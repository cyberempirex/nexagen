"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  export/json_export.py  ·  Structured JSON export engine                   ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Turns NEXAGEN result objects into structured, human-readable JSON files.

Design decisions
────────────────
  • Schema-stamped: every output file carries a ``nexagen_schema`` header
    block with tool name, version, export timestamp, data type, and record
    count so consumers can parse without documentation.
  • Type-aware: detects list[NameResult], list[AnalysisData],
    list[DomainEntry], list[PlatformEntry], and the startup report dict.
    Each type gets its own section structure in the output.
  • Dataclass-safe: converts all @dataclass objects (and nested ones)
    recursively before serialising — no TypeError from non-JSON types.
  • Pretty by default: 2-space indent with ensure_ascii=False so Unicode
    brand names survive intact.
  • Multi-section report: the startup report dict produces a single JSON
    document with four top-level sections (metadata / names / domains /
    platforms) mirroring the CSV multi-section structure.

Public API
──────────
  write_json(data, path, *, indent, metadata)   → JsonResult
  export_names_json(names, path, **kw)           → JsonResult
  export_analysis_json(analysis, path, **kw)     → JsonResult
  export_domains_json(domains, path, **kw)       → JsonResult
  export_platforms_json(platforms, path, **kw)   → JsonResult
  export_report_json(report_dict, path, **kw)    → JsonResult
  detect_data_type(data)                         → str   (same constants as csv_export)
  serialise(obj)                                 → JSON-safe value

Data structures
───────────────
  JsonResult — path, records written, sections, data_type, warnings, ok
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from ..config.constants import (
    EXPORT_DIR,
    SLOGAN,
    TOOL_AUTHOR,
    TOOL_NAME,
    TOOL_REPO,
    TOOL_TAGLINE,
    VERSION,
)
from ..ui.tables import AnalysisData, DomainEntry, NameResult, PlatformEntry

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  TYPE CONSTANTS  (mirrors csv_export)
# ─────────────────────────────────────────────────────────────────────────────

DTYPE_NAMES      = "names"
DTYPE_ANALYSIS   = "analysis"
DTYPE_DOMAINS    = "domains"
DTYPE_PLATFORMS  = "platforms"
DTYPE_REPORT     = "report"
DTYPE_DICTS      = "dicts"
DTYPE_UNKNOWN    = "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# § 2  RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class JsonResult:
    """
    Return value of every json_export write function.

    Attributes:
        path:       Absolute path to the written file.
        records:    Number of data records serialised.
        sections:   Top-level sections in the JSON document.
        data_type:  Detected input data type (DTYPE_* constant).
        warnings:   Any non-fatal issues encountered during export.
        ok:         True if the file was written successfully.
        file_size:  File size in bytes after writing.
    """
    path:      str
    records:   int
    sections:  int  = 1
    data_type: str  = DTYPE_UNKNOWN
    warnings:  list[str] = field(default_factory=list)
    ok:        bool = True
    file_size: int  = 0

    def __str__(self) -> str:
        return (
            f"JsonResult(path={self.path!r}, records={self.records}, "
            f"type={self.data_type}, ok={self.ok})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  TYPE DETECTION  (mirrors csv_export.detect_data_type)
# ─────────────────────────────────────────────────────────────────────────────

def detect_data_type(data: Any) -> str:
    """
    Determine the NEXAGEN data type of *data*.

    Inspects the first element of lists, or the dict keys for reports.

    Args:
        data: Any value to classify.

    Returns:
        One of the DTYPE_* string constants.
    """
    if isinstance(data, dict):
        if "project" in data and "names" in data:
            return DTYPE_REPORT
        return DTYPE_DICTS

    if isinstance(data, (list, tuple)) and data:
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
# § 4  SERIALISATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def serialise(obj: Any) -> Any:
    """
    Recursively convert *obj* to a JSON-safe primitive.

    Handles:
      - @dataclass objects   → dict via dataclasses.asdict
      - list / tuple         → list (elements recursively serialised)
      - dict                 → dict (values recursively serialised)
      - Path                 → str
      - Enum members         → .value
      - Everything else      → left as-is (int, float, str, bool, None)

    Args:
        obj: Any Python object.

    Returns:
        A JSON-serialisable value.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return {k: serialise(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [serialise(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): serialise(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "value") and hasattr(obj, "_value_"):
        # Enum member
        return obj.value
    return obj


def _schema_header(
    data_type: str,
    records:   int,
    extra:     Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the standard nexagen_schema header block."""
    block: dict[str, Any] = {
        "tool":        TOOL_NAME,
        "tagline":     TOOL_TAGLINE,
        "version":     VERSION,
        "author":      TOOL_AUTHOR,
        "repository":  TOOL_REPO,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "data_type":   data_type,
        "records":     records,
    }
    if extra:
        block.update(extra)
    return block


def _auto_path(label: str = "") -> Path:
    """Generate a timestamped output path under EXPORT_DIR."""
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{label}_{ts}" if label else f"nexagen_{ts}"
    out_dir = EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}.json"


def _finish(path: Path, payload: dict, records: int, dtype: str,
            sections: int, warnings: list[str]) -> JsonResult:
    """Serialise *payload* to *path* and return a JsonResult."""
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        size = path.stat().st_size
        log.debug("JSON export: %s  (%d bytes)", path, size)
        return JsonResult(
            path=str(path), records=records, sections=sections,
            data_type=dtype, warnings=warnings, ok=True, file_size=size,
        )
    except (OSError, TypeError) as exc:
        log.error("JSON write failed: %s", exc)
        return JsonResult(
            path=str(path), records=records, sections=sections,
            data_type=dtype, warnings=[str(exc)], ok=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SERIALISE HELPERS PER DATA TYPE
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_name_result(nr: NameResult, rank: int = 0) -> dict[str, Any]:
    """
    Serialise a NameResult to a rich JSON object.

    Keeps nested structures (domains, platforms, keywords) as native
    JSON objects/arrays rather than flattening to strings.
    """
    # Identify best free domain
    best_domain = ""
    best_status = ""
    free_domains: list[str] = []

    for dom, st in (nr.domains or {}).items():
        if st == "free":
            free_domains.append(dom)
            if not best_domain:
                best_domain = dom
                best_status = st
    if not best_domain and nr.domains:
        best_domain, best_status = next(iter(nr.domains.items()))

    return {
        "rank":         rank or None,
        "name":         nr.name,
        "score":        nr.score,
        "tier":         nr.tier,
        "sub_scores": {
            "pronounce":    nr.pronounce,
            "memorability": nr.memorability,
            "uniqueness":   nr.uniqueness,
            "length_fit":   nr.length_fit,
        },
        "tm_risk":       nr.tm_risk,
        "syllables":     nr.syllables,
        "profile":       nr.profile,
        "style":         nr.style,
        "keywords":      nr.keywords,
        "domains":       nr.domains,
        "best_domain":   best_domain,
        "free_domains":  free_domains,
        "platforms":     nr.platforms,
    }


def _serialise_analysis_data(ad: AnalysisData, rank: int = 0) -> dict[str, Any]:
    """Serialise an AnalysisData to a structured JSON object."""
    return {
        "rank":         rank or None,
        "name":         ad.name,
        "score":        ad.score,
        "tier":         ad.tier,
        "sub_scores": {
            "pronounce":    ad.pronounce,
            "memorability": ad.memorability,
            "uniqueness":   ad.uniqueness,
            "length_fit":   ad.length_fit,
        },
        "syllables":    ad.syllables,
        "vowel_ratio":  round(ad.vowel_ratio, 4),
        "tm_risk":      ad.tm_risk,
        "is_common":    ad.is_common,
        "phonetic_key": ad.phonetic_key,
        "notes":        ad.notes,
    }


def _serialise_domain_entry(de: DomainEntry) -> dict[str, Any]:
    """Serialise a DomainEntry to a JSON object."""
    return {
        "domain":   de.domain,
        "tld":      de.tld,
        "status":   de.status,
        "tld_rank": de.tld_rank,
    }


def _serialise_platform_entry(pe: PlatformEntry) -> dict[str, Any]:
    """Serialise a PlatformEntry to a JSON object."""
    return {
        "platform": pe.platform,
        "handle":   pe.handle,
        "status":   pe.status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# § 6  TYPE-SPECIFIC EXPORT FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def export_names_json(
    names:    Sequence[NameResult],
    path:     Optional[Path] = None,
    *,
    indent:   int  = 2,
    metadata: bool = True,
    label:    str  = "names",
) -> JsonResult:
    """
    Export a list of NameResult objects to a JSON file.

    Args:
        names:    Name generation results.
        path:     Output path. Auto-generated if None.
        indent:   JSON indentation level (default 2).
        metadata: Include nexagen_schema header block.
        label:    Filename prefix for auto-generated paths.

    Returns:
        :class:`JsonResult`
    """
    if path is None:
        path = _auto_path(label)

    serialised = [_serialise_name_result(nr, i+1) for i, nr in enumerate(names)]
    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(DTYPE_NAMES, len(serialised))
    payload["names"] = serialised

    return _finish(Path(path), payload, len(serialised), DTYPE_NAMES, 1, [])


def export_analysis_json(
    analysis: Sequence[AnalysisData],
    path:     Optional[Path] = None,
    *,
    indent:   int  = 2,
    metadata: bool = True,
    label:    str  = "analysis",
) -> JsonResult:
    """
    Export a list of AnalysisData objects to a JSON file.

    Args:
        analysis: Brand analysis results.
        path:     Output path. Auto-generated if None.
        indent:   JSON indentation level.
        metadata: Include nexagen_schema header block.
        label:    Filename prefix.

    Returns:
        :class:`JsonResult`
    """
    if path is None:
        path = _auto_path(label)

    serialised = [_serialise_analysis_data(ad, i+1) for i, ad in enumerate(analysis)]
    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(DTYPE_ANALYSIS, len(serialised))
    payload["analysis"] = serialised

    return _finish(Path(path), payload, len(serialised), DTYPE_ANALYSIS, 1, [])


def export_domains_json(
    domains: Sequence[DomainEntry],
    path:    Optional[Path] = None,
    *,
    metadata: bool = True,
    label:    str  = "domains",
) -> JsonResult:
    """
    Export a list of DomainEntry objects to a JSON file.

    Args:
        domains:  Domain availability results.
        path:     Output path. Auto-generated if None.
        metadata: Include nexagen_schema header block.
        label:    Filename prefix.

    Returns:
        :class:`JsonResult`
    """
    if path is None:
        path = _auto_path(label)

    serialised = [_serialise_domain_entry(de) for de in domains]
    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(DTYPE_DOMAINS, len(serialised))
    payload["domains"] = serialised

    return _finish(Path(path), payload, len(serialised), DTYPE_DOMAINS, 1, [])


def export_platforms_json(
    platforms: Sequence[PlatformEntry],
    path:      Optional[Path] = None,
    *,
    metadata:  bool = True,
    label:     str  = "platforms",
) -> JsonResult:
    """
    Export a list of PlatformEntry objects to a JSON file.

    Args:
        platforms: Platform handle check results.
        path:      Output path. Auto-generated if None.
        metadata:  Include nexagen_schema header block.
        label:     Filename prefix.

    Returns:
        :class:`JsonResult`
    """
    if path is None:
        path = _auto_path(label)

    serialised = [_serialise_platform_entry(pe) for pe in platforms]
    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(DTYPE_PLATFORMS, len(serialised))
    payload["platforms"] = serialised

    return _finish(Path(path), payload, len(serialised), DTYPE_PLATFORMS, 1, [])


def export_report_json(
    report:   dict[str, Any],
    path:     Optional[Path] = None,
    *,
    metadata: bool = True,
    label:    str  = "report",
) -> JsonResult:
    """
    Export a startup naming report dict to a structured JSON file.

    The dict must contain the keys returned by ``cmd_startup_report()``:
    ``project``, ``keywords``, ``names``, ``domains``, ``platforms``,
    ``names_generated``, ``checks_run``, ``elapsed``.

    Output structure::

        {
          "nexagen_schema": { ... },
          "report": {
            "project": "...",
            "keywords": [...],
            "generated_at": "...",
            "elapsed_sec": 0.0,
            "names_generated": 0,
            "checks_run": 0
          },
          "names":     [ ... ],
          "domains":   [ ... ],
          "platforms": [ ... ]
        }

    Args:
        report:   Startup report dict from ``cmd_startup_report()``.
        path:     Output path. Auto-generated if None.
        metadata: Include nexagen_schema header block.
        label:    Filename prefix.

    Returns:
        :class:`JsonResult` with ``sections=4``.
    """
    if path is None:
        path = _auto_path(label)

    project   = report.get("project", "")
    keywords  = report.get("keywords", [])
    names     = report.get("names", [])
    domains   = report.get("domains", [])
    platforms = report.get("platforms", [])
    elapsed   = report.get("elapsed", 0.0)
    n_gen     = report.get("names_generated", len(names))
    n_checks  = report.get("checks_run", 0)

    s_names     = [_serialise_name_result(nr, i+1) for i, nr in enumerate(names)]
    s_domains   = [_serialise_domain_entry(de) for de in domains]
    s_platforms = [_serialise_platform_entry(pe) for pe in platforms]

    total_records = len(s_names) + len(s_domains) + len(s_platforms)

    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(
            DTYPE_REPORT, total_records,
            extra={"project": project, "slogan": SLOGAN},
        )

    payload["report"] = {
        "project":         project,
        "keywords":        keywords,
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "elapsed_sec":     round(elapsed, 3),
        "names_generated": n_gen,
        "checks_run":      n_checks,
    }
    payload["names"]     = s_names
    payload["domains"]   = s_domains
    payload["platforms"] = s_platforms

    return _finish(Path(path), payload, total_records, DTYPE_REPORT, 4, [])


# ─────────────────────────────────────────────────────────────────────────────
# § 7  MAIN DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def write_json(
    data:     Any,
    path:     Optional[Path] = None,
    *,
    indent:   int  = 2,
    metadata: bool = True,
    label:    str  = "",
) -> JsonResult:
    """
    Auto-detect the data type and write to JSON.

    The main public entry point.  Inspects *data* and delegates to the
    appropriate type-specific export function.

    Args:
        data:     Any supported type:
                    - list[NameResult]
                    - list[AnalysisData]
                    - list[DomainEntry]
                    - list[PlatformEntry]
                    - dict (startup report or arbitrary dict)
                    - list[dict]  (generic fallback)
        path:     Output file path. If None, auto-generates a timestamped
                  path under EXPORT_DIR.
        indent:   JSON indent depth (default 2).
        metadata: Include nexagen_schema header block.
        label:    Optional filename prefix for auto-generated paths.

    Returns:
        :class:`JsonResult`

    Example::

        from nexagen.export.json_export import write_json
        result = write_json(name_results, Path("~/exports/names.json"))
        print(f"Wrote {result.records} records to {result.path}")
    """
    dtype = detect_data_type(data)

    dispatch = {
        DTYPE_NAMES:     lambda: export_names_json(data, path, indent=indent, metadata=metadata, label=label or "names"),
        DTYPE_ANALYSIS:  lambda: export_analysis_json(data, path, indent=indent, metadata=metadata, label=label or "analysis"),
        DTYPE_DOMAINS:   lambda: export_domains_json(data, path, metadata=metadata, label=label or "domains"),
        DTYPE_PLATFORMS: lambda: export_platforms_json(data, path, metadata=metadata, label=label or "platforms"),
        DTYPE_REPORT:    lambda: export_report_json(data, path, metadata=metadata, label=label or "report"),
    }

    if dtype in dispatch:
        return dispatch[dtype]()

    # Generic fallback — list of dicts or unknown
    if path is None:
        path = _auto_path(label or "export")

    try:
        serialised = serialise(data)
    except Exception as exc:
        serialised = str(data)

    records = len(serialised) if isinstance(serialised, list) else 1
    payload: dict[str, Any] = {}
    if metadata:
        payload["nexagen_schema"] = _schema_header(DTYPE_DICTS, records)
    payload["data"] = serialised

    return _finish(Path(path), payload, records, dtype, 1, [])


# ─────────────────────────────────────────────────────────────────────────────
# § 8  UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def json_preview(path: Union[str, Path], max_chars: int = 600) -> str:
    """
    Return the first *max_chars* characters of a JSON export file.

    Useful for quick inspection in the CLI.

    Args:
        path:      Path to the JSON file.
        max_chars: Maximum characters to return.

    Returns:
        Truncated file content string.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n… [{len(text) - max_chars} chars remaining]"
        return text
    except OSError as exc:
        return f"[Could not read {path}: {exc}]"


def load_json_export(path: Union[str, Path]) -> dict[str, Any]:
    """
    Load and parse a NEXAGEN JSON export file.

    Args:
        path: Path to the JSON export file.

    Returns:
        Parsed JSON as a Python dict.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schema_version(path: Union[str, Path]) -> str:
    """
    Extract the NEXAGEN version string from an export file's schema header.

    Args:
        path: Path to the JSON export file.

    Returns:
        Version string, or ``"unknown"`` if not found.
    """
    try:
        data = load_json_export(path)
        return str(data.get("nexagen_schema", {}).get("version", "unknown"))
    except Exception:
        return "unknown"
