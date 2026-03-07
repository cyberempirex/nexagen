"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  export/csv_export.py  ·  Structured CSV export engine                     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Turns NEXAGEN result objects into well-structured CSV files.

Design decisions
────────────────
  • Type-aware: detects list[NameResult], list[AnalysisData],
    list[DomainEntry], list[PlatformEntry], startup report dict,
    and arbitrary list-of-dicts. Each type has its own column schema.
  • Flat: nested fields (domains, platforms, notes, keywords) are
    serialised into readable single-cell strings — no nested CSV.
  • Multi-section: a startup report dict produces a single CSV with
    clearly labelled sections separated by blank rows.
  • Excel-compatible: UTF-8 BOM (optional), proper quoting, no bare
    newlines inside cells, \r\n line endings on Windows.
  • Streaming: rows are written one at a time — large batches never
    hold everything in memory at once.
  • Metadata header: two leading comment rows with tool name, version,
    export timestamp, and record count (can be toggled off).

Public API
──────────
  write_csv(data, path, *, excel_compat, metadata_header) → CsvResult
  export_names_csv(names, path, **kw)       → CsvResult
  export_analysis_csv(analysis, path, **kw) → CsvResult
  export_domains_csv(domains, path, **kw)   → CsvResult
  export_platforms_csv(platforms, path, **kw) → CsvResult
  export_report_csv(report_dict, path, **kw) → CsvResult
  detect_data_type(data)                    → str
  flatten_name_result(nr)                   → dict[str, str]
  flatten_analysis_data(ad)                 → dict[str, str]
  flatten_domain_entry(de)                  → dict[str, str]
  flatten_platform_entry(pe)                → dict[str, str]

Data types returned
───────────────────
  CsvResult — path, rows written, sections, any warnings
"""

from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

from ..config.constants import (
    EXPORT_DIR,
    SLOGAN,
    TOOL_AUTHOR,
    TOOL_NAME,
    VERSION,
)
from ..ui.tables import AnalysisData, DomainEntry, NameResult, PlatformEntry

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

#: String returned by detect_data_type() for each recognised data shape
DTYPE_NAMES      = "names"        # list[NameResult]
DTYPE_ANALYSIS   = "analysis"     # list[AnalysisData]
DTYPE_DOMAINS    = "domains"      # list[DomainEntry]
DTYPE_PLATFORMS  = "platforms"    # list[PlatformEntry]
DTYPE_REPORT     = "report"       # dict with project/names/domains/platforms
DTYPE_DICTS      = "dicts"        # list[dict] — generic fallback
DTYPE_UNKNOWN    = "unknown"      # cannot determine


@dataclass
class CsvResult:
    """
    Return value of every csv_export write function.

    Attributes:
        path:         Absolute path to the written file.
        rows:         Total data rows written (excludes headers / blanks).
        sections:     Number of sections in the file (1 for most, 4 for reports).
        data_type:    Detected input data type (DTYPE_* constant).
        warnings:     Any non-fatal issues encountered during export.
        ok:           True if the file was written without errors.
        file_size:    File size in bytes after writing.
    """
    path:      str
    rows:      int
    sections:  int  = 1
    data_type: str  = DTYPE_UNKNOWN
    warnings:  list[str] = field(default_factory=list)
    ok:        bool = True
    file_size: int  = 0

    def __str__(self) -> str:
        return (
            f"CsvResult(path={self.path!r}, rows={self.rows}, "
            f"type={self.data_type}, ok={self.ok})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 2  TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_data_type(data: Any) -> str:
    """
    Determine the NEXAGEN data type of *data*.

    Inspects the first element of lists, or the dict keys for reports.

    Args:
        data: The data object to inspect.

    Returns:
        One of the DTYPE_* constants.
    """
    if isinstance(data, dict):
        keys = set(data.keys())
        if {"project", "names", "domains", "platforms"} <= keys:
            return DTYPE_REPORT
        return DTYPE_DICTS

    if not isinstance(data, (list, tuple)) or len(data) == 0:
        return DTYPE_UNKNOWN

    first = data[0]
    if isinstance(first, NameResult):
        return DTYPE_NAMES
    if isinstance(first, AnalysisData):
        return DTYPE_ANALYSIS
    if isinstance(first, DomainEntry):
        return DTYPE_DOMAINS
    if isinstance(first, PlatformEntry):
        return DTYPE_PLATFORMS
    if isinstance(first, dict):
        return DTYPE_DICTS

    return DTYPE_UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# § 3  FIELD FLATTENERS  (one per data type)
# ─────────────────────────────────────────────────────────────────────────────

def _safe(v: Any) -> str:
    """Convert any value to a CSV-safe string, stripping bare newlines."""
    return str(v).replace("\n", " ").replace("\r", " ").strip()


def _list_to_cell(lst: Sequence[Any], sep: str = " | ") -> str:
    """Serialise a list to a single cell string."""
    return sep.join(_safe(x) for x in lst) if lst else ""


def _dict_to_cell(d: dict[str, Any]) -> str:
    """Serialise a dict to a 'key=value | key=value' cell string."""
    return " | ".join(f"{k}={_safe(v)}" for k, v in d.items() if v) if d else ""


# ── Column schemas — field order defines CSV column order ─────────────────────

_NAMES_COLUMNS: list[str] = [
    "rank",
    "name",
    "score",
    "tier",
    "pronounce",
    "memorability",
    "uniqueness",
    "length_fit",
    "tm_risk",
    "syllables",
    "best_domain",
    "domain_status",
    "domains_free",
    "platforms",
    "profile",
    "style",
    "keywords",
]

_ANALYSIS_COLUMNS: list[str] = [
    "rank",
    "name",
    "score",
    "tier",
    "pronounce",
    "memorability",
    "uniqueness",
    "length_fit",
    "syllables",
    "vowel_ratio",
    "tm_risk",
    "is_common",
    "phonetic_key",
    "notes",
]

_DOMAINS_COLUMNS: list[str] = [
    "domain",
    "status",
    "tld",
    "tld_rank",
]

_PLATFORMS_COLUMNS: list[str] = [
    "handle",
    "platform",
    "status",
]

_DICTS_COLUMNS: list[str] = []  # derived dynamically from first dict


def flatten_name_result(nr: NameResult, rank: int = 0) -> dict[str, str]:
    """
    Flatten a NameResult dataclass into a single-level string dict.

    Columns: see _NAMES_COLUMNS.

    Nested fields handling:
      - ``domains``  dict[str, str] → best_domain (first free key), domain_status,
                     domains_free (count of free domains)
      - ``platforms`` dict[str, str] → pipe-separated "platform=status" pairs
      - ``keywords``  list[str] → space-separated string

    Args:
        nr:   NameResult instance.
        rank: 1-based rank position (0 = not ranked).

    Returns:
        Flat dict keyed by _NAMES_COLUMNS.
    """
    # Find best domain (first with status "free", else first key)
    best_domain     = ""
    best_status     = ""
    free_count      = 0

    if nr.domains:
        for dom, st in nr.domains.items():
            if st == "free" and not best_domain:
                best_domain = dom
                best_status = st
            if st == "free":
                free_count += 1
        if not best_domain:
            best_domain, best_status = next(iter(nr.domains.items()))

    platforms_cell = _dict_to_cell(nr.platforms)
    keywords_cell  = _list_to_cell(nr.keywords, sep=" ")

    return {
        "rank":          str(rank) if rank else "",
        "name":          _safe(nr.name),
        "score":         str(nr.score),
        "tier":          _safe(nr.tier),
        "pronounce":     str(nr.pronounce),
        "memorability":  str(nr.memorability),
        "uniqueness":    str(nr.uniqueness),
        "length_fit":    str(nr.length_fit),
        "tm_risk":       _safe(nr.tm_risk),
        "syllables":     str(nr.syllables),
        "best_domain":   _safe(best_domain),
        "domain_status": _safe(best_status),
        "domains_free":  str(free_count),
        "platforms":     platforms_cell,
        "profile":       _safe(nr.profile),
        "style":         _safe(nr.style),
        "keywords":      keywords_cell,
    }


def flatten_analysis_data(ad: AnalysisData, rank: int = 0) -> dict[str, str]:
    """
    Flatten an AnalysisData dataclass to a single-level string dict.

    Columns: see _ANALYSIS_COLUMNS.

    Nested fields:
      - ``notes`` list[str] → pipe-separated string

    Args:
        ad:   AnalysisData instance.
        rank: 1-based rank position.

    Returns:
        Flat dict keyed by _ANALYSIS_COLUMNS.
    """
    notes_cell = _list_to_cell(ad.notes)
    return {
        "rank":         str(rank) if rank else "",
        "name":         _safe(ad.name),
        "score":        str(ad.score),
        "tier":         _safe(ad.tier),
        "pronounce":    str(ad.pronounce),
        "memorability": str(ad.memorability),
        "uniqueness":   str(ad.uniqueness),
        "length_fit":   str(ad.length_fit),
        "syllables":    str(ad.syllables),
        "vowel_ratio":  f"{ad.vowel_ratio:.3f}",
        "tm_risk":      _safe(ad.tm_risk),
        "is_common":    "yes" if ad.is_common else "no",
        "phonetic_key": _safe(ad.phonetic_key),
        "notes":        notes_cell,
    }


def flatten_domain_entry(de: DomainEntry) -> dict[str, str]:
    """
    Flatten a DomainEntry to a single-level string dict.

    Columns: domain, status, tld, tld_rank.

    Args:
        de: DomainEntry instance.

    Returns:
        Flat dict keyed by _DOMAINS_COLUMNS.
    """
    return {
        "domain":   _safe(de.domain),
        "status":   _safe(de.status),
        "tld":      _safe(de.tld),
        "tld_rank": str(de.tld_rank),
    }


def flatten_platform_entry(pe: PlatformEntry) -> dict[str, str]:
    """
    Flatten a PlatformEntry to a single-level string dict.

    Columns: handle, platform, status.

    Args:
        pe: PlatformEntry instance.

    Returns:
        Flat dict keyed by _PLATFORMS_COLUMNS.
    """
    return {
        "handle":   _safe(pe.handle),
        "platform": _safe(pe.platform),
        "status":   _safe(pe.status),
    }


def _flatten_generic_dict(d: dict[str, Any]) -> dict[str, str]:
    """Flatten a generic dict — nested values become cell strings."""
    out: dict[str, str] = {}
    for k, v in d.items():
        key = _safe(str(k))
        if isinstance(v, list):
            out[key] = _list_to_cell(v)
        elif isinstance(v, dict):
            out[key] = _dict_to_cell(v)
        else:
            out[key] = _safe(v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# § 4  LOW-LEVEL CSV WRITER
# ─────────────────────────────────────────────────────────────────────────────

def _metadata_rows(
    data_type:  str,
    n_records:  int,
    extra_meta: dict[str, str] | None = None,
) -> list[list[str]]:
    """Build the two leading metadata comment rows."""
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = [
        f"# {TOOL_NAME} CSV Export",
        f"tool={TOOL_NAME}",
        f"version={VERSION}",
        f"author={TOOL_AUTHOR}",
        f"exported_at={now}",
        f"data_type={data_type}",
        f"records={n_records}",
    ]
    if extra_meta:
        for k, v in extra_meta.items():
            meta.append(f"{k}={_safe(v)}")
    # Pack into a two-row block that CSV readers treat as comments
    row1 = [meta[0]]          # "# NEXAGEN CSV Export"
    row2 = meta[1:]           # all key=value pairs on second row
    return [row1, row2]


def _write_section(
    writer:   csv.DictWriter,
    rows:     Sequence[dict[str, str]],
    *,
    fieldnames: list[str],
    section_label: str = "",
    include_header: bool = True,
) -> int:
    """
    Write one section of rows to an open DictWriter.

    Returns the number of data rows written.
    """
    written = 0
    if section_label:
        # Section divider — written as a comment-style single-cell row
        writer.writerow({fieldnames[0]: f"# {section_label}"} |
                        {k: "" for k in fieldnames[1:]})

    if include_header:
        writer.writeheader()

    for row in rows:
        # Fill any missing keys with empty string; truncate any extra keys
        padded = {k: row.get(k, "") for k in fieldnames}
        writer.writerow(padded)
        written += 1

    return written


def _open_csv_file(path: Path, excel_compat: bool) -> io.TextIOWrapper:
    """Open a CSV output file with correct encoding and newline handling."""
    if excel_compat:
        # UTF-8 BOM + \r\n — Excel on Windows reads this correctly
        return path.open("w", newline="", encoding="utf-8-sig")
    return path.open("w", newline="", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# § 5  TYPE-SPECIFIC EXPORT FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def export_names_csv(
    names:           Sequence[NameResult],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """
    Export a list of NameResult objects to CSV.

    Columns (in order):
        rank · name · score · tier · pronounce · memorability ·
        uniqueness · length_fit · tm_risk · syllables ·
        best_domain · domain_status · domains_free · platforms ·
        profile · style · keywords

    Args:
        names:           List of NameResult instances to export.
        path:            Output file path.
        excel_compat:    Write UTF-8 BOM for Excel compatibility.
        metadata_header: Include two leading comment rows.

    Returns:
        :class:`CsvResult`.
    """
    warnings: list[str] = []
    if not names:
        warnings.append("Empty names list — no rows written")

    rows     = [flatten_name_result(nr, rank=i + 1) for i, nr in enumerate(names)]
    columns  = _NAMES_COLUMNS

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            if metadata_header:
                # Write metadata as plain lines (not CSV-parsed)
                for meta_row in _metadata_rows(DTYPE_NAMES, len(rows)):
                    fh.write(",".join(meta_row) + os.linesep)

            writer = csv.DictWriter(
                fh, fieldnames=columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            written = _write_section(writer, rows, fieldnames=columns)

        size = path.stat().st_size
        log.info("Exported %d NameResult rows to %s (%d bytes)", written, path, size)
        return CsvResult(
            path=str(path), rows=written, sections=1,
            data_type=DTYPE_NAMES, warnings=warnings,
            ok=True, file_size=size,
        )
    except OSError as exc:
        log.error("CSV write failed: %s", exc)
        return CsvResult(
            path=str(path), rows=0,
            data_type=DTYPE_NAMES, ok=False,
            warnings=[str(exc)],
        )


def export_analysis_csv(
    analysis:        Sequence[AnalysisData],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """
    Export a list of AnalysisData objects to CSV.

    Columns (in order):
        rank · name · score · tier · pronounce · memorability ·
        uniqueness · length_fit · syllables · vowel_ratio ·
        tm_risk · is_common · phonetic_key · notes

    Args:
        analysis:        List of AnalysisData instances.
        path:            Output file path.
        excel_compat:    Write UTF-8 BOM.
        metadata_header: Include leading metadata rows.

    Returns:
        :class:`CsvResult`.
    """
    warnings: list[str] = []
    if not analysis:
        warnings.append("Empty analysis list — no rows written")

    rows    = [flatten_analysis_data(ad, rank=i + 1) for i, ad in enumerate(analysis)]
    columns = _ANALYSIS_COLUMNS

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            if metadata_header:
                for meta_row in _metadata_rows(DTYPE_ANALYSIS, len(rows)):
                    fh.write(",".join(meta_row) + os.linesep)

            writer = csv.DictWriter(
                fh, fieldnames=columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            written = _write_section(writer, rows, fieldnames=columns)

        size = path.stat().st_size
        return CsvResult(
            path=str(path), rows=written, sections=1,
            data_type=DTYPE_ANALYSIS, warnings=warnings,
            ok=True, file_size=size,
        )
    except OSError as exc:
        log.error("CSV write failed: %s", exc)
        return CsvResult(
            path=str(path), rows=0,
            data_type=DTYPE_ANALYSIS, ok=False, warnings=[str(exc)],
        )


def export_domains_csv(
    domains:         Sequence[DomainEntry],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """
    Export a list of DomainEntry objects to CSV.

    Columns: domain · status · tld · tld_rank

    Args:
        domains:         List of DomainEntry instances.
        path:            Output file path.
        excel_compat:    Write UTF-8 BOM.
        metadata_header: Include leading metadata rows.

    Returns:
        :class:`CsvResult`.
    """
    warnings: list[str] = []
    rows    = [flatten_domain_entry(de) for de in domains]
    columns = _DOMAINS_COLUMNS

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            if metadata_header:
                for meta_row in _metadata_rows(DTYPE_DOMAINS, len(rows)):
                    fh.write(",".join(meta_row) + os.linesep)

            writer = csv.DictWriter(
                fh, fieldnames=columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            written = _write_section(writer, rows, fieldnames=columns)

        size = path.stat().st_size
        return CsvResult(
            path=str(path), rows=written, sections=1,
            data_type=DTYPE_DOMAINS, warnings=warnings,
            ok=True, file_size=size,
        )
    except OSError as exc:
        log.error("CSV write failed: %s", exc)
        return CsvResult(
            path=str(path), rows=0,
            data_type=DTYPE_DOMAINS, ok=False, warnings=[str(exc)],
        )


def export_platforms_csv(
    platforms:       Sequence[PlatformEntry],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """
    Export a list of PlatformEntry objects to CSV.

    Columns: handle · platform · status

    Args:
        platforms:       List of PlatformEntry instances.
        path:            Output file path.
        excel_compat:    Write UTF-8 BOM.
        metadata_header: Include leading metadata rows.

    Returns:
        :class:`CsvResult`.
    """
    warnings: list[str] = []
    rows    = [flatten_platform_entry(pe) for pe in platforms]
    columns = _PLATFORMS_COLUMNS

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            if metadata_header:
                for meta_row in _metadata_rows(DTYPE_PLATFORMS, len(rows)):
                    fh.write(",".join(meta_row) + os.linesep)

            writer = csv.DictWriter(
                fh, fieldnames=columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            written = _write_section(writer, rows, fieldnames=columns)

        size = path.stat().st_size
        return CsvResult(
            path=str(path), rows=written, sections=1,
            data_type=DTYPE_PLATFORMS, warnings=warnings,
            ok=True, file_size=size,
        )
    except OSError as exc:
        log.error("CSV write failed: %s", exc)
        return CsvResult(
            path=str(path), rows=0,
            data_type=DTYPE_PLATFORMS, ok=False, warnings=[str(exc)],
        )


def export_report_csv(
    report:          dict[str, Any],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """
    Export a startup naming report dict to a multi-section CSV.

    The dict must contain keys: ``project``, ``keywords``, ``names``,
    ``domains``, ``platforms`` (as returned by ``cmd_startup_report``).

    File structure (sections separated by one blank row)::

        # Section 1 — Report Metadata  (project, keywords, stats)
        # Section 2 — Generated Names  (NameResult rows)
        # Section 3 — Domain Checks    (DomainEntry rows)
        # Section 4 — Platform Checks  (PlatformEntry rows)

    Args:
        report:          Startup report dict.
        path:            Output file path.
        excel_compat:    Write UTF-8 BOM.
        metadata_header: Include file-level metadata comment rows.

    Returns:
        :class:`CsvResult` with ``sections=4``.
    """
    warnings: list[str] = []

    project   = report.get("project", "")
    keywords  = report.get("keywords", [])
    names     = report.get("names", [])
    domains   = report.get("domains", [])
    platforms = report.get("platforms", [])
    elapsed   = report.get("elapsed", 0.0)
    n_gen     = report.get("names_generated", len(names))
    n_checks  = report.get("checks_run", 0)

    total_rows = 0
    sections   = 0

    # Column schemas per section — must all be the widest we'll write
    meta_columns    = ["key", "value"]
    name_columns    = _NAMES_COLUMNS
    domain_columns  = _DOMAINS_COLUMNS
    platform_columns = _PLATFORMS_COLUMNS

    # Build metadata section rows
    kw_str = _list_to_cell(keywords, sep=", ")
    meta_rows: list[dict[str, str]] = [
        {"key": "project",        "value": _safe(project)},
        {"key": "keywords",       "value": kw_str},
        {"key": "names_generated","value": str(n_gen)},
        {"key": "checks_run",     "value": str(n_checks)},
        {"key": "elapsed_sec",    "value": f"{elapsed:.2f}"},
        {"key": "exported_at",    "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        {"key": "tool",           "value": f"{TOOL_NAME} v{VERSION}"},
        {"key": "author",         "value": TOOL_AUTHOR},
    ]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            # File-level metadata comment
            if metadata_header:
                extra = {"project": _safe(project), "total_names": str(n_gen)}
                for meta_row in _metadata_rows(DTYPE_REPORT, n_gen, extra):
                    fh.write(",".join(meta_row) + os.linesep)
                fh.write(os.linesep)

            # ── Section 1: Report Metadata ────────────────────────────────────
            w1 = csv.DictWriter(
                fh, fieldnames=meta_columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            total_rows += _write_section(
                w1, meta_rows, fieldnames=meta_columns,
                section_label=f"Report Metadata — {project}",
            )
            sections += 1
            fh.write(os.linesep)

            # ── Section 2: Generated Names ────────────────────────────────────
            name_rows: list[dict[str, str]] = []
            for i, item in enumerate(names):
                if isinstance(item, NameResult):
                    name_rows.append(flatten_name_result(item, rank=i + 1))
                elif isinstance(item, dict):
                    name_rows.append(_flatten_generic_dict(item))

            if name_rows:
                w2 = csv.DictWriter(
                    fh, fieldnames=name_columns,
                    extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
                )
                total_rows += _write_section(
                    w2, name_rows, fieldnames=name_columns,
                    section_label="Generated Names",
                )
                sections += 1
                fh.write(os.linesep)
            else:
                warnings.append("No name rows in report")

            # ── Section 3: Domain Checks ──────────────────────────────────────
            domain_rows: list[dict[str, str]] = []
            for item in domains:
                if isinstance(item, DomainEntry):
                    domain_rows.append(flatten_domain_entry(item))
                elif isinstance(item, dict):
                    domain_rows.append(_flatten_generic_dict(item))

            if domain_rows:
                w3 = csv.DictWriter(
                    fh, fieldnames=domain_columns,
                    extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
                )
                total_rows += _write_section(
                    w3, domain_rows, fieldnames=domain_columns,
                    section_label="Domain Checks",
                )
                sections += 1
                fh.write(os.linesep)
            else:
                warnings.append("No domain rows in report")

            # ── Section 4: Platform Checks ────────────────────────────────────
            platform_rows: list[dict[str, str]] = []
            for item in platforms:
                if isinstance(item, PlatformEntry):
                    platform_rows.append(flatten_platform_entry(item))
                elif isinstance(item, dict):
                    platform_rows.append(_flatten_generic_dict(item))

            if platform_rows:
                w4 = csv.DictWriter(
                    fh, fieldnames=platform_columns,
                    extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
                )
                total_rows += _write_section(
                    w4, platform_rows, fieldnames=platform_columns,
                    section_label="Platform Checks",
                )
                sections += 1

        size = path.stat().st_size
        log.info(
            "Exported report '%s' — %d rows, %d sections → %s (%d bytes)",
            project, total_rows, sections, path, size,
        )
        return CsvResult(
            path=str(path), rows=total_rows, sections=sections,
            data_type=DTYPE_REPORT, warnings=warnings,
            ok=True, file_size=size,
        )

    except OSError as exc:
        log.error("Report CSV write failed: %s", exc)
        return CsvResult(
            path=str(path), rows=0, sections=0,
            data_type=DTYPE_REPORT, ok=False, warnings=[str(exc)],
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 6  GENERIC FALLBACK WRITER
# ─────────────────────────────────────────────────────────────────────────────

def _export_generic_dicts(
    data:            Sequence[dict[str, Any]],
    path:            Path,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
) -> CsvResult:
    """Write a list of arbitrary dicts as CSV.  Column order from first row."""
    warnings: list[str] = []
    if not data:
        warnings.append("Empty data list")

    rows    = [_flatten_generic_dict(d) for d in data]
    columns = list(rows[0].keys()) if rows else ["value"]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _open_csv_file(path, excel_compat) as fh:
            if metadata_header:
                for meta_row in _metadata_rows(DTYPE_DICTS, len(rows)):
                    fh.write(",".join(meta_row) + os.linesep)

            writer = csv.DictWriter(
                fh, fieldnames=columns,
                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL,
            )
            written = _write_section(writer, rows, fieldnames=columns)

        size = path.stat().st_size
        return CsvResult(
            path=str(path), rows=written, sections=1,
            data_type=DTYPE_DICTS, warnings=warnings,
            ok=True, file_size=size,
        )
    except OSError as exc:
        return CsvResult(
            path=str(path), rows=0,
            data_type=DTYPE_DICTS, ok=False, warnings=[str(exc)],
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 7  UNIFIED ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def write_csv(
    data:            Any,
    path:            Optional[Path] = None,
    *,
    excel_compat:    bool = False,
    metadata_header: bool = True,
    label:           str  = "",
) -> CsvResult:
    """
    Auto-detect the data type and write to CSV.

    This is the main public entry point.  It inspects *data* and delegates
    to the appropriate type-specific export function.

    Args:
        data:            Any supported data type:
                           - list[NameResult]
                           - list[AnalysisData]
                           - list[DomainEntry]
                           - list[PlatformEntry]
                           - dict with project/names/domains/platforms keys
                           - list[dict]  (generic fallback)
        path:            Output file path.  If None, auto-generates a
                         timestamped path under EXPORT_DIR.
        excel_compat:    Write UTF-8 BOM for Excel on Windows.
        metadata_header: Write two leading comment/metadata rows.
        label:           Optional filename prefix for auto-generated paths.

    Returns:
        :class:`CsvResult`.

    Raises:
        ValueError: If *data* is not a supported type.

    Example::

        from nexagen.export.csv_export import write_csv
        result = write_csv(name_results, Path("~/exports/names.csv"))
        print(f"Wrote {result.rows} rows to {result.path}")
    """
    dtype = detect_data_type(data)

    # Auto-generate path if not provided
    if path is None:
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem     = f"{label or 'nexagen'}_{ts}" if label else f"nexagen_{ts}"
        out_dir  = EXPORT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{stem}.csv"

    kwargs = dict(excel_compat=excel_compat, metadata_header=metadata_header)

    if dtype == DTYPE_NAMES:
        return export_names_csv(data, path, **kwargs)

    if dtype == DTYPE_ANALYSIS:
        return export_analysis_csv(data, path, **kwargs)

    if dtype == DTYPE_DOMAINS:
        return export_domains_csv(data, path, **kwargs)

    if dtype == DTYPE_PLATFORMS:
        return export_platforms_csv(data, path, **kwargs)

    if dtype == DTYPE_REPORT:
        return export_report_csv(data, path, **kwargs)

    if dtype == DTYPE_DICTS:
        return _export_generic_dicts(data, path, **kwargs)

    return CsvResult(
        path=str(path), rows=0, data_type=DTYPE_UNKNOWN, ok=False,
        warnings=[f"Unsupported data type: {type(data).__name__}"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 8  UTILITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def csv_preview(
    path:     Path,
    n_rows:   int = 5,
    *,
    skip_meta: bool = True,
) -> list[list[str]]:
    """
    Read the first *n_rows* data rows from a CSV file.

    Args:
        path:      Path to an existing CSV file.
        n_rows:    Maximum data rows to return.
        skip_meta: If True, skip leading comment rows (lines starting with #).

    Returns:
        List of rows, each a list of cell strings.
        Returns empty list on any read error.
    """
    rows: list[list[str]] = []
    try:
        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            for raw in reader:
                if skip_meta and raw and raw[0].startswith("#"):
                    continue
                rows.append(raw)
                if len(rows) >= n_rows + 1:  # +1 for header
                    break
    except (OSError, csv.Error) as exc:
        log.debug("csv_preview failed: %s", exc)
    return rows


def column_names(path: Path, *, skip_meta: bool = True) -> list[str]:
    """
    Return the header row of a NEXAGEN CSV file.

    Args:
        path:      Path to an existing CSV file.
        skip_meta: Skip leading comment rows.

    Returns:
        List of column name strings, or empty list on error.
    """
    preview = csv_preview(path, n_rows=0, skip_meta=skip_meta)
    return preview[0] if preview else []


def schema_for_type(dtype: str) -> list[str]:
    """
    Return the column schema for a given data type string.

    Args:
        dtype: One of the DTYPE_* constants.

    Returns:
        Ordered list of column names for that type.
        Returns empty list for unknown types.
    """
    schemas: dict[str, list[str]] = {
        DTYPE_NAMES:     _NAMES_COLUMNS,
        DTYPE_ANALYSIS:  _ANALYSIS_COLUMNS,
        DTYPE_DOMAINS:   _DOMAINS_COLUMNS,
        DTYPE_PLATFORMS: _PLATFORMS_COLUMNS,
    }
    return list(schemas.get(dtype, []))
