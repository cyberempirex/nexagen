"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  ui/banner.py  ·  Startup banner, menus, about, update notifications        ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Responsibilities
────────────────
  • print_banner(animated)       — full animated startup banner
  • print_main_menu(highlight)   — main navigation menu
  • prompt_menu()                — menu input prompt
  • print_about()                — full about / info screen
  • section / subsection         — section dividers used project-wide
  • msg_ok / msg_fail / msg_warn — status message helpers
  • print_update_available()     — GitHub update notification
  • print_session_footer()       — end-of-session stats strip
  • print_goodbye()              — clean exit farewell

All render functions write to the module-level ``console`` instance.
Import ``console`` directly when you need to write outside this module.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ..config.constants import (
    ANIM_BANNER_DELAY,
    ANIM_CHAR_TYPEWRITER,
    ANIM_SCREEN_CLEAR_PAUSE,
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
    DISCLAIMER,
    SLOGAN,
    TOOL_AUTHOR,
    TOOL_CONTACT,
    TOOL_DOCS,
    TOOL_ECOSYSTEM,
    TOOL_NAME,
    TOOL_REPO,
    TOOL_TAGLINE,
    VERSION,
    VERSION_TAG,
    MenuOption,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  SHARED CONSOLE
# ─────────────────────────────────────────────────────────────────────────────

#: Module-level console — import this wherever you need styled output.
console = Console(highlight=False, markup=True)

# ─────────────────────────────────────────────────────────────────────────────
# § 2  ASCII ART  (hand-crafted box-drawing block letters)
# ─────────────────────────────────────────────────────────────────────────────

_ART_FULL: list[str] = [
    r" ███╗   ██╗███████╗██╗  ██╗ █████╗  ██████╗ ███████╗███╗   ██╗",
    r" ████╗  ██║██╔════╝╚██╗██╔╝██╔══██╗██╔════╝ ██╔════╝████╗  ██║",
    r" ██╔██╗ ██║█████╗   ╚███╔╝ ███████║██║  ███╗█████╗  ██╔██╗ ██║",
    r" ██║╚██╗██║██╔══╝   ██╔██╗ ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║",
    r" ██║ ╚████║███████╗██╔╝ ██╗██║  ██║╚██████╔╝███████╗██║ ╚████║",
    r" ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝",
]

# Compact art used when terminal width < 72 columns
_ART_COMPACT: list[str] = [
    r"  ██╗  ██╗███████╗██╗  ██╗",
    r"  ████╗ ██║██╔════╝╚██╗██╔╝",
    r"  ██╔██╗██║█████╗   ╚███╔╝ ",
    r"  ██║╚████║███████╗██╔╝ ██╗",
    r"  ╚═╝  ╚══╝╚══════╝╚═╝  ╚═╝",
    r"         · A G E N ·",
]

# Per-line gradient colour applied from top to bottom
_ART_GRADIENT: list[str] = [
    "#d8b4fe",   # lavender-200
    "#c084fc",   # purple-400
    "#a855f7",   # purple-500
    "#9b59b6",   # purple-600
    "#7c3aed",   # violet-700
    "#6d28d9",   # violet-800
]

# ─────────────────────────────────────────────────────────────────────────────
# § 3  TERMINAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def clear_screen() -> None:
    """Clear the terminal screen (Windows + POSIX)."""
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")
        time.sleep(ANIM_SCREEN_CLEAR_PAUSE)


def terminal_width() -> int:
    """Return the current terminal column count, clamped to 40–220."""
    try:
        w = os.get_terminal_size().columns
    except OSError:
        w = getattr(console, "width", 80) or 80
    return max(40, min(int(w), 220))


# ─────────────────────────────────────────────────────────────────────────────
# § 4  BANNER
# ─────────────────────────────────────────────────────────────────────────────

def print_banner(animated: bool = True) -> None:
    """
    Render the full NEXAGEN startup banner.

    Visual structure (full-width terminal)::

        [blank]
         ███╗   ██╗███████╗██╗  ██╗ ...   ← 6-line ASCII art, gradient colours
         ...
        [blank]
        ═══════════════════════════════════
        Platform Naming Intelligence Engine
           CEX-Nexagen  ·  v1.0.0
        ═══════════════════════════════════
        [blank]
        Generate · Analyze · Validate · Discover   ← typewriter or static
        [blank]
        https://github.com/cyberempirex/nexagen
        [blank]

    Args:
        animated: True = per-line art delays + typewriter slogan.
                  False = instant render (for sub-screens and tests).
    """
    tw  = terminal_width()
    art = _ART_COMPACT if tw < 72 else _ART_FULL

    console.print()

    # ── ASCII art with top-to-bottom gradient ─────────────────────────────────
    for i, line in enumerate(art):
        c = _ART_GRADIENT[i % len(_ART_GRADIENT)]
        console.print(
            Align.center(f"[bold {c}]{escape(line)}[/bold {c}]")
        )
        if animated:
            time.sleep(ANIM_BANNER_DELAY)

    console.print()

    # ── Identity block ────────────────────────────────────────────────────────
    rw   = min(64, tw - 4)
    rule = f"[{C_ACCENT}]{'═' * rw}[/{C_ACCENT}]"

    console.print(Align.center(rule))
    if animated:
        time.sleep(0.04)

    console.print(
        Align.center(f"[bold {C_WHITE}]  {TOOL_TAGLINE}  [/bold {C_WHITE}]")
    )
    console.print(
        Align.center(f"[{C_GRAY}]  {TOOL_AUTHOR}  ·  {VERSION_TAG}  [/{C_GRAY}]")
    )
    console.print(Align.center(rule))
    console.print()

    # ── Slogan ────────────────────────────────────────────────────────────────
    _render_slogan(animated)

    # ── Repo link ─────────────────────────────────────────────────────────────
    if animated:
        time.sleep(0.04)
    console.print(
        Align.center(f"[dim {C_GRAY}]{TOOL_REPO}[/dim {C_GRAY}]")
    )
    console.print()


def _render_slogan(animated: bool) -> None:
    """
    Render ``SLOGAN`` with per-word colours.
    When animated, each word types in character-by-character before the
    separator materialises and the next word starts.
    """
    parts   = SLOGAN.split(" · ")
    colours = [C_TEAL, C_PURPLE, C_AMBER, C_GREEN]
    sep     = f" [dim {C_GRAY}]·[/dim {C_GRAY}] "

    if animated:
        done: list[str] = []
        for idx, part in enumerate(parts):
            c     = colours[idx % len(colours)]
            typed = ""
            for ch in part:
                typed += ch
                line = sep.join(
                    done + [f"[bold {c}]{escape(typed)}[/bold {c}]"]
                )
                console.print(Align.center(line), end="\r")
                time.sleep(ANIM_CHAR_TYPEWRITER)
            done.append(f"[bold {c}]{escape(part)}[/bold {c}]")
        # Final complete line
        console.print(Align.center(sep.join(done)))
    else:
        coloured = sep.join(
            f"[bold {colours[i % len(colours)]}]{escape(p)}"
            f"[/bold {colours[i % len(colours)]}]"
            for i, p in enumerate(parts)
        )
        console.print(Align.center(coloured))

    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SECTION DIVIDERS  (used project-wide by all UI modules)
# ─────────────────────────────────────────────────────────────────────────────

def section(title: str, colour: str = C_ACCENT) -> None:
    """Full-width Rule with a bold centred title."""
    console.print()
    console.print(
        Rule(
            f"[bold {colour}]  {escape(title)}  [/bold {colour}]",
            style=f"dim {colour}",
        )
    )


def subsection(label: str, colour: str = C_WHITE) -> None:
    """Lighter-weight headed line with a short underline."""
    console.print()
    console.print(
        f"  [{C_ACCENT}]▸[/{C_ACCENT}]  "
        f"[bold {colour}]{escape(label)}[/bold {colour}]"
    )
    console.print(
        f"  [dim {C_GRAY}]{'─' * (len(label) + 5)}[/dim {C_GRAY}]"
    )


def separator(colour: str = C_GRAY) -> None:
    """Thin full-width horizontal rule with no title."""
    w = min(terminal_width() - 4, 80)
    console.print(f"  [dim {colour}]{'─' * w}[/dim {colour}]")


# ─────────────────────────────────────────────────────────────────────────────
# § 6  MAIN MENU
# ─────────────────────────────────────────────────────────────────────────────

#: Menu items: (option number, display label, hint text, accent colour)
_MENU_ITEMS: list[tuple[int, str, str, str]] = [
    (MenuOption.GENERATE_NAMES,  "Generate Names",
     "Create brand candidates from keywords",             C_GREEN),
    (MenuOption.ANALYZE_BRAND,   "Analyze Brand Strength",
     "Score and evaluate an existing name",               C_PURPLE),
    (MenuOption.DOMAIN_SUGGEST,  "Domain Suggestions",
     "Discover available domains for a name",             C_TEAL),
    (MenuOption.STARTUP_REPORT,  "Startup Naming Report",
     "Full intelligence report for a project",            C_GOLD),
    (MenuOption.ABOUT,           "About NEXAGEN",
     "Version, ecosystem, and tool details",              C_GRAY),
    (MenuOption.EXIT,            "Exit",
     "Quit the application",                              C_RED),
]


def print_main_menu(highlight: Optional[int] = None) -> None:
    """
    Render the main interactive menu.

    On wide terminals (≥88 cols) shows inline hints.
    On narrow terminals shows hints indented below each option.

    Args:
        highlight: Option number to visually highlight (keyboard nav preview).
    """
    section("MAIN MENU", C_ACCENT)
    console.print()

    wide = terminal_width() >= 88

    for num, label, hint, colour in _MENU_ITEMS:
        active = highlight == int(num)
        arrow  = "▶ " if active else "  "
        bg     = f" on {C_DARK}" if active else ""

        num_cell = f"[bold {C_ACCENT}]{int(num)}[/bold {C_ACCENT}]"

        if wide:
            console.print(
                f"   {num_cell}"
                f"  [bold {colour}{bg}]{arrow}{label:<34}[/bold {colour}{bg}]"
                f"[dim {C_GRAY}]{escape(hint)}[/dim {C_GRAY}]"
            )
        else:
            console.print(
                f"   {num_cell}"
                f"  [bold {colour}]{arrow}{label}[/bold {colour}]"
            )
            console.print(
                f"       [dim {C_GRAY}]{escape(hint)}[/dim {C_GRAY}]"
            )

        # Visual gap after the last "real" option and before Exit
        if int(num) == int(MenuOption.ABOUT):
            console.print()

    console.print()
    console.print(
        f"   [{C_GRAY}]Enter option number and press "
        f"[bold {C_WHITE}]Enter[/bold {C_WHITE}][/{C_GRAY}]"
    )
    console.print()


def prompt_menu() -> str:
    """
    Display the menu input prompt and return stripped user input.

    Falls back to plain ``input()`` if Rich.Prompt is unavailable.
    """
    try:
        from rich.prompt import Prompt
        return Prompt.ask(
            f"   [bold {C_WHITE}]→[/bold {C_WHITE}]",
            console=console,
        ).strip()
    except (ImportError, EOFError, KeyboardInterrupt):
        try:
            return input("   → ").strip()
        except (EOFError, KeyboardInterrupt):
            return str(int(MenuOption.EXIT))


def prompt_text(label: str, default: str = "") -> str:
    """Generic text prompt with optional default value."""
    try:
        from rich.prompt import Prompt
        kwargs: dict = {"console": console}
        if default:
            kwargs["default"] = default
        return Prompt.ask(
            f"   [{C_ACCENT}]{escape(label)}[/{C_ACCENT}]",
            **kwargs,
        ).strip()
    except (ImportError, EOFError, KeyboardInterrupt):
        try:
            return input(f"   {label}: ").strip() or default
        except (EOFError, KeyboardInterrupt):
            return default


def prompt_confirm(label: str, default: bool = True) -> bool:
    """Yes/No confirmation prompt."""
    try:
        from rich.prompt import Confirm
        return Confirm.ask(
            f"   [{C_ACCENT}]{escape(label)}[/{C_ACCENT}]",
            default=default,
            console=console,
        )
    except (ImportError, EOFError, KeyboardInterrupt):
        try:
            ans = input(f"   {label} [y/n]: ").strip().lower()
            return ans in ("y", "yes", "1")
        except (EOFError, KeyboardInterrupt):
            return default


# ─────────────────────────────────────────────────────────────────────────────
# § 7  ABOUT SCREEN
# ─────────────────────────────────────────────────────────────────────────────

def print_about() -> None:
    """
    Render the full NEXAGEN about / information screen.

    Sections:
      - Identity card (name, version, author, ecosystem, links)
      - Description paragraph
      - Core Pillars (Generate · Analyze · Validate · Discover)
      - Disclaimer panel
      - Slogan footer
    """
    clear_screen()
    print_banner(animated=False)
    section("ABOUT NEXAGEN", C_BANNER)
    console.print()

    # ── Identity card ─────────────────────────────────────────────────────────
    id_t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
        border_style=f"dim {C_GRAY}",
        expand=False,
    )
    id_t.add_column(style=f"dim {C_GRAY}",   width=16)
    id_t.add_column(style=f"bold {C_WHITE}",  width=54)
    id_t.add_row("Tool",       TOOL_NAME)
    id_t.add_row("Version",    f"{VERSION_TAG}  (stable)")
    id_t.add_row("Author",     TOOL_AUTHOR)
    id_t.add_row("Ecosystem",  TOOL_ECOSYSTEM)
    id_t.add_row("Contact",    TOOL_CONTACT)
    id_t.add_row("Repository", TOOL_REPO)
    id_t.add_row("Docs",       TOOL_DOCS)
    console.print(Padding(id_t, (0, 4)))
    console.print()

    # ── Description ───────────────────────────────────────────────────────────
    console.print(Padding(
        f"[{C_WHITE}]NEXAGEN is an advanced platform naming intelligence engine "
        f"designed to help developers, founders, and creators discover strong, "
        f"natural, and memorable names for platforms, tools, startups, and "
        f"digital products.[/{C_WHITE}]\n\n"
        f"[{C_GRAY}]Rather than producing random or artificial words, NEXAGEN "
        f"generates names using structured datasets, linguistic patterns, and "
        f"industry vocabulary — then evaluates each candidate on clarity, "
        f"pronounceability, memorability, and uniqueness to surface names "
        f"that are practical for real-world branding.[/{C_GRAY}]",
        (0, 4),
    ))
    console.print()

    # ── Core Pillars ──────────────────────────────────────────────────────────
    subsection("Core Pillars")
    pillars = [
        (C_GREEN,  "Generate",  "Keyword expansion · synonym mapping · pattern generation"),
        (C_PURPLE, "Analyze",   "Phonetic scoring · memorability · brand strength tiers"),
        (C_TEAL,   "Validate",  "Trademark conflicts · phonetic quality · collision detection"),
        (C_GOLD,   "Discover",  "Domain intelligence · TLD ranking · platform availability"),
    ]
    for colour, label, detail in pillars:
        console.print(
            f"   [{colour}]◆[/{colour}]  "
            f"[bold {C_WHITE}]{label:<12}[/bold {C_WHITE}]  "
            f"[dim {C_GRAY}]{detail}[/dim {C_GRAY}]"
        )

    console.print()

    # ── Dataset summary ───────────────────────────────────────────────────────
    subsection("Knowledge Layer")
    datasets = [
        ("common_words.txt",     "1,229 words",    "Generic word filter"),
        ("synonyms.txt",          "2,512 synonyms", "Semantic expansion engine"),
        ("tech_terms.txt",        "302 terms",      "Technology vocabulary"),
        ("ai_terms.txt",          "150 terms",      "AI / ML vocabulary"),
        ("business_terms.txt",    "226 terms",      "Business vocabulary"),
        ("domain_prefixes.txt",   "62 prefixes",    "Domain variation prefixes"),
        ("domain_suffixes.txt",   "129 suffixes",   "Domain variation suffixes"),
        ("tlds.txt",              "40 TLDs",        "TLD rank list"),
    ]
    ds_t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        expand=False,
    )
    ds_t.add_column(style=f"dim {C_TEAL}",   width=26)
    ds_t.add_column(style=f"{C_WHITE}",       width=16)
    ds_t.add_column(style=f"dim {C_GRAY}",    width=36)
    for fname, size, desc in datasets:
        ds_t.add_row(fname, size, desc)
    console.print(Padding(ds_t, (0, 4)))
    console.print()

    # ── Disclaimer ────────────────────────────────────────────────────────────
    console.print(Padding(
        Panel(
            f"[dim {C_GRAY}]{DISCLAIMER}[/dim {C_GRAY}]",
            border_style=f"dim {C_GRAY}",
            padding=(0, 2),
        ),
        (0, 4),
    ))
    console.print()
    _render_slogan(animated=False)


# ─────────────────────────────────────────────────────────────────────────────
# § 8  STATUS & INLINE MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

def msg_ok(text: str) -> None:
    """Green tick — success confirmation."""
    console.print(
        f"   [bold {C_GREEN}]✔[/bold {C_GREEN}]  [{C_WHITE}]{escape(text)}[/{C_WHITE}]"
    )


def msg_fail(text: str) -> None:
    """Red cross — error message."""
    console.print(
        f"   [bold {C_RED}]✘[/bold {C_RED}]  [{C_WHITE}]{escape(text)}[/{C_WHITE}]"
    )


def msg_warn(text: str) -> None:
    """Amber triangle — warning."""
    console.print(
        f"   [bold {C_AMBER}]⚠[/bold {C_AMBER}]  [{C_WHITE}]{escape(text)}[/{C_WHITE}]"
    )


def msg_info(text: str) -> None:
    """Blue circle — informational note."""
    console.print(
        f"   [{C_BLUE}]ℹ[/{C_BLUE}]  [{C_GRAY}]{escape(text)}[/{C_GRAY}]"
    )


def msg_step(step: int, total: int, text: str) -> None:
    """Numbered workflow step indicator."""
    console.print(
        f"   [{C_GRAY}][{step}/{total}][/{C_GRAY}]  "
        f"[{C_WHITE}]{escape(text)}[/{C_WHITE}]"
    )


def msg_result(label: str, value: str, colour: str = C_WHITE) -> None:
    """Key-value result line."""
    console.print(
        f"   [{C_GRAY}]{escape(label):<20}[/{C_GRAY}]  "
        f"[bold {colour}]{escape(value)}[/bold {colour}]"
    )


def print_hint(text: str) -> None:
    """Dimmed hint text indented below the previous message."""
    console.print(f"   [dim {C_GRAY}]↳ {escape(text)}[/dim {C_GRAY}]")


def print_panel(
    content:  str,
    title:    str   = "",
    colour:   str   = C_ACCENT,
    pad:      tuple = (1, 2),
) -> None:
    """Render content inside a styled Rich panel."""
    title_mu = (
        f"[bold {colour}] {escape(title)} [/bold {colour}]"
        if title else None
    )
    console.print(
        Panel(
            content,
            title=title_mu,
            border_style=f"bold {colour}",
            padding=pad,
        )
    )


def print_empty_state(context: str = "results") -> None:
    """Styled empty-state message when no data is available."""
    console.print()
    console.print(
        Align.center(
            Panel(
                f"[{C_GRAY}]No {context} to display yet.\n"
                f"Run an operation from the main menu to get started.[/{C_GRAY}]",
                border_style=f"dim {C_GRAY}",
                padding=(1, 4),
                width=52,
            )
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 9  UPDATE NOTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def print_update_available(latest: str) -> None:
    """
    Render a prominent but non-blocking update notification.

    Called at startup when a newer GitHub release is detected.
    The user can dismiss and continue — update is never forced.
    """
    console.print()
    console.print(
        Panel(
            f"   [{C_GOLD}]✦  A new version of NEXAGEN is available![/{C_GOLD}]\n\n"
            f"   [{C_GRAY}]Current :[/{C_GRAY}]  [{C_WHITE}]{VERSION_TAG}[/{C_WHITE}]\n"
            f"   [{C_GRAY}]Latest  :[/{C_GRAY}]  [{C_GREEN}]v{escape(latest)}[/{C_GREEN}]\n\n"
            f"   [{C_GRAY}]Upgrade :[/{C_GRAY}]  "
            f"[bold {C_ACCENT}]pip install --upgrade nexagen[/bold {C_ACCENT}]\n"
            f"   [{C_GRAY}]Releases:[/{C_GRAY}]  "
            f"[dim {C_GRAY}]{TOOL_REPO}/releases[/dim {C_GRAY}]",
            border_style=f"bold {C_GOLD}",
            title=f"[bold {C_GOLD}] ✦ Update Available [/bold {C_GOLD}]",
            padding=(0, 2),
        )
    )
    console.print()


def print_checking_update() -> None:
    """One-line status shown while the update check network call runs."""
    console.print(
        f"   [{C_BLUE}]↻[/{C_BLUE}]  "
        f"[dim {C_GRAY}]Checking for updates...[/dim {C_GRAY}]",
        end="\r",
    )


def print_up_to_date() -> None:
    """Brief confirmation that the current version is the latest."""
    console.print(
        f"   [{C_GREEN}]✔[/{C_GREEN}]  "
        f"[dim {C_GRAY}]NEXAGEN {VERSION_TAG} — up to date.[/dim {C_GRAY}]"
    )


def print_update_check_skipped() -> None:
    """Shown when update check is disabled in settings."""
    console.print(
        f"   [{C_GRAY}]—[/{C_GRAY}]  "
        f"[dim {C_GRAY}]Update check disabled.[/dim {C_GRAY}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 10  STARTUP HEADER  (after banner, before menu)
# ─────────────────────────────────────────────────────────────────────────────

def print_ready(profile: str = "generic", style: str = "minimal") -> None:
    """
    Short "ready" line displayed after the update check completes
    and just before the main menu renders.
    """
    console.print(
        f"   [{C_GREEN}]●[/{C_GREEN}]  "
        f"[{C_GRAY}]Profile: "
        f"[bold {C_ACCENT}]{profile}[/bold {C_ACCENT}]  ·  "
        f"Style: [bold {C_ACCENT}]{style}[/bold {C_ACCENT}][/{C_GRAY}]"
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 11  SESSION FOOTER & GOODBYE
# ─────────────────────────────────────────────────────────────────────────────

def print_session_footer(
    names_generated: int   = 0,
    checks_run:      int   = 0,
    exports:         int   = 0,
    elapsed:         float = 0.0,
) -> None:
    """
    End-of-session statistics strip rendered on clean exit.

    Shows: version, author, names count, checks count, elapsed time.
    """
    console.print()
    console.print(Rule(style=f"dim {C_GRAY}"))
    stats = (
        f"NEXAGEN {VERSION_TAG}  ·  {TOOL_AUTHOR}  ·  "
        f"{names_generated} names  ·  "
        f"{checks_run} checks  ·  "
        f"{exports} exports  ·  "
        f"{elapsed:.1f}s"
    )
    console.print(Align.center(f"[dim {C_GRAY}]{stats}[/dim {C_GRAY}]"))
    console.print(Align.center(f"[dim {C_GRAY}]{SLOGAN}[/dim {C_GRAY}]"))
    console.print()


def print_goodbye() -> None:
    """Clean exit farewell — displayed after menu option 6 (Exit)."""
    console.print()
    console.print(
        Align.center(
            f"[bold {C_BANNER}]Thank you for using NEXAGEN[/bold {C_BANNER}]"
        )
    )
    console.print(
        Align.center(
            f"[dim {C_GRAY}]{TOOL_ECOSYSTEM}  ·  {TOOL_REPO}[/dim {C_GRAY}]"
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 12  KEYBOARD INTERRUPT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def print_interrupted() -> None:
    """Clean Ctrl+C / KeyboardInterrupt handler message."""
    console.print()
    console.print()
    msg_warn("Interrupted by user (Ctrl+C).")
    print_goodbye()
