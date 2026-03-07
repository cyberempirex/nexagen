"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  cli/help.py  ·  Inline help system — command reference, tips, examples    ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Provides the complete inline help system used inside the interactive CLI.
All output is Rich-formatted and consistent with the NEXAGEN theme.

Public API
──────────
  print_help_overview()         — top-level help with all menu options
  print_help_generate()         — detailed help for name generation
  print_help_analyze()          — detailed help for brand analysis
  print_help_domains()          — detailed help for domain suggestions
  print_help_report()           — detailed help for startup report
  print_help_settings()         — settings reference card
  print_help_export()           — export formats + file locations
  print_help_scoring()          — scoring algorithm explanation
  print_help_profiles()         — profile + style mode reference
  print_help_cli_flags()        — CLI flag reference (--generate, etc.)
  print_help_env_vars()         — environment variable reference
  print_tip(context)            — context-specific quick tip
  print_keyboard_reference()    — key bindings / navigation hints

Design rules:
  • All output uses ui/banner.py helpers — no raw print() calls
  • Each section is self-contained and can be called independently
  • Widths adapt to terminal size (terminal_width() from banner.py)
  • No external state — pure rendering functions
"""

from __future__ import annotations

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
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PINK,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
    GEN_DEFAULT_COUNT,
    GEN_MAX_COUNT,
    GEN_MIN_COUNT,
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    SCORE_DECENT,
    SCORE_PREMIUM,
    SCORE_STRONG,
    SCORE_WEAK,
    TOOL_AUTHOR,
    TOOL_CONTACT,
    TOOL_DOCS,
    TOOL_ECOSYSTEM,
    TOOL_REPO,
    VERSION_TAG,
    Profile,
    StyleMode,
)
from ..ui.banner import (
    console,
    section,
    separator,
    subsection,
    terminal_width,
    msg_info,
    print_panel,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _kv_table(rows: list[tuple[str, str, str]], col1_w: int = 20, col2_w: int = 48) -> Table:
    """Build a two-column key → value table with optional colour for the value."""
    t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        expand=False,
        border_style=f"dim {C_GRAY}",
    )
    t.add_column(style=f"dim {C_GRAY}",   width=col1_w)
    t.add_column(style=f"{C_WHITE}",       width=col2_w)
    for key, val, colour in rows:
        val_mu = f"[bold {colour}]{escape(val)}[/bold {colour}]" if colour else escape(val)
        t.add_row(escape(key), val_mu)
    return t


def _example_block(lines: list[tuple[str, str]]) -> None:
    """Print command example lines: (command, description)."""
    console.print()
    for cmd, desc in lines:
        console.print(
            f"  [{C_ACCENT}]$[/{C_ACCENT}]  "
            f"[bold {C_WHITE}]{escape(cmd)}[/bold {C_WHITE}]"
        )
        if desc:
            console.print(f"     [{C_GRAY}]{escape(desc)}[/{C_GRAY}]")
    console.print()


def _bullet(text: str, colour: str = C_ACCENT, indent: int = 2) -> None:
    pad = " " * indent
    console.print(f"{pad}[{colour}]◆[/{colour}]  [{C_WHITE}]{escape(text)}[/{C_WHITE}]")


def _note(text: str) -> None:
    console.print(f"  [{C_AMBER}]⚠[/{C_AMBER}]  [dim {C_GRAY}]{escape(text)}[/dim {C_GRAY}]")


# ─────────────────────────────────────────────────────────────────────────────
# § 2  HELP OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────

def print_help_overview() -> None:
    """
    Print the top-level help screen covering all menu options.
    Equivalent to running ``nexagen --help`` inside the interactive session.
    """
    section("NEXAGEN HELP", C_BANNER)
    console.print()
    console.print(
        Padding(
            f"[{C_WHITE}]NEXAGEN {VERSION_TAG} is an interactive platform naming intelligence engine.\n"
            f"Use the numbered menu to generate names, analyze brands, check domains,\n"
            f"or produce a full startup naming report.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    # Main menu option table
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_ACCENT}",
        padding=(0, 2),
        expand=False,
        border_style=f"dim {C_ACCENT}",
    )
    t.add_column("#",       style=f"bold {C_ACCENT}", width=4)
    t.add_column("Option",  style=f"bold {C_WHITE}",  width=26)
    t.add_column("What it does",                      width=52)

    options = [
        ("1", "Generate Names",          C_GREEN,
         "Expand keywords → generate candidates → score → show ranked table"),
        ("2", "Analyze Brand Strength",  C_PURPLE,
         "Score an existing name on 4 dimensions with a full breakdown"),
        ("3", "Domain Suggestions",      C_TEAL,
         "Generate domain variants and check availability via RDAP"),
        ("4", "Startup Naming Report",   C_GOLD,
         "Full pipeline: generate + score + domains + platforms in one report"),
        ("5", "About NEXAGEN",           C_GRAY,
         "Tool info, version, ecosystem, datasets, disclaimer"),
        ("6", "Exit",                    C_RED,
         "Quit the application and print session statistics"),
    ]

    for num, label, colour, desc in options:
        t.add_row(
            num,
            f"[bold {colour}]{label}[/bold {colour}]",
            f"[{C_GRAY}]{desc}[/{C_GRAY}]",
        )

    console.print(Padding(t, (0, 2)))
    console.print()

    subsection("Quick Tips")
    tips = [
        "Use 2–4 focused keywords for best results (e.g. 'ai document tool')",
        "Profiles shape vocabulary — use 'ai' for ML tools, 'security' for infosec",
        "Run option 4 (Startup Report) for a complete one-stop analysis",
        "Press Ctrl+C at any sub-prompt to cancel and return to the main menu",
        "All results can be exported to JSON, CSV, or Markdown after each run",
    ]
    for tip in tips:
        _bullet(tip, C_TEAL)

    console.print()
    console.print(
        f"  [{C_GRAY}]Full documentation → [{C_ACCENT}]{TOOL_DOCS}[/{C_ACCENT}][/{C_GRAY}]"
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 3  GENERATE NAMES HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_generate() -> None:
    """Detailed help for option 1 — Generate Names."""
    section("HELP  ·  Generate Names", C_GREEN)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]Option 1 takes keyword input and runs a 5-stage pipeline to produce\n"
            f"a ranked table of brand name candidates with full scoring.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Pipeline Stages")
    stages = [
        ("1  Keyword expansion",  "Seeds are expanded via synonyms and profile vocabulary"),
        ("2  Candidate generation", "6 strategies: direct · prefix+seed · seed+suffix · blends · vocab · mutations"),
        ("3  Deduplication",       "Levenshtein distance ≤ 2 — near-duplicates removed"),
        ("4  Scoring",             "4-dimension composite score (pronounce · memory · unique · length)"),
        ("5  Selection",           f"Top N sorted by score, default N = {GEN_DEFAULT_COUNT}"),
    ]
    t = _kv_table([(s, d, C_ACCENT) for s, d in stages], col1_w=26, col2_w=52)
    console.print(Padding(t, (0, 2)))

    subsection("Keyword Input Rules")
    rules = [
        "Enter 1–8 keywords separated by commas or spaces",
        "Keywords must be alphabetic and at least 2 characters",
        "More specific keywords → more targeted names",
        f"Maximum {GEN_MAX_COUNT} names per run  ·  minimum {GEN_MIN_COUNT}",
    ]
    for r in rules:
        _bullet(r)

    subsection("Example Runs")
    _example_block([
        ("nexagen   [then choose 1]", ""),
        ("Keywords → ai data pipeline", "Generates: datapipe, aipipe, flowbase, dataflow…"),
        ("Keywords → cloud security platform", "Generates: cloudshield, securehub, vaultex…"),
        ("Keywords → note taking minimalist", "Generates: notedly, markdesk, quillpad…"),
    ])

    _note(
        "Names with trademark risk HIGH are still shown — verify before use. "
        "NEXAGEN cannot guarantee trademark clearance."
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 4  ANALYZE BRAND HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_analyze() -> None:
    """Detailed help for option 2 — Analyze Brand Strength."""
    section("HELP  ·  Analyze Brand Strength", C_PURPLE)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]Option 2 evaluates one or more brand names you already have.\n"
            f"It scores each across four independent dimensions and shows a\n"
            f"detailed breakdown with a score card and comparison table.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Scoring Dimensions  (all 0–100)")
    dims = [
        ("Pronounceability", "30%", C_TEAL,
         "Vowel ratio · consonant clusters · CVCV alternation · syllable count"),
        ("Memorability",     "30%", C_PURPLE,
         "Length fitness · strong opening · ending vowel · alliteration · rhythm"),
        ("Uniqueness",       "20%", C_ACCENT,
         "Distance from common words · trademark blacklist · pool similarity"),
        ("Length Fitness",   "20%", C_GOLD,
         "Ideal range 4–8 chars · penalty for short (<4) or long (>8)"),
    ]
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_PURPLE}",
        padding=(0, 1),
        expand=False,
    )
    t.add_column("Dimension",   style=f"bold {C_WHITE}",  width=18)
    t.add_column("Weight",      style=f"bold {C_GOLD}",   width=8)
    t.add_column("What's measured",                       width=52)

    for dim, weight, colour, desc in dims:
        t.add_row(
            f"[bold {colour}]{dim}[/bold {colour}]",
            weight,
            f"[{C_GRAY}]{desc}[/{C_GRAY}]",
        )
    console.print(Padding(t, (0, 2)))

    subsection("Brand Tiers")
    tiers = [
        (f"◆ PREMIUM   {SCORE_PREMIUM}–100", C_GOLD,   "Exceptional — all metrics above threshold"),
        (f"▲ STRONG    {SCORE_STRONG}–{SCORE_PREMIUM-1}", C_GREEN,  "Strong candidate — good to proceed"),
        (f"● DECENT    {SCORE_DECENT}–{SCORE_STRONG-1}", C_ACCENT, "Usable — some weak dimensions"),
        (f"▼ WEAK      {SCORE_WEAK}–{SCORE_DECENT-1}",  C_AMBER,  "Problematic — significant issues"),
        (f"✕ POOR      0–{SCORE_WEAK-1}",               C_RED,    "Avoid — multiple failures"),
    ]
    for label, colour, desc in tiers:
        console.print(
            f"   [{colour}]{label:<22}[/{colour}]  [{C_GRAY}]{desc}[/{C_GRAY}]"
        )

    console.print()
    subsection("Multi-name Input")
    console.print(
        f"  [{C_GRAY}]Separate multiple names with commas:[/{C_GRAY}]\n"
        f"  [{C_WHITE}]Names(s) → paperdesk, paperflow, paperhub[/{C_WHITE}]\n\n"
        f"  [{C_GRAY}]All names are scored and a comparison table is shown.[/{C_GRAY}]"
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 5  DOMAIN SUGGESTIONS HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_domains() -> None:
    """Detailed help for option 3 — Domain Suggestions."""
    section("HELP  ·  Domain Suggestions", C_TEAL)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]Option 3 generates domain variants for a brand name and checks\n"
            f"their registration status via RDAP (Registry Data Access Protocol).\n"
            f"It also checks platform handle availability optionally.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Domain Variants Generated")
    _bullet("name.com  ·  name.io  ·  name.ai  ·  name.co  ·  name.dev  (preferred TLDs)", C_TEAL)
    _bullet("name + all ranked TLDs in TLD_SCORES (40 TLDs total)", C_TEAL)
    _bullet("prefix + name.tld  (e.g. getnexagen.com, trynexagen.io)", C_TEAL)
    _bullet("name + suffix.tld  (e.g. nexagenhub.com, nexagenlab.io)", C_TEAL)
    console.print()

    subsection("Availability Check Method")
    console.print(
        Padding(
            f"[{C_GRAY}]Domains are checked using RDAP (rdap.org). A 404 response means\n"
            f"the domain is unregistered (FREE). A 200 response means it is\n"
            f"registered (TAKEN). Network failures are reported as UNKNOWN.\n\n"
            f"Checks run in parallel using up to {12} workers for speed.\n"
            f"Each check times out after {8.0}s. All results are shown.[/{C_GRAY}]",
            (0, 2),
        )
    )

    subsection("Platform Checks")
    platforms = [
        ("GitHub",      "https://api.github.com/users/{handle}",   "User/Org availability"),
        ("PyPI",        "https://pypi.org/pypi/{package}/json",     "Package name availability"),
        ("npm",         "https://registry.npmjs.org/{package}",     "Package name availability"),
    ]
    t = _kv_table(
        [(p, u, C_GRAY) for p, u, _ in platforms],
        col1_w=12, col2_w=48,
    )
    console.print(Padding(t, (0, 2)))

    _note(
        "RDAP availability is not a guarantee of trademark clearance. "
        "An unregistered domain may still conflict with a registered trademark."
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 6  STARTUP REPORT HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_report() -> None:
    """Detailed help for option 4 — Startup Naming Report."""
    section("HELP  ·  Startup Naming Report", C_GOLD)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]Option 4 is the most comprehensive mode. It combines all four\n"
            f"operations into a single animated report.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Report Stages")
    stages = [
        ("1  Keyword analysis",   "Expand seeds → build vocabulary pool"),
        ("2  Name generation",    "Generate candidates from all strategies"),
        ("3  Brand scoring",      "Score every candidate on 4 dimensions"),
        ("4  Domain discovery",   "Check domains for top 5 names"),
        ("5  Platform checks",    "Check GitHub / PyPI / npm for best name"),
        ("6  Summary display",    "Ranked table + domain grid + stats strip"),
    ]
    for num, label, desc in [s[:1][0] + " " + s[1:2][0] for s in stages] if False else stages:
        console.print(
            f"  [{C_GOLD}]{num:<3}[/{C_GOLD}]  "
            f"[bold {C_WHITE}]{label:<24}[/bold {C_WHITE}]"
            f"[{C_GRAY}]{desc}[/{C_GRAY}]"
        )

    console.print()
    subsection("Inputs Required")
    _bullet("Project name  — label for the report header (any text)")
    _bullet("Keywords  — 1–6 themes or concepts (same as option 1)")
    _bullet("Count  — how many names to generate (default 20)")
    console.print()

    _note(
        "The report can take 30–120 seconds depending on domain check latency. "
        "Disable domain checks (NEXAGEN_NO_CHECKS=1) for offline use."
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 7  SETTINGS REFERENCE
# ─────────────────────────────────────────────────────────────────────────────

def print_help_settings() -> None:
    """Full settings reference card."""
    section("SETTINGS REFERENCE", C_ACCENT)
    console.print()

    console.print(
        Padding(
            f"[{C_GRAY}]Settings are stored in [bold {C_WHITE}]~/.nexagen/settings.toml[/bold {C_WHITE}].\n"
            f"Edit the file directly or use the in-session quick customise prompt.[/{C_GRAY}]",
            (0, 2),
        )
    )
    console.print()

    groups: list[tuple[str, str, list[tuple[str, str, str]]]] = [
        ("Generation", C_GREEN, [
            ("profile",      f"Industry profile  default: generic", "Choices: " + " · ".join(Profile.choices())),
            ("style_mode",   f"Naming style  default: minimal",     "Choices: " + " · ".join(StyleMode.choices())),
            ("count",        f"Names to generate  default: {GEN_DEFAULT_COUNT}", f"Range: {GEN_MIN_COUNT}–{GEN_MAX_COUNT}"),
            ("min_len",      f"Minimum name length  default: {NAME_LENGTH_IDEAL_MIN}",  f"Hard min: {NAME_LENGTH_HARD_MIN}"),
            ("max_len",      f"Maximum name length  default: {NAME_LENGTH_IDEAL_MAX}",  f"Hard max: {NAME_LENGTH_HARD_MAX}"),
            ("use_suffixes", "Apply suffix mutations  default: true", ""),
            ("use_prefixes", "Apply prefix mutations  default: true", ""),
            ("use_multiword","Generate compound names  default: true", ""),
            ("use_synonyms", "Expand via synonyms  default: true",   ""),
        ]),
        ("Domain Checks", C_TEAL, [
            ("do_domain_checks",  "Enable RDAP domain checks  default: true",    ""),
            ("do_handle_checks",  "Enable platform handle checks  default: true", ""),
            ("check_workers",     "Parallel check threads  default: 12",         "Range: 1–64"),
            ("check_timeout",     "Per-request timeout (sec)  default: 8.0",     ""),
            ("preferred_tlds",    "Ordered TLD preference  default: com io ai co dev", ""),
            ("check_github",      "Check GitHub availability  default: true",    ""),
            ("check_pypi",        "Check PyPI availability  default: true",      ""),
            ("check_npm",         "Check npm availability  default: true",       ""),
        ]),
        ("Interface", C_PURPLE, [
            ("animations",    "Enable Rich animations  default: true",    "Set false for CI"),
            ("clear_on_start","Clear screen on startup  default: true",   ""),
            ("show_scores",   "Show score columns in table  default: true", ""),
            ("show_domains",  "Show domain column in table  default: true", ""),
            ("table_row_limit","Max rows in output table  default: 30",   ""),
        ]),
        ("Export", C_GOLD, [
            ("export_dir",    "Output directory  default: ~/.nexagen/exports", ""),
            ("auto_export",   "Auto-export after each run  default: false",    ""),
            ("export_format", "Default format  default: json",                 "json · csv · markdown · all"),
        ]),
        ("Cache & Logging", C_GRAY, [
            ("cache_enabled",     "Enable domain check cache  default: true",  ""),
            ("cache_ttl_seconds", "Cache lifetime (sec)  default: 3600",       ""),
            ("log_enabled",       "Enable file logging  default: false",        ""),
            ("log_level",         "Log level  default: WARNING",               "DEBUG · INFO · WARNING · ERROR"),
            ("check_for_updates", "GitHub update check  default: true",        ""),
        ]),
    ]

    for group_name, colour, fields in groups:
        subsection(group_name, colour)
        t = Table(
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 1),
            expand=False,
        )
        t.add_column(style=f"bold {colour}",  width=22)
        t.add_column(style=f"{C_WHITE}",       width=40)
        t.add_column(style=f"dim {C_GRAY}",    width=30)
        for key, desc, note in fields:
            t.add_row(key, desc, note)
        console.print(Padding(t, (0, 2)))

    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 8  EXPORT HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_export() -> None:
    """Export formats and file location reference."""
    section("HELP  ·  Export", C_ACCENT)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]After every command completes, NEXAGEN offers to export results.\n"
            f"Files are written to the export directory (default: ~/.nexagen/exports/).[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Export Formats")
    formats = [
        ("json",     C_TEAL,   "Structured JSON with metadata envelope, version, timestamp, and full record array"),
        ("csv",      C_GREEN,  "Flat CSV with header row — compatible with Excel, pandas, any spreadsheet tool"),
        ("markdown", C_PURPLE, "Formatted Markdown report with sections per name — ready for GitHub or Notion"),
        ("all",      C_GOLD,   "Writes all three formats simultaneously to the export directory"),
    ]
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_ACCENT}",
        padding=(0, 2),
        expand=False,
    )
    t.add_column("Format",    style=f"bold {C_WHITE}",  width=12)
    t.add_column("Extension", style=f"dim {C_GRAY}",    width=10)
    t.add_column("Description",                          width=58)

    ext_map = {"json": ".json", "csv": ".csv", "markdown": ".md", "all": "*"}
    for fmt, colour, desc in formats:
        t.add_row(
            f"[bold {colour}]{fmt}[/bold {colour}]",
            ext_map[fmt],
            f"[{C_GRAY}]{desc}[/{C_GRAY}]",
        )
    console.print(Padding(t, (0, 2)))

    subsection("File Naming")
    console.print(
        Padding(
            f"  [{C_GRAY}]Pattern: [bold {C_WHITE}]nexagen_export_YYYYMMDD_HHMMSS.ext[/bold {C_WHITE}]\n"
            f"  Example: [bold {C_WHITE}]nexagen_export_20260305_143022.json[/bold {C_WHITE}]\n\n"
            f"  Override the directory:\n"
            f"  [{C_ACCENT}]NEXAGEN_EXPORT_DIR=/path/to/dir nexagen[/{C_ACCENT}]",
            (0, 0),
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 9  SCORING ALGORITHM HELP
# ─────────────────────────────────────────────────────────────────────────────

def print_help_scoring() -> None:
    """Full scoring algorithm explanation."""
    section("SCORING ALGORITHM", C_PURPLE)
    console.print()

    console.print(
        Padding(
            f"[{C_WHITE}]NEXAGEN computes a composite brand score (0–100) from four\n"
            f"independent dimensions. Each dimension contributes a weighted share.[/{C_WHITE}]",
            (0, 2),
        )
    )
    console.print()

    subsection("Formula")
    console.print(
        Padding(
            f"  [{C_WHITE}]composite = (\n"
            f"    pronounce   × 0.30 +\n"
            f"    memorability × 0.30 +\n"
            f"    uniqueness   × 0.20 +\n"
            f"    length_fit   × 0.20\n"
            f"  )[/{C_WHITE}]\n\n"
            f"  [{C_GRAY}]Weights are configurable in settings under score_weights.[/{C_GRAY}]",
            (0, 2),
        )
    )

    subsection("Pronounceability Factors")
    factors = [
        ("Vowel ratio",        "Ideal 30–55%. Penalty outside 20–65% range."),
        ("Consonant clusters", "Max run ≤ 2 for bonus. Run ≥ 4 penalised heavily."),
        ("Alternation score",  "CVCV pattern quality 0.0–1.0 (from text_utils)."),
        ("Forbidden sequences","Known unpronounceable pairs (aa, kk, wq, bx…) → -20."),
        ("Syllable count",     "2–3 syllables ideal (+10). >4 penalised."),
    ]
    t = _kv_table([(f, d, C_TEAL) for f, d in factors], col1_w=22, col2_w=50)
    console.print(Padding(t, (0, 2)))

    subsection("Memorability Factors")
    factors2 = [
        ("Length sweet spot",   f"4–8 chars: +20. Penalty increases beyond 10 chars."),
        ("Strong opening",      "Starts with b/d/f/g/k/l/m/n/p/r/s/t/v: +8."),
        ("Vowel ending",        "Name ends on a vowel (soft, approachable): +6."),
        ("Alliteration",        "First two sounds match: +8 bonus."),
        ("Syllable rhythm",     "2 syllables: +12. 3: +8. 1: +4. 4+: penalty."),
    ]
    t2 = _kv_table([(f, d, C_PURPLE) for f, d in factors2], col1_w=22, col2_w=50)
    console.print(Padding(t2, (0, 2)))

    subsection("Uniqueness Factors")
    factors3 = [
        ("Common word check",  "Name in common_words.txt → -25 uniqueness"),
        ("Blacklist proximity","Levenshtein ≤ 1 from blacklisted brand → -30, return 0"),
        ("Pool similarity",    "Distance ≤ 2 from other candidates in this run → -30"),
    ]
    t3 = _kv_table([(f, d, C_ACCENT) for f, d in factors3], col1_w=22, col2_w=50)
    console.print(Padding(t3, (0, 2)))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 10  PROFILES + STYLES REFERENCE
# ─────────────────────────────────────────────────────────────────────────────

def print_help_profiles() -> None:
    """Profile and style mode reference card."""
    section("PROFILES  &  STYLE MODES", C_ACCENT)
    console.print()

    subsection("Industry Profiles")
    console.print(
        Padding(
            f"[{C_GRAY}]Profiles control which vocabulary datasets are prioritised\n"
            f"during keyword expansion and candidate generation.[/{C_GRAY}]",
            (0, 2),
        )
    )

    profiles = [
        ("tech",       C_BLUE,   "Technology tools and developer platforms",
         "tech_terms.txt (302 terms)"),
        ("ai",         C_PURPLE, "Machine learning, AI, data science products",
         "ai_terms.txt (150 terms)"),
        ("security",   C_RED,    "Cybersecurity, infosec, privacy tools",
         "tech_terms.txt blended"),
        ("finance",    C_GOLD,   "Fintech, payments, banking, trading",
         "business_terms.txt (226 terms)"),
        ("health",     C_GREEN,  "Healthtech, medical, wellness",
         "business_terms.txt blended"),
        ("social",     C_PINK,   "Social platforms, communities, messaging",
         "business_terms.txt blended"),
        ("education",  C_TEAL,   "Edtech, learning tools, academic",
         "business_terms.txt blended"),
        ("document",   C_WHITE,  "Document tools, writing, productivity",
         "business_terms.txt blended"),
        ("generic",    C_GRAY,   "General purpose — blends all vocabularies",
         "All datasets equally weighted"),
    ]

    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_ACCENT}",
        padding=(0, 1),
        expand=False,
    )
    t.add_column("Profile",    style=f"bold {C_WHITE}",  width=12)
    t.add_column("Best for",   style=f"{C_WHITE}",       width=38)
    t.add_column("Vocabulary", style=f"dim {C_GRAY}",    width=32)

    for name, colour, desc, vocab in profiles:
        t.add_row(
            f"[bold {colour}]{name}[/bold {colour}]",
            desc,
            vocab,
        )
    console.print(Padding(t, (0, 2)))
    console.print()

    subsection("Style Modes")
    console.print(
        Padding(
            f"[{C_GRAY}]Styles influence mutation patterns and suffix/prefix selection\n"
            f"applied during candidate generation.[/{C_GRAY}]",
            (0, 2),
        )
    )

    styles = [
        ("minimal",    C_WHITE,   "Clean, short names. Minimal suffixes. 4–6 chars preferred."),
        ("futuristic", C_PURPLE,  "Power endings: -ex, -ix, -on, -en. Sci-fi aesthetic."),
        ("aggressive", C_RED,     "Hard consonants. Strong openings. Impact-focused."),
        ("soft",       C_PINK,    "Vowel endings. Gentle sounds. -ly, -fy, -io suffixes."),
        ("technical",  C_BLUE,    "Compound precision. -ops, -base, -kit. Developer-focused."),
        ("luxury",     C_GOLD,    "Short, premium feel. Fewer suffixes. 4–5 chars."),
    ]

    for name, colour, desc in styles:
        console.print(
            f"   [{colour}]▸[/{colour}]  "
            f"[bold {C_WHITE}]{name:<12}[/bold {C_WHITE}]  "
            f"[{C_GRAY}]{desc}[/{C_GRAY}]"
        )

    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 11  CLI FLAGS REFERENCE
# ─────────────────────────────────────────────────────────────────────────────

def print_help_cli_flags() -> None:
    """CLI flag reference for the nexagen command."""
    section("CLI FLAGS  ·  nexagen [OPTIONS]", C_ACCENT)
    console.print()

    flags = [
        ("--version, -v",           "",              C_GRAY,   "Print version and exit"),
        ("--no-anim",               "",              C_GRAY,   "Disable all animations (for CI / pipe output)"),
        ("--no-clear",              "",              C_GRAY,   "Do not clear the screen on startup"),
        ("--profile PROFILE, -p",   "PROFILE",       C_ACCENT, f"Set industry profile. Choices: {', '.join(Profile.choices())}"),
        ("--style STYLE",           "STYLE",         C_ACCENT, f"Set style mode. Choices: {', '.join(StyleMode.choices())}"),
        ("--count N, -n",           "N",             C_GREEN,  f"Number of names to generate (1–{GEN_MAX_COUNT})"),
        ("--generate KW …, -g",     "KW [KW …]",     C_GOLD,   "Generate names from keywords and exit (headless mode)"),
        ("--no-update-check",       "",              C_GRAY,   "Skip the GitHub release update check at startup"),
    ]

    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_ACCENT}",
        padding=(0, 1),
        expand=False,
    )
    t.add_column("Flag",       style=f"bold {C_WHITE}",  width=28)
    t.add_column("Description",                           width=60)

    for flag, _arg, colour, desc in flags:
        t.add_row(
            f"[bold {colour}]{flag}[/bold {colour}]",
            f"[{C_GRAY}]{desc}[/{C_GRAY}]",
        )
    console.print(Padding(t, (0, 2)))

    subsection("Headless Mode Examples")
    _example_block([
        ("nexagen --generate ai data pipeline",
         "Generate names immediately, print table, exit"),
        ("nexagen --generate cloud security --count 40 --profile security",
         "40 names, security profile"),
        ("nexagen --generate startup --no-anim --no-clear",
         "No animations, useful in scripts"),
        ("nexagen --generate fintech --style futuristic --count 10 > names.txt",
         "Pipe output to file"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# § 12  ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────────────────────

def print_help_env_vars() -> None:
    """Environment variable reference for CI / Docker / scripting."""
    section("ENVIRONMENT VARIABLES", C_BLUE)
    console.print()

    console.print(
        Padding(
            f"[{C_GRAY}]Environment variables override settings for one session without\n"
            f"touching ~/.nexagen/settings.toml. Useful for CI pipelines, Docker,\n"
            f"and shell scripts.[/{C_GRAY}]",
            (0, 2),
        )
    )
    console.print()

    env_vars = [
        ("NEXAGEN_PROFILE",     "Set industry profile",           f"e.g. ai · tech · security"),
        ("NEXAGEN_STYLE",       "Set style mode",                 f"e.g. minimal · futuristic"),
        ("NEXAGEN_COUNT",       "Number of names to generate",    f"Integer 1–{GEN_MAX_COUNT}"),
        ("NEXAGEN_NO_CHECKS",   "Disable all availability checks","Set to any non-empty value"),
        ("NEXAGEN_NO_ANIM",     "Disable animations",             "Set to any non-empty value"),
        ("NEXAGEN_EXPORT_DIR",  "Override export directory",      "Absolute path"),
        ("NEXAGEN_LOG_LEVEL",   "Set log verbosity",              "DEBUG · INFO · WARNING · ERROR"),
    ]

    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style=f"bold {C_BLUE}",
        padding=(0, 1),
        expand=False,
    )
    t.add_column("Variable",      style=f"bold {C_WHITE}",  width=26)
    t.add_column("Effect",        style=f"{C_WHITE}",       width=34)
    t.add_column("Values",        style=f"dim {C_GRAY}",    width=28)

    for var, effect, vals in env_vars:
        t.add_row(var, effect, vals)
    console.print(Padding(t, (0, 2)))

    subsection("Usage Examples")
    _example_block([
        ("NEXAGEN_PROFILE=ai NEXAGEN_COUNT=50 nexagen --generate agent",
         "AI profile, 50 names"),
        ("NEXAGEN_NO_CHECKS=1 nexagen",
         "Full interactive mode, domain checks disabled"),
        ("NEXAGEN_EXPORT_DIR=/tmp/exports NEXAGEN_NO_ANIM=1 nexagen --generate saas",
         "CI-friendly headless run"),
        ("NEXAGEN_LOG_LEVEL=DEBUG nexagen 2>nexagen.log",
         "Capture debug log"),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# § 13  CONTEXT-SPECIFIC TIPS
# ─────────────────────────────────────────────────────────────────────────────

_TIPS: dict[str, list[str]] = {
    "generate": [
        "Use 3–4 specific keywords for tighter, more relevant output.",
        "The 'ai' profile prioritises neural/model/agent vocabulary — ideal for ML tools.",
        "Style 'futuristic' adds -ex/-on/-ix endings for a sci-fi brand feel.",
        f"Increase count to {GEN_MAX_COUNT} and filter the table manually for creative runs.",
        "Keywords like 'fast', 'smart', 'pro' are too generic — try domain-specific terms.",
    ],
    "analyze": [
        "A STRONG score (75+) is a good bar for real product naming.",
        "Low uniqueness usually means the name is too close to a common English word.",
        "Compare 3–5 variants at once — the comparison table shows the best at a glance.",
        "Phonetic key (Soundex) helps identify names that sound alike even if spelled differently.",
        "A HIGH trademark risk means the name is within edit-distance 2 of a known major brand.",
    ],
    "domains": [
        "Check .io and .ai first for developer/SaaS tools — they read as credible.",
        "A .com availability is rare for short names — .co or .dev are strong alternatives.",
        "UNKNOWN status means RDAP didn't respond — retry or check manually.",
        "Prefix variants like 'get' and 'use' are common fallbacks when the bare name is taken.",
        "Platform handle availability matters as much as domain — check GitHub early.",
    ],
    "report": [
        "The startup report is the best starting point — it runs everything in one pass.",
        "6 keywords is the practical maximum — more dilutes the vocabulary focus.",
        f"Set count to {GEN_MAX_COUNT} for the report to maximise candidate diversity.",
        "Disable domain checks with NEXAGEN_NO_CHECKS=1 if you're iterating quickly offline.",
        "Export the report as Markdown and paste directly into a Notion or GitHub doc.",
    ],
    "export": [
        "Use 'all' to get JSON + CSV + Markdown in one step.",
        "The JSON envelope includes metadata (version, date, count) for traceability.",
        "CSV output imports directly into Google Sheets or Excel for further filtering.",
        "Markdown output is pre-formatted for Notion, GitHub README, or design briefs.",
    ],
    "general": [
        "Ctrl+C at any sub-prompt cancels the current operation and returns to the menu.",
        "Settings persist between sessions — customise once, not every run.",
        "The boot sequence checks dataset integrity — if it fails, reinstall the package.",
        f"File a bug report or request a feature at {TOOL_REPO}/issues",
        f"Contact the team: {TOOL_CONTACT}",
    ],
}


def print_tip(context: str = "general") -> None:
    """
    Print a random context-specific tip.

    Args:
        context: One of "generate", "analyze", "domains", "report",
                 "export", "general".
    """
    import random
    tips = _TIPS.get(context, _TIPS["general"])
    tip  = random.choice(tips)
    console.print()
    console.print(
        Panel(
            f"  [{C_GOLD}]✦  Tip[/{C_GOLD}]  [{C_WHITE}]{escape(tip)}[/{C_WHITE}]",
            border_style=f"dim {C_GOLD}",
            padding=(0, 1),
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 14  KEYBOARD REFERENCE
# ─────────────────────────────────────────────────────────────────────────────

def print_keyboard_reference() -> None:
    """Print keyboard shortcuts and navigation hints."""
    section("KEYBOARD REFERENCE", C_GRAY)
    console.print()

    keys = [
        ("1 – 6",    C_ACCENT, "Select a main menu option"),
        ("Enter",    C_WHITE,  "Confirm input / advance to next prompt"),
        ("Ctrl + C", C_AMBER,  "Cancel current operation, return to main menu"),
        ("Ctrl + C  (at menu)", C_RED, "Exit the application immediately"),
        ("y / n",    C_GREEN,  "Answer Yes/No confirmation prompts"),
    ]

    t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
        expand=False,
    )
    t.add_column(style=f"bold {C_WHITE}",  width=26)
    t.add_column(style=f"{C_GRAY}",        width=52)

    for key, colour, desc in keys:
        t.add_row(
            f"[bold {colour}]{key}[/bold {colour}]",
            desc,
        )
    console.print(Padding(t, (0, 2)))
    console.print()
    console.print(
        Align.center(
            f"[dim {C_GRAY}]NEXAGEN {VERSION_TAG}  ·  {TOOL_AUTHOR}  ·  {TOOL_REPO}[/dim {C_GRAY}]"
        )
    )
    console.print()
