"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  ui/theme.py  ·  Rich Theme system + colour palette management             ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Rich Theme system and colour palette management for NEXAGEN.

Centralises every colour and style decision so the UI modules (banner, tables,
animations, progress) never hard-code palette values.  All UI code that needs
a colour should call :func:`colour` or use a named style via the shared
:data:`console` instance.

Themes available
─────────────────
  cyberpunk  (default) — high-contrast neon on dark; hex constants from
             ``config.constants`` (C_BANNER, C_ACCENT, C_GREEN, …)
  light      — muted, softer tones suitable for light-background terminals
  mono       — greyscale-only, no colour; safe for CI/CD pipelines and
             accessibility tools

All three themes expose the same semantic role names so consumer code
can stay theme-agnostic:

  banner  — logo / heading colour (bold)
  accent  — primary accent (borders, section headings)
  success — positive / available
  warn    — warning / caution
  danger  — error / taken / high risk
  muted   — dimmed text / hints / labels
  label   — bold secondary text
  gold    — premium / top-tier highlight
  pink    — creative / soft mode accent
  teal    — domain / network accent
  purple  — AI / analysis accent
  blue    — info / progress
  dark    — panel background (used in style strings, not as foreground)

Public API
──────────
  get_theme(name)         → rich.theme.Theme
  get_console(name)       → rich.console.Console   (markup=True, highlight=False)
  colour(role, theme)     → str   hex colour or colour name for that role
  apply_theme(cfg)        → None  set module-level active theme from Settings
  active_theme_name()     → str   currently active theme name
  ThemePalette            — dataclass: one colour per semantic role
  THEMES                  — dict[str, ThemePalette]  all built-in palettes

Shared console
──────────────
  All NEXAGEN UI modules should import ``console`` from this module:

      from nexagen.ui.theme import console

  That single Console instance respects the active theme.  To switch theme at
  runtime (e.g. when Settings.color_theme changes), call :func:`apply_theme`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.theme import Theme

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
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  SEMANTIC ROLE NAMES
# ─────────────────────────────────────────────────────────────────────────────

#: All valid semantic role names — used as keys in ThemePalette and Theme dicts.
ROLE_NAMES: tuple[str, ...] = (
    "banner",
    "accent",
    "success",
    "warn",
    "danger",
    "muted",
    "label",
    "gold",
    "pink",
    "teal",
    "purple",
    "blue",
    "dark",
)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  PALETTE DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ThemePalette:
    """
    Immutable mapping of semantic roles to hex colour strings.

    All fields correspond to entries in :data:`ROLE_NAMES`.

    Attributes:
        banner:  Logo / H1 heading colour.
        accent:  Primary accent — borders, section headings.
        success: Positive outcome / available status.
        warn:    Warning / caution / medium risk.
        danger:  Error / taken / high risk.
        muted:   Dimmed text, hints, labels.
        label:   Bold secondary text.
        gold:    Premium / top tier.
        pink:    Creative / soft mode.
        teal:    Domain / network accent.
        purple:  AI / analysis accent.
        blue:    Info / progress.
        dark:    Panel background (used in style strings).
        name:    Human-readable theme name.
    """
    banner:  str
    accent:  str
    success: str
    warn:    str
    danger:  str
    muted:   str
    label:   str
    gold:    str
    pink:    str
    teal:    str
    purple:  str
    blue:    str
    dark:    str
    name:    str = "unnamed"

    def colour(self, role: str) -> str:
        """
        Return the hex colour for a semantic role.

        Args:
            role: One of the :data:`ROLE_NAMES` strings.

        Returns:
            Hex colour string.  Falls back to the ``label`` colour for
            unknown roles.
        """
        return getattr(self, role, self.label)

    def to_rich_theme(self) -> Theme:
        """
        Convert this palette to a :class:`rich.theme.Theme` object.

        The Rich Theme maps each role name to a ``bold {colour}`` style so
        ``[accent]some text[/accent]`` works in Rich markup.  The ``muted``
        and ``dark`` roles are dimmed / non-bold.

        Returns:
            :class:`rich.theme.Theme`
        """
        non_bold = {"muted", "dark"}
        styles: dict[str, str] = {}
        for role in ROLE_NAMES:
            col = self.colour(role)
            styles[role] = f"dim {col}" if role in non_bold else f"bold {col}"
        return Theme(styles)

    def score_colour(self, score: int) -> str:
        """
        Return a colour appropriate for a composite brand score.

        Threshold bands match the SCORE_* constants in config.constants.

        Args:
            score: Integer 0–100.

        Returns:
            Hex colour string.
        """
        if score >= 90:
            return self.gold
        if score >= 75:
            return self.success
        if score >= 60:
            return self.accent
        if score >= 40:
            return self.warn
        return self.danger

    def tier_colour(self, tier: str) -> str:
        """
        Return a colour for a BrandTier value string.

        Args:
            tier: ``"PREMIUM"`` | ``"STRONG"`` | ``"DECENT"`` | ``"WEAK"`` | ``"POOR"``

        Returns:
            Hex colour string.
        """
        mapping = {
            "PREMIUM": self.gold,
            "STRONG":  self.success,
            "DECENT":  self.accent,
            "WEAK":    self.warn,
            "POOR":    self.danger,
        }
        return mapping.get(tier.upper(), self.label)

    def avail_colour(self, status: str) -> str:
        """
        Return a colour for a domain / platform availability status.

        Args:
            status: ``"free"`` | ``"taken"`` | ``"unknown"`` | ``"skip"``

        Returns:
            Hex colour string.
        """
        mapping = {
            "free":    self.success,
            "taken":   self.danger,
            "unknown": self.muted,
            "skip":    self.muted,
        }
        return mapping.get(status.lower(), self.muted)

    def tm_risk_colour(self, risk: str) -> str:
        """
        Return a colour for a trademark risk level.

        Args:
            risk: ``"none"`` | ``"low"`` | ``"medium"`` | ``"high"``

        Returns:
            Hex colour string.
        """
        mapping = {
            "none":   self.success,
            "low":    self.teal,
            "medium": self.warn,
            "high":   self.danger,
        }
        return mapping.get(risk.lower(), self.muted)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  BUILT-IN PALETTES
# ─────────────────────────────────────────────────────────────────────────────

#: Default high-contrast neon-cyberpunk palette — matches constants.py hex values.
CYBERPUNK = ThemePalette(
    name    = "cyberpunk",
    banner  = C_BANNER,     # "#9b59b6"  vivid purple
    accent  = C_ACCENT,     # "#00d2d3"  bright cyan
    success = C_GREEN,      # "#2ecc71"  emerald green
    warn    = C_AMBER,      # "#f39c12"  amber
    danger  = C_RED,        # "#e74c3c"  crimson
    muted   = C_GRAY,       # "#7f8c8d"  medium grey
    label   = C_WHITE,      # "#f0f0f0"  near-white
    gold    = C_GOLD,       # "#f1c40f"  gold
    pink    = C_PINK,       # "#fd79a8"  soft pink
    teal    = C_TEAL,       # "#1abc9c"  teal
    purple  = C_PURPLE,     # "#6c5ce7"  indigo-purple
    blue    = C_BLUE,       # "#3498db"  sky blue
    dark    = C_DARK,       # "#2c3e50"  dark blue-grey
)

#: Softer palette for light-background terminals.
LIGHT = ThemePalette(
    name    = "light",
    banner  = "#7d3c98",    # deeper purple
    accent  = "#0e6655",    # dark teal
    success = "#1e8449",    # dark green
    warn    = "#b7770d",    # burnt amber
    danger  = "#a93226",    # dark red
    muted   = "#626567",    # cool grey
    label   = "#1c2833",    # near-black
    gold    = "#9a7d0a",    # dark gold
    pink    = "#c0392b",    # muted rose
    teal    = "#148f77",    # dark teal
    purple  = "#4a235a",    # deep purple
    blue    = "#1a5276",    # dark blue
    dark    = "#eaf2ff",    # very light blue-grey (used as panel bg)
)

#: Greyscale-only palette — no colour, safe for CI and accessibility tools.
MONO = ThemePalette(
    name    = "mono",
    banner  = "#e0e0e0",
    accent  = "#c0c0c0",
    success = "#e0e0e0",
    warn    = "#a0a0a0",
    danger  = "#808080",
    muted   = "#606060",
    label   = "#e0e0e0",
    gold    = "#e0e0e0",
    pink    = "#c0c0c0",
    teal    = "#c0c0c0",
    purple  = "#a0a0a0",
    blue    = "#c0c0c0",
    dark    = "#202020",
)

#: Registry of all built-in palettes indexed by name.
THEMES: dict[str, ThemePalette] = {
    "cyberpunk": CYBERPUNK,
    "light":     LIGHT,
    "mono":      MONO,
}

# ─────────────────────────────────────────────────────────────────────────────
# § 4  ACTIVE THEME STATE
# ─────────────────────────────────────────────────────────────────────────────

# Module-level active theme — updated by apply_theme()
_active_name:    str          = "cyberpunk"
_active_palette: ThemePalette = CYBERPUNK

#: Shared Rich Console for the entire NEXAGEN UI layer.
#: Import this from all UI modules instead of creating local Console instances.
#: Switch theme by calling :func:`apply_theme`.
console: Console = Console(
    theme     = CYBERPUNK.to_rich_theme(),
    highlight = False,
    markup    = True,
)


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_theme(name: str = "cyberpunk") -> Theme:
    """
    Return a Rich :class:`~rich.theme.Theme` for the named NEXAGEN theme.

    Args:
        name: ``"cyberpunk"`` (default) | ``"light"`` | ``"mono"``

    Returns:
        :class:`rich.theme.Theme`
    """
    palette = THEMES.get(name.lower(), CYBERPUNK)
    return palette.to_rich_theme()


def get_palette(name: str = "cyberpunk") -> ThemePalette:
    """
    Return the :class:`ThemePalette` for *name*.

    Args:
        name: Theme name string.

    Returns:
        :class:`ThemePalette` (falls back to CYBERPUNK for unknown names).
    """
    return THEMES.get(name.lower(), CYBERPUNK)


def get_console(name: str = "cyberpunk") -> Console:
    """
    Return a new :class:`rich.console.Console` configured with the named theme.

    Prefer importing the module-level :data:`console` where possible;
    use this function only when you need an isolated console instance.

    Args:
        name: Theme name string.

    Returns:
        :class:`rich.console.Console`
    """
    return Console(theme=get_theme(name), highlight=False, markup=True)


def colour(role: str, theme: str = "") -> str:
    """
    Return the hex colour for a semantic role in the active (or named) theme.

    Args:
        role:  One of the :data:`ROLE_NAMES` strings.
        theme: Optional theme name to query instead of the active theme.

    Returns:
        Hex colour string.
    """
    palette = THEMES.get(theme.lower(), _active_palette) if theme else _active_palette
    return palette.colour(role)


def score_colour(score: int) -> str:
    """
    Return the active-theme colour appropriate for *score*.

    Args:
        score: Composite brand score 0–100.

    Returns:
        Hex colour string.
    """
    return _active_palette.score_colour(score)


def tier_colour(tier: str) -> str:
    """
    Return the active-theme colour for a BrandTier value.

    Args:
        tier: ``"PREMIUM"`` | ``"STRONG"`` | ``"DECENT"`` | ``"WEAK"`` | ``"POOR"``

    Returns:
        Hex colour string.
    """
    return _active_palette.tier_colour(tier)


def avail_colour(status: str) -> str:
    """
    Return the active-theme colour for a domain / platform availability status.

    Args:
        status: ``"free"`` | ``"taken"`` | ``"unknown"`` | ``"skip"``

    Returns:
        Hex colour string.
    """
    return _active_palette.avail_colour(status)


def tm_risk_colour(risk: str) -> str:
    """
    Return the active-theme colour for a trademark risk level.

    Args:
        risk: ``"none"`` | ``"low"`` | ``"medium"`` | ``"high"``

    Returns:
        Hex colour string.
    """
    return _active_palette.tm_risk_colour(risk)


def apply_theme(cfg_or_name: "str | object") -> None:
    """
    Set the module-level active theme and rebuild the shared :data:`console`.

    Accepts either a theme name string or a :class:`~config.settings.Settings`
    object (reads ``cfg.color_theme``).

    Args:
        cfg_or_name: Theme name string (``"cyberpunk"`` | ``"light"`` | ``"mono"``)
                     OR a Settings object with a ``color_theme`` attribute.

    Example::

        from nexagen.ui.theme import apply_theme
        apply_theme("light")   # switch to light theme

        from nexagen.config.settings import get_settings
        apply_theme(get_settings())   # read from Settings
    """
    global _active_name, _active_palette, console

    # Accept Settings object or plain string
    if isinstance(cfg_or_name, str):
        name = cfg_or_name
    else:
        name = getattr(cfg_or_name, "color_theme", "cyberpunk")

    palette = THEMES.get(name.lower())
    if palette is None:
        log.warning(
            "Unknown theme %r — falling back to 'cyberpunk'. "
            "Valid names: %s",
            name,
            list(THEMES.keys()),
        )
        palette = CYBERPUNK
        name    = "cyberpunk"

    _active_name    = name
    _active_palette = palette

    # Rebuild the module-level console with the new theme
    console = Console(
        theme     = palette.to_rich_theme(),
        highlight = False,
        markup    = True,
    )
    log.debug("NEXAGEN theme set to %r", name)


def active_theme_name() -> str:
    """
    Return the name of the currently active theme.

    Returns:
        ``"cyberpunk"`` | ``"light"`` | ``"mono"``
    """
    return _active_name


def active_palette() -> ThemePalette:
    """
    Return the currently active :class:`ThemePalette`.

    Returns:
        :class:`ThemePalette`
    """
    return _active_palette


def list_themes() -> list[str]:
    """
    Return the names of all available built-in themes.

    Returns:
        Sorted list of theme name strings.
    """
    return sorted(THEMES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# § 6  DISPLAY HELPERS  (thin wrappers used by banner, tables, animations)
# ─────────────────────────────────────────────────────────────────────────────

def score_bar(score: int, width: int = 12) -> str:
    """
    Render a score (0–100) as a Unicode block progress bar.

    Example: ``████████░░░░ 82``

    Args:
        score: Integer score 0–100.
        width: Total bar width in block characters (default 12).

    Returns:
        String with filled/empty blocks and trailing numeric score.
    """
    score  = max(0, min(100, score))
    filled = round(score / 100 * width)
    empty  = width - filled
    return f"{'█' * filled}{'░' * empty} {score}"


def avail_icon(status: str) -> str:
    """Return a single Unicode icon for an availability status."""
    return {"free": "✔", "taken": "✘", "unknown": "?", "skip": "—"}.get(
        status.lower(), "?"
    )


def tier_indicator(tier: str) -> str:
    """Return a Unicode indicator character for a BrandTier value."""
    return {
        "PREMIUM": "◆",
        "STRONG":  "▲",
        "DECENT":  "●",
        "WEAK":    "▼",
        "POOR":    "✕",
    }.get(tier.upper(), "·")


def tier_emoji(tier: str) -> str:
    """Return an emoji for a BrandTier value."""
    return {
        "PREMIUM": "💎",
        "STRONG":  "🟢",
        "DECENT":  "🔵",
        "WEAK":    "🟡",
        "POOR":    "🔴",
    }.get(tier.upper(), "⚪")
