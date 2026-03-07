"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  export/markdown_export.py  ·  Structured Markdown export engine           ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Turns NEXAGEN result objects into clean, human-readable Markdown documents.

Design decisions
────────────────
  • GitHub-flavoured Markdown (GFM) throughout — pipe tables, fenced code
    blocks, task checkboxes for domain/platform availability.
  • Type-aware sections: NameResult → ranked names table + sub-score bars,
    AnalysisData → brand analysis table with emoji tier indicators,
    DomainEntry → availability table with ✔/✘ icons,
    PlatformEntry → handle availability table,
    startup report dict → full multi-section branded document.
  • Score bars: ASCII progress bars (e.g. ████████░░ 82/100) are rendered
    inside table cells for visual sub-score comparison.
  • Metadata frontmatter: YAML-style comment block at top of each file
    with tool name, version, export timestamp, and record count.
  • Self-contained: every export is a complete Markdown document readable
    in any Markdown renderer (GitHub, Obsidian, Typora, VS Code, etc.).

Public API
──────────
  write_markdown(data, path, *, metadata)      → MarkdownResult
  export_names_md(names, path, **kw)            → MarkdownResult
  export_analysis_md(analysis, path, **kw)      → MarkdownResult
  export_domains_md(domains, path, **kw)        → MarkdownResult
  export_platforms_md(platforms, path, **kw)    → MarkdownResult
  export_report_md(report_dict, path, **kw)     → MarkdownResult
  detect_data_type(data)                        → str
  score_bar(score, width)                       → str

Data structures
───────────────
  MarkdownResult — path, lines written, sections, data_type, warnings, ok
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from ..config.constants import (
    DISCLAIMER,
    EXPORT_DIR,
    SLOGAN,
    TOOL_AUTHOR,
    TOOL_CONTACT,
    TOOL_NAME,
    TOOL_REPO,
    TOOL_TAGLINE,
    VERSION,
    VERSION_TAG,
)
from ..ui.tables import AnalysisData, DomainEntry, NameResult, PlatformEntry

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  TYPE CONSTANTS  (mirrors csv_export / json_export)
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
class MarkdownResult:
    """
    Return value of every markdown_export write function.

    Attributes:
        path:       Absolute path to the written file.
        lines:      Total lines written (including blanks).
        sections:   Number of H2 sections in the document.
        data_type:  Detected input data type (DTYPE_* constant).
        warnings:   Any non-fatal issues encountered during export.
        ok:         True if the file was written successfully.
        file_size:  File size in bytes after writing.
    """
    path:      str
    lines:     int
    sections:  int  = 1
    data_type: str  = DTYPE_UNKNOWN
    warnings:  list[str] = field(default_factory=list)
    ok:        bool = True
    file_size: int  = 0

    def __str__(self) -> str:
        return (
            f"MarkdownResult(path={self.path!r}, lines={self.lines}, "
            f"type={self.data_type}, ok={self.ok})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_data_type(data: Any) -> str:
    """
    Determine the NEXAGEN data type of *data*.

    Args:
        data: Value to classify.

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
# § 4  RENDERING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def score_bar(score: int, width: int = 10) -> str:
    """
    Render a score (0–100) as an ASCII progress bar.

    Example: ``████████░░ 82``

    Args:
        score: Integer score 0–100.
        width: Total bar character width (default 10).

    Returns:
        String with filled + empty blocks and numeric score suffix.
    """
    score  = max(0, min(100, score))
    filled = round(score / 100 * width)
    empty  = width - filled
    return f"{'█' * filled}{'░' * empty} {score}"


def _tier_emoji(tier: str) -> str:
    """Return a single emoji indicator for a BrandTier value."""
    return {
        "PREMIUM": "💎",
        "STRONG":  "🟢",
        "DECENT":  "🔵",
        "WEAK":    "🟡",
        "POOR":    "🔴",
    }.get(tier.upper(), "⚪")


def _tier_indicator(tier: str) -> str:
    """Return a Unicode indicator character for a BrandTier value."""
    return {
        "PREMIUM": "◆",
        "STRONG":  "▲",
        "DECENT":  "●",
        "WEAK":    "▼",
        "POOR":    "✕",
    }.get(tier.upper(), "·")


def _avail_icon(status: str) -> str:
    """Map domain/platform status to a Markdown-safe icon."""
    return {"free": "✅", "taken": "❌", "unknown": "❓", "skip": "—"}.get(
        status.lower(), "❓"
    )


def _tm_label(risk: str) -> str:
    """Trademark risk → emoji label."""
    return {
        "none":   "🟢 None",
        "low":    "🟡 Low",
        "medium": "🟠 Medium",
        "high":   "🔴 High",
    }.get(risk.lower(), "⚪ Unknown")


def _md_escape(text: str) -> str:
    """Escape pipe characters to avoid breaking GFM table cells."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _auto_path(label: str = "") -> Path:
    """Generate a timestamped output path under EXPORT_DIR."""
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{label}_{ts}" if label else f"nexagen_{ts}"
    out_dir = EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}.md"


def _metadata_comment(data_type: str, records: int) -> str:
    """Build a YAML-style front-matter comment block."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"<!--\n"
        f"  NEXAGEN Export\n"
        f"  tool:        {TOOL_NAME} {VERSION_TAG}\n"
        f"  author:      {TOOL_AUTHOR}\n"
        f"  exported_at: {now}\n"
        f"  data_type:   {data_type}\n"
        f"  records:     {records}\n"
        f"-->\n"
    )


def _write_lines(path: Path, lines: list[str], dtype: str,
                 sections: int, warnings: list[str]) -> MarkdownResult:
    """Join lines, write to path, return MarkdownResult."""
    try:
        text = "\n".join(lines)
        path.write_text(text, encoding="utf-8")
        size = path.stat().st_size
        log.debug("Markdown export: %s  (%d bytes)", path, size)
        return MarkdownResult(
            path=str(path), lines=len(lines), sections=sections,
            data_type=dtype, warnings=warnings, ok=True, file_size=size,
        )
    except OSError as exc:
        log.error("Markdown write failed: %s", exc)
        return MarkdownResult(
            path=str(path), lines=0, sections=sections,
            data_type=dtype, warnings=[str(exc)], ok=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  GFM TABLE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _names_table(names: Sequence[NameResult]) -> list[str]:
    """
    Build a GFM pipe table for a list of NameResult objects.

    Columns: Rank | Name | Score | Tier | Pronounce | Memory | Unique |
             Length | TM Risk | Syllables | Best Domain
    """
    lines = [
        "| # | Name | Score | Tier | Pronounce | Memory | Unique | Length | TM Risk | Syl | Best Domain |",
        "|---|------|-------|------|-----------|--------|--------|--------|---------|-----|-------------|",
    ]
    for i, nr in enumerate(names, 1):
        best = next((d for d, s in nr.domains.items() if s == "free"), "")
        if not best and nr.domains:
            best = next(iter(nr.domains))
        lines.append(
            f"| {i} "
            f"| **{_md_escape(nr.name)}** "
            f"| `{nr.score}` "
            f"| {_tier_emoji(nr.tier)} {nr.tier} "
            f"| {score_bar(nr.pronounce, 6)} "
            f"| {score_bar(nr.memorability, 6)} "
            f"| {score_bar(nr.uniqueness, 6)} "
            f"| {score_bar(nr.length_fit, 6)} "
            f"| {_tm_label(nr.tm_risk)} "
            f"| {nr.syllables} "
            f"| {_md_escape(best) or '—'} |"
        )
    return lines


def _analysis_table(analysis: Sequence[AnalysisData]) -> list[str]:
    """Build a GFM pipe table for a list of AnalysisData objects."""
    lines = [
        "| # | Name | Score | Tier | Pronounce | Memory | Unique | Length | Syllables | Vowel% | TM Risk | Common |",
        "|---|------|-------|------|-----------|--------|--------|--------|-----------|--------|---------|--------|",
    ]
    for i, ad in enumerate(analysis, 1):
        lines.append(
            f"| {i} "
            f"| **{_md_escape(ad.name)}** "
            f"| `{ad.score}` "
            f"| {_tier_emoji(ad.tier)} {ad.tier} "
            f"| {score_bar(ad.pronounce, 6)} "
            f"| {score_bar(ad.memorability, 6)} "
            f"| {score_bar(ad.uniqueness, 6)} "
            f"| {score_bar(ad.length_fit, 6)} "
            f"| {ad.syllables} "
            f"| {ad.vowel_ratio*100:.0f}% "
            f"| {_tm_label(ad.tm_risk)} "
            f"| {'Yes' if ad.is_common else 'No'} |"
        )
    return lines


def _domains_table(domains: Sequence[DomainEntry]) -> list[str]:
    """Build a GFM pipe table for a list of DomainEntry objects."""
    lines = [
        "| Domain | Status | TLD | TLD Score |",
        "|--------|--------|-----|-----------|",
    ]
    for de in domains:
        lines.append(
            f"| `{_md_escape(de.domain)}` "
            f"| {_avail_icon(de.status)} {de.status.capitalize()} "
            f"| .{de.tld} "
            f"| {de.tld_rank} |"
        )
    return lines


def _platforms_table(platforms: Sequence[PlatformEntry]) -> list[str]:
    """Build a GFM pipe table for a list of PlatformEntry objects."""
    lines = [
        "| Platform | Handle | Status |",
        "|----------|--------|--------|",
    ]
    for pe in platforms:
        lines.append(
            f"| {_md_escape(pe.platform).capitalize()} "
            f"| `{_md_escape(pe.handle)}` "
            f"| {_avail_icon(pe.status)} {pe.status.capitalize()} |"
        )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# § 6  TYPE-SPECIFIC EXPORT FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def export_names_md(
    names:    Sequence[NameResult],
    path:     Optional[Path] = None,
    *,
    metadata: bool = True,
    title:    str  = "Generated Brand Names",
    label:    str  = "names",
) -> MarkdownResult:
    """
    Export a list of NameResult objects to a Markdown file.

    Args:
        names:    Name generation results.
        path:     Output path. Auto-generated if None.
        metadata: Include YAML comment header.
        title:    H1 title for the document.
        label:    Filename prefix for auto-generated paths.

    Returns:
        :class:`MarkdownResult`
    """
    if path is None:
        path = _auto_path(label)

    lines: list[str] = []

    if metadata:
        lines.append(_metadata_comment(DTYPE_NAMES, len(names)))

    lines += [
        f"# {title}",
        "",
        f"> Generated by **{TOOL_NAME} {VERSION_TAG}** · {TOOL_TAGLINE}  ",
        f"> {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  {len(names)} candidates",
        "",
        "## Names",
        "",
    ]

    if names:
        lines += _names_table(names)
    else:
        lines.append("_No names generated._")

    # Per-name detail blocks
    lines += ["", "## Detailed Scores", ""]
    for i, nr in enumerate(names, 1):
        emoji = _tier_emoji(nr.tier)
        lines += [
            f"### {i}. {nr.name}  {emoji} {nr.tier}",
            "",
            f"**Composite Score:** `{nr.score}/100`  |  "
            f"**TM Risk:** {_tm_label(nr.tm_risk)}  |  "
            f"**Syllables:** {nr.syllables}",
            "",
            "| Dimension | Score |",
            "|-----------|-------|",
            f"| Pronounceability | {score_bar(nr.pronounce)} |",
            f"| Memorability     | {score_bar(nr.memorability)} |",
            f"| Uniqueness       | {score_bar(nr.uniqueness)} |",
            f"| Length Fitness   | {score_bar(nr.length_fit)} |",
            "",
        ]
        if nr.domains:
            free = [(d, s) for d, s in nr.domains.items() if s == "free"]
            taken = [(d, s) for d, s in nr.domains.items() if s == "taken"]
            if free:
                lines.append(f"**Available domains:** {', '.join(f'`{d}`' for d, _ in free)}")
            if taken:
                lines.append(f"**Taken domains:** {', '.join(f'`{d}`' for d, _ in taken)}")
            lines.append("")

    lines += [
        "---",
        "",
        f"*{DISCLAIMER}*",
        "",
        f"*{TOOL_NAME} {VERSION_TAG} · {TOOL_AUTHOR} · {TOOL_REPO}*",
    ]

    return _write_lines(Path(path), lines, DTYPE_NAMES, 2, [])


def export_analysis_md(
    analysis: Sequence[AnalysisData],
    path:     Optional[Path] = None,
    *,
    metadata: bool = True,
    title:    str  = "Brand Analysis Report",
    label:    str  = "analysis",
) -> MarkdownResult:
    """
    Export a list of AnalysisData objects to a Markdown file.

    Args:
        analysis: Brand analysis results.
        path:     Output path. Auto-generated if None.
        metadata: Include YAML comment header.
        title:    H1 document title.
        label:    Filename prefix.

    Returns:
        :class:`MarkdownResult`
    """
    if path is None:
        path = _auto_path(label)

    lines: list[str] = []

    if metadata:
        lines.append(_metadata_comment(DTYPE_ANALYSIS, len(analysis)))

    lines += [
        f"# {title}",
        "",
        f"> **{TOOL_NAME} {VERSION_TAG}**  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}  "
        f"·  {len(analysis)} entries",
        "",
        "## Analysis Table",
        "",
    ]

    if analysis:
        lines += _analysis_table(analysis)
    else:
        lines.append("_No analysis data._")

    # Notes section per name
    with_notes = [ad for ad in analysis if ad.notes]
    if with_notes:
        lines += ["", "## Diagnostic Notes", ""]
        for ad in with_notes:
            lines += [
                f"### {ad.name}  (`{ad.score}/100`)",
                "",
            ]
            for note in ad.notes:
                lines.append(f"- {_md_escape(note)}")
            lines.append("")

    lines += [
        "---",
        "",
        f"*{TOOL_NAME} {VERSION_TAG} · {TOOL_AUTHOR} · {TOOL_REPO}*",
    ]

    return _write_lines(Path(path), lines, DTYPE_ANALYSIS, 2, [])


def export_domains_md(
    domains: Sequence[DomainEntry],
    path:    Optional[Path] = None,
    *,
    metadata: bool = True,
    title:    str  = "Domain Availability Report",
    label:    str  = "domains",
) -> MarkdownResult:
    """
    Export a list of DomainEntry objects to a Markdown file.

    Args:
        domains:  Domain availability check results.
        path:     Output path. Auto-generated if None.
        metadata: Include YAML comment header.
        title:    H1 document title.
        label:    Filename prefix.

    Returns:
        :class:`MarkdownResult`
    """
    if path is None:
        path = _auto_path(label)

    free    = [d for d in domains if d.status == "free"]
    taken   = [d for d in domains if d.status == "taken"]
    unknown = [d for d in domains if d.status not in ("free", "taken")]

    lines: list[str] = []

    if metadata:
        lines.append(_metadata_comment(DTYPE_DOMAINS, len(domains)))

    lines += [
        f"# {title}",
        "",
        f"> **{TOOL_NAME} {VERSION_TAG}**  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**Summary:** {len(free)} available  ·  {len(taken)} taken  ·  {len(unknown)} unknown  "
        f"·  {len(domains)} total",
        "",
    ]

    if free:
        lines += ["## ✅ Available Domains", ""]
        lines += _domains_table(free)
        lines.append("")

    if taken:
        lines += ["## ❌ Taken Domains", ""]
        lines += _domains_table(taken)
        lines.append("")

    if unknown:
        lines += ["## ❓ Unknown / Check Manually", ""]
        lines += _domains_table(unknown)
        lines.append("")

    lines += [
        "---",
        "",
        f"*{TOOL_NAME} {VERSION_TAG} · {TOOL_AUTHOR}*",
    ]

    return _write_lines(Path(path), lines, DTYPE_DOMAINS, 3, [])


def export_platforms_md(
    platforms: Sequence[PlatformEntry],
    path:      Optional[Path] = None,
    *,
    metadata:  bool = True,
    title:     str  = "Platform Handle Availability",
    label:     str  = "platforms",
) -> MarkdownResult:
    """
    Export a list of PlatformEntry objects to a Markdown file.

    Args:
        platforms: Platform handle check results.
        path:      Output path. Auto-generated if None.
        metadata:  Include YAML comment header.
        title:     H1 document title.
        label:     Filename prefix.

    Returns:
        :class:`MarkdownResult`
    """
    if path is None:
        path = _auto_path(label)

    free  = [p for p in platforms if p.status == "free"]
    taken = [p for p in platforms if p.status == "taken"]

    lines: list[str] = []

    if metadata:
        lines.append(_metadata_comment(DTYPE_PLATFORMS, len(platforms)))

    lines += [
        f"# {title}",
        "",
        f"> **{TOOL_NAME} {VERSION_TAG}**  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**Summary:** {len(free)} available  ·  {len(taken)} taken  ·  {len(platforms)} checked",
        "",
        "## All Results",
        "",
    ]

    if platforms:
        lines += _platforms_table(platforms)
    else:
        lines.append("_No platform checks performed._")

    lines += [
        "",
        "---",
        "",
        f"*{TOOL_NAME} {VERSION_TAG} · {TOOL_AUTHOR}*",
    ]

    return _write_lines(Path(path), lines, DTYPE_PLATFORMS, 1, [])


def export_report_md(
    report:   dict[str, Any],
    path:     Optional[Path] = None,
    *,
    metadata: bool = True,
    label:    str  = "startup_report",
) -> MarkdownResult:
    """
    Export a startup naming report dict to a full branded Markdown document.

    The dict must contain the keys returned by ``cmd_startup_report()``:
    ``project``, ``keywords``, ``names``, ``domains``, ``platforms``,
    ``names_generated``, ``checks_run``, ``elapsed``.

    Output structure (H2 sections):
      1. Project Overview
      2. Top Candidates  (names table)
      3. Detailed Scores (per-name breakdown)
      4. Domain Availability
      5. Platform Handles
      6. Next Steps
      7. Footer

    Args:
        report:   Startup report dict from ``cmd_startup_report()``.
        path:     Output path. Auto-generated if None.
        metadata: Include YAML comment header.
        label:    Filename prefix.

    Returns:
        :class:`MarkdownResult` with ``sections=7``.
    """
    if path is None:
        path = _auto_path(label)

    project   = report.get("project", "Unnamed Project")
    keywords  = report.get("keywords", [])
    names     = report.get("names", [])
    domains   = report.get("domains", [])
    platforms = report.get("platforms", [])
    elapsed   = report.get("elapsed", 0.0)
    n_gen     = report.get("names_generated", len(names))
    n_checks  = report.get("checks_run", 0)

    now      = datetime.now().strftime("%Y-%m-%d %H:%M")
    now_full = datetime.now().strftime("%B %d, %Y at %H:%M")

    free_domains = [d for d in domains if d.status == "free"]
    best_domain  = free_domains[0].domain if free_domains else ""

    lines: list[str] = []

    if metadata:
        lines.append(_metadata_comment(DTYPE_REPORT, n_gen))

    # ── Cover ────────────────────────────────────────────────────────────────
    lines += [
        f"# {TOOL_NAME} — Startup Naming Report",
        f"## {project}",
        "",
        f"> **{TOOL_TAGLINE}**  ",
        f"> Generated {now_full}  ·  Powered by {TOOL_NAME} {VERSION_TAG}",
        "",
        "---",
        "",
    ]

    # ── § 1 Project Overview ──────────────────────────────────────────────────
    kw_badges = "  ".join(f"`{k}`" for k in keywords)
    lines += [
        "## 1. Project Overview",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Project** | {_md_escape(project)} |",
        f"| **Keywords** | {kw_badges} |",
        f"| **Names Generated** | {n_gen} |",
        f"| **Checks Run** | {n_checks} |",
        f"| **Elapsed** | {elapsed:.1f}s |",
        f"| **Best Domain** | {('`' + best_domain + '`') if best_domain else '—'} |",
        "",
    ]

    # ── § 2 Top Candidates ────────────────────────────────────────────────────
    lines += ["## 2. Top Candidates", ""]

    top5 = list(names[:5])
    if top5:
        lines += _names_table(top5)
    else:
        lines.append("_No names generated._")
    lines.append("")

    # ── § 3 Detailed Scores ───────────────────────────────────────────────────
    lines += ["## 3. Detailed Score Breakdown", ""]

    for i, nr in enumerate(names[:10], 1):
        emoji = _tier_emoji(nr.tier)
        best  = next((d for d, s in nr.domains.items() if s == "free"), "")
        lines += [
            f"### {i}. {nr.name}  {emoji}",
            "",
            f"| | |",
            f"|---|---|",
            f"| **Score** | `{nr.score}/100` |",
            f"| **Tier** | {nr.tier} |",
            f"| **TM Risk** | {_tm_label(nr.tm_risk)} |",
            f"| **Syllables** | {nr.syllables} |",
            f"| **Best Domain** | {('`' + best + '`') if best else '—'} |",
            "",
            "**Sub-scores:**",
            "",
            "| Dimension | Score |",
            "|-----------|-------|",
            f"| Pronounceability | `{score_bar(nr.pronounce)}` |",
            f"| Memorability     | `{score_bar(nr.memorability)}` |",
            f"| Uniqueness       | `{score_bar(nr.uniqueness)}` |",
            f"| Length Fitness   | `{score_bar(nr.length_fit)}` |",
            "",
        ]
        if nr.keywords:
            lines.append(f"**Keywords:** {', '.join(_md_escape(k) for k in nr.keywords)}")
            lines.append("")

    # ── § 4 Domain Availability ───────────────────────────────────────────────
    lines += ["## 4. Domain Availability", ""]

    if domains:
        free_d   = [d for d in domains if d.status == "free"]
        taken_d  = [d for d in domains if d.status == "taken"]
        unknown_d = [d for d in domains if d.status not in ("free", "taken")]

        lines.append(
            f"**{len(free_d)} available** · {len(taken_d)} taken · "
            f"{len(unknown_d)} unknown · {len(domains)} total checked"
        )
        lines.append("")

        if free_d:
            lines += ["**✅ Available:**", ""]
            lines += _domains_table(free_d)
            lines.append("")

        if taken_d:
            lines += ["**❌ Taken:**", ""]
            lines += _domains_table(taken_d[:8])
            if len(taken_d) > 8:
                lines.append(f"_… and {len(taken_d) - 8} more taken domains._")
            lines.append("")
    else:
        lines.append("_Domain checks were not run for this report._")
        lines.append("")

    # ── § 5 Platform Handles ──────────────────────────────────────────────────
    lines += ["## 5. Platform Handle Availability", ""]

    if platforms:
        free_p  = [p for p in platforms if p.status == "free"]
        taken_p = [p for p in platforms if p.status == "taken"]
        lines.append(
            f"**{len(free_p)} available** · {len(taken_p)} taken · {len(platforms)} checked"
        )
        lines.append("")
        lines += _platforms_table(platforms)
        lines.append("")
    else:
        lines.append("_Platform handle checks were not run for this report._")
        lines.append("")

    # ── § 6 Next Steps ────────────────────────────────────────────────────────
    best_name  = names[0].name if names else ""
    lines += [
        "## 6. Recommended Next Steps",
        "",
    ]
    if best_name:
        lines += [
            f"1. **Register `{best_domain}`** immediately if available.",
            f"2. Verify trademark clearance for **{best_name}** in your jurisdiction.",
            f"3. Reserve platform handles (GitHub, PyPI, npm, Docker Hub) for your shortlist.",
            f"4. Run a professional trademark search before launch.",
        ]
    else:
        lines += [
            "1. Re-run with different keywords to generate more candidates.",
            "2. Review the domain and platform check results above.",
        ]
    lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        f"> *{DISCLAIMER}*",
        "",
        f"**{TOOL_NAME} {VERSION_TAG}** · {TOOL_AUTHOR}  ",
        f"{SLOGAN}  ",
        f"[{TOOL_REPO}]({TOOL_REPO}) · {TOOL_CONTACT}",
        "",
    ]

    return _write_lines(Path(path), lines, DTYPE_REPORT, 7, [])


# ─────────────────────────────────────────────────────────────────────────────
# § 7  MAIN DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def write_markdown(
    data:     Any,
    path:     Optional[Path] = None,
    *,
    metadata: bool = True,
    label:    str  = "",
) -> MarkdownResult:
    """
    Auto-detect the data type and write to Markdown.

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
        metadata: Include YAML comment front-matter header.
        label:    Optional filename prefix for auto-generated paths.

    Returns:
        :class:`MarkdownResult`
    """
    dtype = detect_data_type(data)

    dispatch = {
        DTYPE_NAMES:     lambda: export_names_md(data, path, metadata=metadata, label=label or "names"),
        DTYPE_ANALYSIS:  lambda: export_analysis_md(data, path, metadata=metadata, label=label or "analysis"),
        DTYPE_DOMAINS:   lambda: export_domains_md(data, path, metadata=metadata, label=label or "domains"),
        DTYPE_PLATFORMS: lambda: export_platforms_md(data, path, metadata=metadata, label=label or "platforms"),
        DTYPE_REPORT:    lambda: export_report_md(data, path, metadata=metadata, label=label or "report"),
    }

    if dtype in dispatch:
        return dispatch[dtype]()

    # Generic fallback — list of dicts or unknown
    if path is None:
        path = _auto_path(label or "export")

    lines: list[str] = []
    if metadata:
        lines.append(_metadata_comment(DTYPE_DICTS, len(data) if isinstance(data, list) else 1))

    lines += [
        "# NEXAGEN Export",
        "",
        f"> {TOOL_NAME} {VERSION_TAG} · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if isinstance(data, list):
        for i, item in enumerate(data, 1):
            lines.append(f"## Item {i}")
            lines.append("")
            if isinstance(item, dict):
                for k, v in item.items():
                    lines.append(f"- **{_md_escape(k)}:** {_md_escape(str(v))}")
            else:
                lines.append(str(item))
            lines.append("")
    else:
        lines.append(str(data))

    return _write_lines(
        Path(path), lines, dtype,
        1, [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 8  UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def markdown_preview(path: Union[str, Path], max_lines: int = 30) -> str:
    """
    Return the first *max_lines* lines of a Markdown export file.

    Args:
        path:      Path to the .md file.
        max_lines: Maximum lines to return.

    Returns:
        Truncated file content string.
    """
    try:
        all_lines = Path(path).read_text(encoding="utf-8").splitlines()
        if len(all_lines) > max_lines:
            return "\n".join(all_lines[:max_lines]) + f"\n… [{len(all_lines) - max_lines} more lines]"
        return "\n".join(all_lines)
    except OSError as exc:
        return f"[Could not read {path}: {exc}]"
