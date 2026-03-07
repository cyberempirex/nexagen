"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  export/report_builder.py  ·  Unified report assembly & multi-format export║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Unified report assembly and multi-format export orchestrator.

This module sits above the three format-specific exporters (csv_export,
json_export, markdown_export) and provides:

  1. A :class:`ReportBuilder` that assembles structured ``ReportPackage``
     objects from raw NEXAGEN result data.
  2. Multi-format dispatch — write CSV + JSON + Markdown in a single call
     with consistent filenames and a shared output directory.
  3. An auto-export helper that respects ``cfg.auto_export`` and
     ``cfg.export_format`` from Settings.
  4. Report validation — checks that the input data is well-formed before
     any I/O occurs.
  5. Export summary helpers used by the CLI to display confirmation strips.

Report structure (``ReportPackage``)
──────────────────────────────────────
  A ``ReportPackage`` mirrors the dict returned by ``cmd_startup_report()``:
    project          str                  project / startup name
    keywords         list[str]            seed keywords
    names            list[NameResult]     scored name candidates
    domains          list[DomainEntry]    domain availability results
    platforms        list[PlatformEntry]  handle availability results
    names_generated  int
    checks_run       int
    elapsed          float                wall-clock seconds for generation
    generated_at     datetime

  It also adds summary fields computed on construction:
    top_name         str     highest-scoring name
    best_domain      str     first free domain found
    free_domain_count  int
    free_platform_count int

Public API
──────────
  ReportBuilder.from_report_dict(d)       → ReportPackage
  ReportBuilder.from_parts(...)           → ReportPackage
  ReportBuilder.export(pkg, cfg, formats) → ExportManifest
  build_report(data, cfg)                 → ExportManifest
  auto_export(data, cfg)                  → ExportManifest | None
  validate_report(data)                   → list[str]  (errors)

Data structures
───────────────
  ReportPackage    — structured report object
  ExportResult     — path + format + ok for one file
  ExportManifest   — all ExportResult objects from one export call
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from ..config.constants import (
    EXPORT_DIR,
    TOOL_AUTHOR,
    TOOL_NAME,
    VERSION,
)
from ..config.settings import Settings, get_settings
from ..ui.tables import AnalysisData, DomainEntry, NameResult, PlatformEntry

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReportPackage:
    """
    Structured representation of a full NEXAGEN naming report.

    Constructed by :class:`ReportBuilder` from either a raw report dict
    (as returned by ``cmd_startup_report()``) or individual components.

    Attributes:
        project:             Project / startup name.
        keywords:            Seed keywords used for generation.
        names:               Scored name candidates (sorted best-first).
        domains:             Domain availability results.
        platforms:           Platform handle availability results.
        names_generated:     Total names generated (may differ from len(names)
                             if a top-N slice was applied).
        checks_run:          Total domain + platform checks performed.
        elapsed:             Wall-clock seconds for the generation pipeline.
        generated_at:        When the report was assembled.
        top_name:            The highest-scoring name (computed on init).
        best_domain:         First domain confirmed as free (computed on init).
        free_domain_count:   Number of free domains found.
        free_platform_count: Number of free platform handles found.
    """
    project:             str
    keywords:            list[str]
    names:               list[NameResult]
    domains:             list[DomainEntry]
    platforms:           list[PlatformEntry]
    names_generated:     int  = 0
    checks_run:          int  = 0
    elapsed:             float = 0.0
    generated_at:        datetime = field(default_factory=datetime.now)

    # Computed on init
    top_name:            str = field(init=False, default="")
    best_domain:         str = field(init=False, default="")
    free_domain_count:   int = field(init=False, default=0)
    free_platform_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.top_name  = self.names[0].name if self.names else ""
        free_doms      = [d for d in self.domains if d.status == "free"]
        free_plats     = [p for p in self.platforms if p.status == "free"]
        self.best_domain          = free_doms[0].domain if free_doms else ""
        self.free_domain_count    = len(free_doms)
        self.free_platform_count  = len(free_plats)
        if not self.names_generated:
            self.names_generated = len(self.names)
        if not self.checks_run:
            self.checks_run = len(self.domains) + len(self.platforms)

    def to_dict(self) -> dict[str, Any]:
        """Convert to the standard report dict consumed by exporters."""
        return {
            "project":         self.project,
            "keywords":        self.keywords,
            "names":           self.names,
            "domains":         self.domains,
            "platforms":       self.platforms,
            "names_generated": self.names_generated,
            "checks_run":      self.checks_run,
            "elapsed":         self.elapsed,
        }

    def summary_lines(self) -> list[str]:
        """Return a short human-readable summary suitable for CLI display."""
        return [
            f"  Project        : {self.project}",
            f"  Keywords       : {', '.join(self.keywords)}",
            f"  Names          : {len(self.names)} candidates",
            f"  Top name       : {self.top_name}",
            f"  Best domain    : {self.best_domain or '—'}",
            f"  Free domains   : {self.free_domain_count}",
            f"  Free platforms : {self.free_platform_count}",
            f"  Elapsed        : {self.elapsed:.1f}s",
        ]

    def __str__(self) -> str:
        return (
            f"ReportPackage({self.project!r}  "
            f"names={len(self.names)}  "
            f"domains={len(self.domains)}  "
            f"platforms={len(self.platforms)})"
        )


@dataclass
class ExportResult:
    """
    Result of writing one export file.

    Attributes:
        path:    Absolute path of the written file (empty string on failure).
        fmt:     Format string: ``"json"`` | ``"csv"`` | ``"markdown"``.
        ok:      True if the file was written successfully.
        records: Number of records written.
        error:   Error message if ``ok=False``.
        size:    File size in bytes (0 if unknown or failed).
    """
    path:    str
    fmt:     str
    ok:      bool
    records: int  = 0
    error:   str  = ""
    size:    int  = 0

    def __str__(self) -> str:
        if self.ok:
            return f"[{self.fmt.upper()}] {self.path}  ({self.records} records)"
        return f"[{self.fmt.upper()}] FAILED: {self.error}"


@dataclass
class ExportManifest:
    """
    Aggregated results for a multi-format export operation.

    Attributes:
        results:    One :class:`ExportResult` per format written.
        project:    Project name the report was generated for.
        stem:       Common filename stem shared across formats.
        export_dir: Directory where all files were written.
        ok:         True if every result succeeded.
    """
    results:    list[ExportResult]
    project:    str  = ""
    stem:       str  = ""
    export_dir: str  = ""

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def paths(self) -> list[str]:
        """Paths of all successfully written files."""
        return [r.path for r in self.results if r.ok]

    @property
    def primary(self) -> str:
        """Path of the first successful file, or empty string."""
        return self.paths[0] if self.paths else ""

    def summary_lines(self) -> list[str]:
        """Human-readable summary lines for CLI display."""
        lines = []
        for r in self.results:
            tick = "✔" if r.ok else "✘"
            if r.ok:
                size_kb = f"{r.size / 1024:.1f} KB" if r.size else ""
                lines.append(f"  {tick}  [{r.fmt.upper():<8}]  {r.path}  {size_kb}")
            else:
                lines.append(f"  {tick}  [{r.fmt.upper():<8}]  FAILED: {r.error}")
        return lines

    def __str__(self) -> str:
        ok_count = sum(1 for r in self.results if r.ok)
        return (
            f"ExportManifest({self.project!r}  "
            f"{ok_count}/{len(self.results)} formats OK  "
            f"primary={self.primary!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 2  VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_report(data: Any) -> list[str]:
    """
    Validate that *data* is a well-formed NEXAGEN report dict.

    Checks all required keys exist and have the expected types.
    Does NOT validate content of individual NameResult / DomainEntry etc.

    Args:
        data: Value to validate.

    Returns:
        List of error message strings.  Empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(f"Expected dict, got {type(data).__name__}")
        return errors

    required = {
        "project":   str,
        "keywords":  list,
        "names":     list,
        "domains":   list,
        "platforms": list,
    }
    for key, expected_type in required.items():
        if key not in data:
            errors.append(f"Missing required key: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"Key '{key}' expected {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    if not errors:
        if not data["names"]:
            errors.append("'names' list is empty — nothing to export")

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# § 3  REPORT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

class ReportBuilder:
    """
    Assembles :class:`ReportPackage` objects and dispatches multi-format exports.

    Stateless — safe to reuse across calls.

    Usage::

        from nexagen.export.report_builder import ReportBuilder
        builder = ReportBuilder()

        # From cmd_startup_report() return dict
        pkg = builder.from_report_dict(report_dict)

        # Export to JSON + CSV + Markdown
        manifest = builder.export(pkg, cfg, formats=["json", "csv", "markdown"])
        print(manifest.summary_lines())
    """

    # ── Construction ──────────────────────────────────────────────────────────

    def from_report_dict(self, data: dict[str, Any]) -> ReportPackage:
        """
        Build a :class:`ReportPackage` from a ``cmd_startup_report()`` dict.

        Args:
            data: Report dict with keys: project, keywords, names, domains,
                  platforms, names_generated, checks_run, elapsed.

        Returns:
            :class:`ReportPackage`

        Raises:
            ValueError: If the dict fails validation.
        """
        errors = validate_report(data)
        if errors:
            raise ValueError(
                "Report dict failed validation:\n" +
                "\n".join(f"  • {e}" for e in errors)
            )

        return ReportPackage(
            project          = str(data.get("project", "")),
            keywords         = list(data.get("keywords", [])),
            names            = list(data.get("names", [])),
            domains          = list(data.get("domains", [])),
            platforms        = list(data.get("platforms", [])),
            names_generated  = int(data.get("names_generated", 0)),
            checks_run       = int(data.get("checks_run", 0)),
            elapsed          = float(data.get("elapsed", 0.0)),
        )

    def from_parts(
        self,
        project:   str,
        keywords:  Sequence[str],
        names:     Sequence[NameResult],
        domains:   Optional[Sequence[DomainEntry]]   = None,
        platforms: Optional[Sequence[PlatformEntry]] = None,
        *,
        elapsed:   float = 0.0,
    ) -> ReportPackage:
        """
        Build a :class:`ReportPackage` directly from components.

        Args:
            project:   Project name.
            keywords:  Seed keywords.
            names:     Scored name candidates.
            domains:   Domain availability results (empty if not run).
            platforms: Platform check results (empty if not run).
            elapsed:   Wall-clock seconds for generation.

        Returns:
            :class:`ReportPackage`
        """
        return ReportPackage(
            project   = project,
            keywords  = list(keywords),
            names     = list(names),
            domains   = list(domains or []),
            platforms = list(platforms or []),
            elapsed   = elapsed,
        )

    # ── Export dispatch ───────────────────────────────────────────────────────

    def export(
        self,
        pkg:        ReportPackage,
        cfg:        Optional[Settings] = None,
        *,
        formats:    Sequence[str] = ("json", "csv", "markdown"),
        export_dir: Optional[Path] = None,
        label:      str            = "",
    ) -> ExportManifest:
        """
        Write *pkg* to one or more output formats.

        All formats share the same filename stem (``{label}_{timestamp}``)
        and the same output directory, differing only in extension.

        Args:
            pkg:        :class:`ReportPackage` to export.
            cfg:        Active Settings (for export_dir if export_dir is None).
            formats:    Sequence of format strings to write.
                        Valid values: ``"json"`` | ``"csv"`` | ``"markdown"``
                        Use ``["all"]`` as a shortcut for all three.
            export_dir: Override export directory (ignores cfg.export_dir).
            label:      Filename prefix (default: slugified project name).

        Returns:
            :class:`ExportManifest` with one result per format.
        """
        if cfg is None:
            cfg = get_settings()

        # Resolve output directory
        out_dir = Path(export_dir or cfg.export_dir_path)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.error("Cannot create export directory %s: %s", out_dir, exc)
            return ExportManifest(
                results=[ExportResult("", f, False, error=str(exc)) for f in formats],
                project=pkg.project,
            )

        # Normalise formats
        resolved = _resolve_formats(formats)

        # Build shared filename stem
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(label or pkg.project or "nexagen")
        stem = f"{slug}_{ts}"

        results: list[ExportResult] = []

        for fmt in resolved:
            path = out_dir / f"{stem}.{_fmt_ext(fmt)}"
            result = self._write_one(pkg, path, fmt)
            results.append(result)

        return ExportManifest(
            results    = results,
            project    = pkg.project,
            stem       = stem,
            export_dir = str(out_dir),
        )

    def _write_one(
        self,
        pkg:  ReportPackage,
        path: Path,
        fmt:  str,
    ) -> ExportResult:
        """Write *pkg* to *path* in *fmt*. Returns :class:`ExportResult`."""
        report_dict = pkg.to_dict()

        try:
            if fmt == "json":
                from .json_export import export_report_json
                r = export_report_json(report_dict, path)
                return ExportResult(
                    path=r.path, fmt="json", ok=r.ok,
                    records=r.records, error=r.warnings[0] if r.warnings else "",
                    size=r.file_size,
                )

            if fmt == "csv":
                from .csv_export import export_report_csv
                r = export_report_csv(report_dict, path)
                return ExportResult(
                    path=r.path, fmt="csv", ok=r.ok,
                    records=r.rows, error=r.warnings[0] if r.warnings else "",
                    size=r.file_size,
                )

            if fmt == "markdown":
                from .markdown_export import export_report_md
                r = export_report_md(report_dict, path)
                return ExportResult(
                    path=r.path, fmt="markdown", ok=r.ok,
                    records=r.lines, error=r.warnings[0] if r.warnings else "",
                    size=r.file_size,
                )

            return ExportResult("", fmt, False, error=f"Unknown format: {fmt!r}")

        except Exception as exc:
            log.exception("Export to %s failed: %s", fmt, exc)
            return ExportResult("", fmt, False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# § 4  FUNCTIONAL INTERFACES
# ─────────────────────────────────────────────────────────────────────────────

def build_report(
    data:       Any,
    cfg:        Optional[Settings] = None,
    *,
    formats:    Sequence[str] = ("json", "csv", "markdown"),
    export_dir: Optional[Path] = None,
    label:      str            = "",
) -> ExportManifest:
    """
    Build and export a NEXAGEN report in one call.

    Accepts the same *data* shapes as ``cmd_export()``:
      - ``dict`` with report keys → full startup report
      - ``list[NameResult]``      → names-only export
      - ``list[AnalysisData]``    → analysis-only export
      - ``list[DomainEntry]``     → domains-only export
      - ``list[PlatformEntry]``   → platforms-only export

    For list inputs, a lightweight ReportPackage wrapper is built with
    empty components for the missing sections.

    Args:
        data:       Source data to export.
        cfg:        Active Settings.
        formats:    Formats to write (``"all"`` = all three).
        export_dir: Override export directory.
        label:      Filename prefix.

    Returns:
        :class:`ExportManifest`
    """
    if cfg is None:
        cfg = get_settings()

    builder = ReportBuilder()

    # Coerce to ReportPackage
    if isinstance(data, dict) and "project" in data and "names" in data:
        try:
            pkg = builder.from_report_dict(data)
        except ValueError as exc:
            log.error("Invalid report dict: %s", exc)
            # Attempt graceful degradation
            pkg = ReportPackage(
                project  = str(data.get("project", "export")),
                keywords = list(data.get("keywords", [])),
                names    = list(data.get("names", [])),
                domains  = list(data.get("domains", [])),
                platforms= list(data.get("platforms", [])),
            )
    elif isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, NameResult):
            pkg = ReportPackage(project="export", keywords=[], names=list(data),
                                domains=[], platforms=[])
        elif isinstance(first, AnalysisData):
            # Wrap AnalysisData as minimal NameResult-like structure
            names = [
                NameResult(
                    name=ad.name, score=ad.score, tier=ad.tier,
                    pronounce=ad.pronounce, memorability=ad.memorability,
                    uniqueness=ad.uniqueness, length_fit=ad.length_fit,
                    tm_risk=ad.tm_risk, syllables=ad.syllables,
                )
                for ad in data
            ]
            pkg = ReportPackage(project="analysis", keywords=[], names=names,
                                domains=[], platforms=[])
        elif isinstance(first, DomainEntry):
            pkg = ReportPackage(project="domains", keywords=[], names=[],
                                domains=list(data), platforms=[])
        elif isinstance(first, PlatformEntry):
            pkg = ReportPackage(project="platforms", keywords=[], names=[],
                                domains=[], platforms=list(data))
        else:
            log.warning("Unrecognised list element type: %s", type(first))
            return ExportManifest(
                results=[ExportResult("", f, False, error="Unrecognised data type")
                         for f in _resolve_formats(formats)],
            )
    else:
        log.error("build_report: unsupported data type %s", type(data))
        return ExportManifest(
            results=[ExportResult("", f, False, error="Unsupported data type")
                     for f in _resolve_formats(formats)],
        )

    return builder.export(pkg, cfg, formats=formats,
                          export_dir=export_dir, label=label)


def auto_export(
    data: Any,
    cfg:  Optional[Settings] = None,
    *,
    label: str = "",
) -> Optional[ExportManifest]:
    """
    Run export only if ``cfg.auto_export`` is True.

    Used by the CLI after every report generation to optionally write
    output files without user interaction.

    Args:
        data:  Source data (any shape supported by :func:`build_report`).
        cfg:   Active Settings.
        label: Filename prefix.

    Returns:
        :class:`ExportManifest` if auto_export is enabled, else ``None``.
    """
    if cfg is None:
        cfg = get_settings()

    if not cfg.auto_export:
        return None

    fmt = cfg.export_format  # "json" | "csv" | "markdown" | "all"
    log.info("Auto-exporting in format: %s", fmt)

    return build_report(
        data,
        cfg,
        formats=[fmt] if fmt != "all" else ["json", "csv", "markdown"],
        label=label,
    )


def export_formats_from_setting(fmt: str) -> list[str]:
    """
    Resolve a Settings export_format value to a list of format strings.

    Args:
        fmt: ``"json"`` | ``"csv"`` | ``"markdown"`` | ``"all"``

    Returns:
        List of format strings.
    """
    if fmt == "all":
        return ["json", "csv", "markdown"]
    return [fmt] if fmt in ("json", "csv", "markdown") else ["json"]


# ─────────────────────────────────────────────────────────────────────────────
# § 5  INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_formats(formats: Sequence[str]) -> list[str]:
    """
    Expand and validate a formats sequence.

    ``["all"]`` → ``["json", "csv", "markdown"]``.
    Unknown format strings are silently dropped.
    """
    expanded: list[str] = []
    for f in formats:
        if f == "all":
            for x in ("json", "csv", "markdown"):
                if x not in expanded:
                    expanded.append(x)
        elif f in ("json", "csv", "markdown") and f not in expanded:
            expanded.append(f)
    return expanded or ["json"]


def _fmt_ext(fmt: str) -> str:
    """Map format name to file extension."""
    return {"json": "json", "csv": "csv", "markdown": "md"}.get(fmt, fmt)


def _slugify(text: str) -> str:
    """
    Convert *text* to a safe lowercase filename stem.

    Replaces spaces and non-alphanumeric chars with underscores;
    collapses repeated underscores; strips leading/trailing underscores.
    Max 40 characters.
    """
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    slug = slug.strip("_")[:40]
    return slug or "nexagen"
