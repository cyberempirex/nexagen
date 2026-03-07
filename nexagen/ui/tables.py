"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  ui/tables.py  ·  Results tables, score cards, domain & analysis display   ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Public API
──────────
  print_names_table(results)             — main generation results table
  print_score_card(name, score_data)     — single-name detailed score card
  print_domain_table(domain_results)     — domain availability grid
  print_platform_table(platform_results) — GitHub / PyPI / npm / Docker grid
  print_analysis_table(analysis_data)    — brand strength breakdown
  print_comparison_table(names)          — side-by-side name comparison
  print_startup_report_summary(data)     — full startup report summary
  print_export_summary(path, format)     — export confirmation strip
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from rich import box
from rich.align import Align
from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ..config.constants import (
    C_ACCENT,
    C_AMBER,
    C_BANNER,
    C_BLUE,
    C_DARK,
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PINK,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
    SCORE_DECENT,
    SCORE_PREMIUM,
    SCORE_STRONG,
    SCORE_WEAK,
    BrandTier,
    AvailStatus,
    TIER_COLORS,
)

_con = Console(highlight=False, markup=True)


# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATA MODELS (lightweight, no heavy ORM)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NameResult:
    """One brand name candidate with all scores and availability."""
    name:          str
    score:         int                         # composite 0–100
    tier:          str = ""                    # PREMIUM / STRONG / DECENT / WEAK / POOR
    pronounce:     int = 0                     # 0–100
    memorability:  int = 0                     # 0–100
    uniqueness:    int = 0                     # 0–100
    length_fit:    int = 0                     # 0–100
    tm_risk:       str = "none"               # none / low / medium / high
    syllables:     int = 0
    domains:       dict[str, str] = field(default_factory=dict)   # tld → status
    platforms:     dict[str, str] = field(default_factory=dict)   # platform → status
    profile:       str = ""
    style:         str = ""
    keywords:      list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tier:
            self.tier = BrandTier.from_score(self.score).value


@dataclass
class DomainEntry:
    """One domain availability result."""
    domain:   str
    status:   str   # free | taken | unknown
    tld:      str
    tld_rank: int = 0


@dataclass
class PlatformEntry:
    """One platform handle availability result."""
    handle:   str
    platform: str   # github | pypi | npm | docker | huggingface
    status:   str   # free | taken | unknown


@dataclass
class AnalysisData:
    """Full brand analysis data for one name."""
    name:         str
    score:        int
    tier:         str
    pronounce:    int
    memorability: int
    uniqueness:   int
    length_fit:   int
    syllables:    int
    vowel_ratio:  float
    tm_risk:      str
    is_common:    bool
    phonetic_key: str = ""
    notes:        list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _tier_colour(tier: str) -> str:
    return TIER_COLORS.get(tier.upper(), C_WHITE)


def _score_colour(score: int) -> str:
    if score >= SCORE_PREMIUM:
        return C_GOLD
    if score >= SCORE_STRONG:
        return C_GREEN
    if score >= SCORE_DECENT:
        return C_ACCENT
    if score >= SCORE_WEAK:
        return C_AMBER
    return C_RED


def _score_bar(score: int, width: int = 12) -> str:
    """Return a Unicode block progress bar for a 0–100 score."""
    BLOCKS = " ▏▎▍▌▋▊▉█"
    filled = (score / 100) * width
    full   = int(filled)
    frac   = filled - full
    idx    = int(frac * (len(BLOCKS) - 1))

    bar = "█" * full
    if full < width:
        bar += BLOCKS[idx]
    bar = bar.ljust(width)
    return bar


def _avail_icon(status: str) -> str:
    m = {"free": "✔", "taken": "✘", "unknown": "?", "skip": "—"}
    return m.get(status.lower(), "?")


def _avail_colour(status: str) -> str:
    m = {"free": C_GREEN, "taken": C_RED, "unknown": C_GRAY, "skip": C_GRAY}
    return m.get(status.lower(), C_GRAY)


def _tm_risk_colour(risk: str) -> str:
    return {"none": C_GREEN, "low": C_TEAL, "medium": C_AMBER, "high": C_RED}.get(
        risk.lower(), C_GRAY
    )


def _tier_indicator(tier: str) -> str:
    return {
        "PREMIUM": "◆",
        "STRONG":  "▲",
        "DECENT":  "●",
        "WEAK":    "▼",
        "POOR":    "✕",
    }.get(tier.upper(), "·")


# ─────────────────────────────────────────────────────────────────────────────
# § 3  MAIN NAMES TABLE
# ─────────────────────────────────────────────────────────────────────────────

def print_names_table(
    results:     Sequence[NameResult],
    title:       str  = "Generated Brand Names",
    max_rows:    int  = 30,
    show_domains:bool = True,
) -> None:
    """
    Render the primary name generation results table.

    Columns: Rank · Name · Score · Tier · Pronounce · Memory · Unique ·
             TM Risk · Syllables · [top domain if show_domains]
    """
    from .banner import section
    section(title, C_ACCENT)
    _con.print()

    if not results:
        _con.print(f"   [{C_AMBER}]⚠  No names generated.[/{C_AMBER}]")
        return

    t = Table(
        box=box.ROUNDED,
        border_style=f"dim {C_ACCENT}",
        header_style=f"bold {C_ACCENT}",
        show_header=True,
        expand=False,
        padding=(0, 1),
    )

    # ── Columns ───────────────────────────────────────────────────────────────
    t.add_column("#",         style=f"dim {C_GRAY}",   width=4,  justify="right")
    t.add_column("Name",      style=f"bold {C_WHITE}",  width=18)
    t.add_column("Score",     style="",                 width=10, justify="center")
    t.add_column("Tier",      style="",                 width=10, justify="center")
    t.add_column("Pronounce", style="",                 width=10, justify="center")
    t.add_column("Memory",    style="",                 width=10, justify="center")
    t.add_column("Unique",    style="",                 width=10, justify="center")
    t.add_column("TM Risk",   style="",                 width=10, justify="center")
    if show_domains:
        t.add_column("Domain", style="",                width=14)

    # ── Rows ──────────────────────────────────────────────────────────────────
    display_count = min(len(results), max_rows)
    for rank, res in enumerate(results[:display_count], 1):
        sc  = _score_colour(res.score)
        tc  = _tier_colour(res.tier)
        ind = _tier_indicator(res.tier)

        score_cell = (
            f"[bold {sc}]{_score_bar(res.score, 8)}[/bold {sc}]"
            f"[dim {C_GRAY}]{res.score:3}[/dim {C_GRAY}]"
        )
        tier_cell = f"[bold {tc}]{ind} {res.tier:<8}[/bold {tc}]"
        pron_cell = f"[{_score_colour(res.pronounce)}]{res.pronounce:3}[/{_score_colour(res.pronounce)}]"
        memo_cell = f"[{_score_colour(res.memorability)}]{res.memorability:3}[/{_score_colour(res.memorability)}]"
        uniq_cell = f"[{_score_colour(res.uniqueness)}]{res.uniqueness:3}[/{_score_colour(res.uniqueness)}]"
        tm_col    = _tm_risk_colour(res.tm_risk)
        tm_cell   = f"[{tm_col}]{res.tm_risk.upper():<8}[/{tm_col}]"

        row_cells: list[Any] = [
            str(rank),
            escape(res.name.capitalize()),
            score_cell,
            tier_cell,
            pron_cell,
            memo_cell,
            uniq_cell,
            tm_cell,
        ]

        if show_domains and res.domains:
            best_dom = next(
                ((d, s) for d, s in res.domains.items() if s == "free"),
                next(iter(res.domains.items()), ("—", "unknown")),
            )
            dom_col  = _avail_colour(best_dom[1])
            dom_icon = _avail_icon(best_dom[1])
            row_cells.append(
                f"[{dom_col}]{dom_icon}[/{dom_col}]"
                f" [{C_WHITE}]{escape(best_dom[0])}[/{C_WHITE}]"
            )

        t.add_row(*row_cells)

    _con.print(Padding(t, (0, 2)))

    if len(results) > max_rows:
        _con.print(
            f"   [dim {C_GRAY}]…and {len(results) - max_rows} more names. "
            f"Use export to see the full list.[/dim {C_GRAY}]"
        )

    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 4  DETAILED SCORE CARD
# ─────────────────────────────────────────────────────────────────────────────

def print_score_card(name: str, data: AnalysisData) -> None:
    """
    Render a full-detail score card for one brand name.

    Displayed as a Rich panel with score bars for each dimension.
    """
    from .banner import section
    section(f"Score Card  —  {name.upper()}", C_BANNER)
    _con.print()

    tc = _tier_colour(data.tier)
    sc = _score_colour(data.score)

    # ── Header: name + composite score ───────────────────────────────────────
    header = (
        f"  [bold {tc}]{_tier_indicator(data.tier)}  "
        f"{escape(name.capitalize())}[/bold {tc}]\n"
        f"  [bold {sc}]Composite Score: {data.score}/100[/bold {sc}]  "
        f"[bold {tc}]{data.tier}[/bold {tc}]"
    )
    _con.print(Padding(header, (0, 2)))
    _con.print()

    # ── Score dimension bars ──────────────────────────────────────────────────
    dims = [
        ("Pronounceability",  data.pronounce,    C_TEAL),
        ("Memorability",      data.memorability, C_PURPLE),
        ("Uniqueness",        data.uniqueness,   C_ACCENT),
        ("Length Fitness",    data.length_fit,   C_GOLD),
    ]
    for label, score, colour in dims:
        bar = _score_bar(score, 20)
        _con.print(
            f"   [{C_GRAY}]{label:<18}[/{C_GRAY}]  "
            f"[bold {colour}]{bar}[/bold {colour}]  "
            f"[bold {_score_colour(score)}]{score:3}/100[/bold {_score_colour(score)}]"
        )

    _con.print()

    # ── Metrics strip ─────────────────────────────────────────────────────────
    metrics_t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
        expand=False,
        border_style=f"dim {C_GRAY}",
    )
    metrics_t.add_column(style=f"dim {C_GRAY}",   width=20)
    metrics_t.add_column(style=f"bold {C_WHITE}",  width=22)

    tm_col = _tm_risk_colour(data.tm_risk)
    metrics_t.add_row("Syllables",    str(data.syllables))
    metrics_t.add_row("Vowel ratio",  f"{data.vowel_ratio:.0%}")
    metrics_t.add_row("TM risk",      f"[{tm_col}]{data.tm_risk.upper()}[/{tm_col}]")
    metrics_t.add_row("Common word",  "yes" if data.is_common else "no")
    if data.phonetic_key:
        metrics_t.add_row("Phonetic key", data.phonetic_key)

    _con.print(Padding(metrics_t, (0, 2)))

    # ── Notes ─────────────────────────────────────────────────────────────────
    if data.notes:
        _con.print()
        _con.print(f"   [{C_GRAY}]Notes:[/{C_GRAY}]")
        for note in data.notes:
            _con.print(f"   [{C_AMBER}]·[/{C_AMBER}]  [{C_GRAY}]{escape(note)}[/{C_GRAY}]")

    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 5  DOMAIN AVAILABILITY TABLE
# ─────────────────────────────────────────────────────────────────────────────

def print_domain_table(
    entries: Sequence[DomainEntry],
    name:    str = "",
    cols:    int = 3,
) -> None:
    """
    Render domain availability in a compact multi-column grid.

    Free domains are highlighted in green. Taken in red.

    Args:
        entries: List of DomainEntry results.
        name:    Brand name (for the section header).
        cols:    Number of columns in the grid (default 3).
    """
    from .banner import section
    section(f"Domain Availability  —  {escape(name)}" if name else "Domain Availability", C_TEAL)
    _con.print()

    if not entries:
        _con.print(f"   [{C_GRAY}]No domain results.[/{C_GRAY}]")
        return

    # Split into free / taken / unknown for the summary
    free    = [e for e in entries if e.status == "free"]
    taken   = [e for e in entries if e.status == "taken"]
    unknown = [e for e in entries if e.status == "unknown"]

    # Summary line
    _con.print(
        f"   [{C_GREEN}]✔ {len(free)} free[/{C_GREEN}]   "
        f"[{C_RED}]✘ {len(taken)} taken[/{C_RED}]   "
        f"[{C_GRAY}]? {len(unknown)} unknown[/{C_GRAY}]   "
        f"[dim {C_GRAY}]{len(entries)} checked[/dim {C_GRAY}]"
    )
    _con.print()

    # Grid table
    t = Table(
        box=box.SIMPLE_HEAD,
        border_style=f"dim {C_TEAL}",
        header_style=f"bold {C_TEAL}",
        expand=False,
        padding=(0, 1),
        show_header=True,
    )
    for _ in range(cols):
        t.add_column("Domain",    style="",          width=24)
        t.add_column("Status",    style="",          width=8)
        t.add_column("TLD Rank",  style="",          width=8)

    # Fill rows
    row_buf: list[str] = []
    for entry in sorted(entries, key=lambda e: (e.status != "free", e.tld_rank)):
        col    = _avail_colour(entry.status)
        icon   = _avail_icon(entry.status)
        domain = f"[{col}]{icon}[/{col}] [{C_WHITE}]{escape(entry.domain)}[/{C_WHITE}]"
        status = f"[bold {col}]{entry.status.upper():<6}[/bold {col}]"
        rank   = f"[dim {C_GRAY}]{entry.tld_rank}[/dim {C_GRAY}]"
        row_buf.extend([domain, status, rank])

        if len(row_buf) == cols * 3:
            t.add_row(*row_buf)
            row_buf = []

    # Pad last row
    if row_buf:
        while len(row_buf) < cols * 3:
            row_buf.extend(["", "", ""])
        t.add_row(*row_buf)

    _con.print(Padding(t, (0, 2)))
    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 6  PLATFORM HANDLE TABLE
# ─────────────────────────────────────────────────────────────────────────────

_PLATFORM_ICONS: dict[str, str] = {
    "github":      "⬡",
    "pypi":        "⬢",
    "npm":         "⬡",
    "docker":      "⬢",
    "huggingface": "🤗",
}

def print_platform_table(
    entries:  Sequence[PlatformEntry],
    name:     str = "",
) -> None:
    """
    Render platform handle availability across GitHub, PyPI, npm, Docker, etc.
    """
    from .banner import section
    section(
        f"Platform Availability  —  {escape(name)}" if name else "Platform Availability",
        C_PURPLE,
    )
    _con.print()

    if not entries:
        _con.print(f"   [{C_GRAY}]No platform results.[/{C_GRAY}]")
        return

    t = Table(
        box=box.ROUNDED,
        border_style=f"dim {C_PURPLE}",
        header_style=f"bold {C_PURPLE}",
        expand=False,
        padding=(0, 1),
    )
    t.add_column("Platform",  style=f"dim {C_WHITE}",   width=14)
    t.add_column("Handle",    style=f"bold {C_WHITE}",  width=28)
    t.add_column("Status",    style="",                  width=10, justify="center")
    t.add_column("URL",       style=f"dim {C_GRAY}",    width=40)

    platform_urls: dict[str, str] = {
        "github":      "https://github.com/{handle}",
        "pypi":        "https://pypi.org/project/{handle}/",
        "npm":         "https://www.npmjs.com/package/{handle}",
        "docker":      "https://hub.docker.com/u/{handle}",
        "huggingface": "https://huggingface.co/{handle}",
    }

    for entry in sorted(entries, key=lambda e: e.platform):
        col     = _avail_colour(entry.status)
        icon    = _avail_icon(entry.status)
        p_icon  = _PLATFORM_ICONS.get(entry.platform, "○")
        url_tpl = platform_urls.get(entry.platform, "{handle}")
        url     = url_tpl.format(handle=entry.handle)

        t.add_row(
            f"{p_icon} {entry.platform.capitalize()}",
            escape(entry.handle),
            f"[bold {col}]{icon} {entry.status.upper()}[/bold {col}]",
            url if entry.status == "free" else f"[dim {C_GRAY}]{url}[/dim {C_GRAY}]",
        )

    _con.print(Padding(t, (0, 2)))
    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 7  BRAND ANALYSIS TABLE
# ─────────────────────────────────────────────────────────────────────────────

def print_analysis_table(data_list: Sequence[AnalysisData]) -> None:
    """
    Multi-name analysis comparison table.
    Shows all four scoring dimensions side-by-side.
    """
    from .banner import section
    section("Brand Strength Analysis", C_PURPLE)
    _con.print()

    if not data_list:
        _con.print(f"   [{C_GRAY}]No analysis data.[/{C_GRAY}]")
        return

    t = Table(
        box=box.ROUNDED,
        border_style=f"dim {C_PURPLE}",
        header_style=f"bold {C_PURPLE}",
        expand=False,
        padding=(0, 1),
    )
    t.add_column("Name",        style=f"bold {C_WHITE}", width=18)
    t.add_column("Composite",   style="",                width=12, justify="center")
    t.add_column("Pronounce",   style="",                width=12, justify="center")
    t.add_column("Memory",      style="",                width=12, justify="center")
    t.add_column("Unique",      style="",                width=12, justify="center")
    t.add_column("Len Fit",     style="",                width=12, justify="center")
    t.add_column("Tier",        style="",                width=10, justify="center")
    t.add_column("TM",          style="",                width=8,  justify="center")

    for d in sorted(data_list, key=lambda x: -x.score):
        tc = _tier_colour(d.tier)
        tm = _tm_risk_colour(d.tm_risk)

        def _cell(score: int) -> str:
            c = _score_colour(score)
            return f"[bold {c}]{score:3}[/bold {c}]  [{c}]{_score_bar(score, 6)}[/{c}]"

        t.add_row(
            escape(d.name.capitalize()),
            _cell(d.score),
            _cell(d.pronounce),
            _cell(d.memorability),
            _cell(d.uniqueness),
            _cell(d.length_fit),
            f"[bold {tc}]{_tier_indicator(d.tier)} {d.tier}[/bold {tc}]",
            f"[{tm}]{d.tm_risk.upper()[:3]}[/{tm}]",
        )

    _con.print(Padding(t, (0, 2)))
    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 8  COMPARISON TABLE
# ─────────────────────────────────────────────────────────────────────────────

def print_comparison_table(names: Sequence[NameResult], top_n: int = 5) -> None:
    """
    Side-by-side comparison of the top N names.
    Each name occupies a column; rows are scoring dimensions.
    """
    from .banner import section
    section(f"Top {min(len(names), top_n)} Name Comparison", C_GOLD)
    _con.print()

    candidates = list(names[:top_n])
    if not candidates:
        return

    t = Table(
        box=box.ROUNDED,
        border_style=f"dim {C_GOLD}",
        header_style=f"bold {C_GOLD}",
        expand=False,
        padding=(0, 1),
    )
    t.add_column("Metric", style=f"dim {C_GRAY}", width=18)
    for res in candidates:
        tc = _tier_colour(res.tier)
        t.add_column(
            f"[bold {tc}]{escape(res.name.capitalize())}[/bold {tc}]",
            width=14,
            justify="center",
        )

    def _row(label: str, getter) -> None:
        cells = [label]
        for res in candidates:
            val    = getter(res)
            colour = _score_colour(val) if isinstance(val, int) else C_WHITE
            cells.append(f"[bold {colour}]{val}[/bold {colour}]")
        t.add_row(*cells)

    _row("Composite",    lambda r: r.score)
    _row("Pronounce",    lambda r: r.pronounce)
    _row("Memory",       lambda r: r.memorability)
    _row("Unique",       lambda r: r.uniqueness)
    _row("Length Fit",   lambda r: r.length_fit)
    _row("Syllables",    lambda r: r.syllables)

    # Tier row
    tier_cells = ["Tier"]
    for res in candidates:
        tc = _tier_colour(res.tier)
        tier_cells.append(
            f"[bold {tc}]{_tier_indicator(res.tier)} {res.tier}[/bold {tc}]"
        )
    t.add_row(*tier_cells)

    # TM risk row
    tm_cells = ["TM Risk"]
    for res in candidates:
        tm_cells.append(
            f"[{_tm_risk_colour(res.tm_risk)}]{res.tm_risk.upper()}[/{_tm_risk_colour(res.tm_risk)}]"
        )
    t.add_row(*tm_cells)

    _con.print(Padding(t, (0, 2)))
    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 9  STARTUP REPORT SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def print_startup_report_summary(
    project:     str,
    keywords:    list[str],
    top_names:   Sequence[NameResult],
    domain_hits: list[DomainEntry],
    elapsed:     float = 0.0,
) -> None:
    """
    Render the full startup naming report summary.

    Shows: project identity, top 5 names, best domain, key stats.
    """
    from .banner import section, subsection
    section("STARTUP NAMING REPORT", C_BANNER)
    _con.print()

    # ── Project identity panel ────────────────────────────────────────────────
    kw_str = "  ·  ".join(f"[{C_TEAL}]{escape(k)}[/{C_TEAL}]" for k in keywords)
    _con.print(Padding(
        Panel(
            f"  [{C_GRAY}]Project:[/{C_GRAY}]  [{C_WHITE}]{escape(project)}[/{C_WHITE}]\n"
            f"  [{C_GRAY}]Keywords:[/{C_GRAY}]  {kw_str}\n"
            f"  [{C_GRAY}]Generated:[/{C_GRAY}]  [{C_WHITE}]{len(top_names)} candidates[/{C_WHITE}]  "
            f"[dim {C_GRAY}]in {elapsed:.1f}s[/dim {C_GRAY}]",
            border_style=f"bold {C_BANNER}",
            padding=(0, 1),
        ),
        (0, 2),
    ))
    _con.print()

    # ── Top 5 names ───────────────────────────────────────────────────────────
    subsection("Top Candidates")
    top5 = list(top_names[:5])
    for rank, res in enumerate(top5, 1):
        tc   = _tier_colour(res.tier)
        sc   = _score_colour(res.score)
        free = [d for d, s in res.domains.items() if s == "free"]
        dom  = f"  [{C_GREEN}]→ {escape(free[0])}[/{C_GREEN}]" if free else ""
        _con.print(
            f"   [{C_GRAY}]{rank}.[/{C_GRAY}]  "
            f"[bold {tc}]{escape(res.name.capitalize()):<18}[/bold {tc}]"
            f"[bold {sc}]{res.score:3}[/bold {sc}]"
            f"  [{tc}]{res.tier:<8}[/{tc}]"
            f"{dom}"
        )

    _con.print()

    # ── Best domain availability ───────────────────────────────────────────────
    free_domains = [e for e in domain_hits if e.status == "free"]
    if free_domains:
        subsection("Best Available Domains")
        for entry in sorted(free_domains, key=lambda e: e.tld_rank, reverse=True)[:8]:
            _con.print(
                f"   [{C_GREEN}]✔[/{C_GREEN}]  "
                f"[bold {C_WHITE}]{escape(entry.domain):<32}[/bold {C_WHITE}]"
                f"[dim {C_GRAY}].{entry.tld}[/dim {C_GRAY}]"
            )
        _con.print()

    # ── Stats strip ───────────────────────────────────────────────────────────
    _con.print(Rule(style=f"dim {C_GRAY}"))
    _con.print(
        Align.center(
            f"[dim {C_GRAY}]"
            f"{len(top_names)} names  ·  "
            f"{len(domain_hits)} domains checked  ·  "
            f"{len(free_domains)} free  ·  "
            f"{elapsed:.1f}s"
            f"[/dim {C_GRAY}]"
        )
    )
    _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 10  EXPORT CONFIRMATION
# ─────────────────────────────────────────────────────────────────────────────

def print_export_summary(path: str, fmt: str, n_records: int = 0) -> None:
    """Print a compact export success confirmation."""
    _con.print()
    _con.print(
        Panel(
            f"  [{C_GREEN}]✔  Export complete[/{C_GREEN}]\n\n"
            f"  [{C_GRAY}]Format :[/{C_GRAY}]  [{C_WHITE}]{fmt.upper()}[/{C_WHITE}]\n"
            f"  [{C_GRAY}]Records:[/{C_GRAY}]  [{C_WHITE}]{n_records}[/{C_WHITE}]\n"
            f"  [{C_GRAY}]File   :[/{C_GRAY}]  [{C_ACCENT}]{escape(path)}[/{C_ACCENT}]",
            border_style=f"bold {C_GREEN}",
            title=f"[bold {C_GREEN}] Exported [/bold {C_GREEN}]",
            padding=(0, 1),
        )
    )
    _con.print()
