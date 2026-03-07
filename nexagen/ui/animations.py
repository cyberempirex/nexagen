"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  ui/animations.py  ·  Spinners, scanners, typewriter, pulse effects         ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

All animations are context-manager-friendly and thread-safe.
Every animation class runs its own daemon thread so the main thread
remains unblocked — critical for async domain checks and generation.

Public API
──────────
  Spinner(label)                    — classic rotating spinner
  DotsSpinner(label)                — dot-pulse spinner
  ScanBeam(label, width)            — left-right beam scan (domain checks)
  PulseBar(label)                   — pulsing block bar
  TypewriterLine(text, colour)      — print text character-by-character
  CountUp(label, target, duration)  — animated number count-up
  BootSequence()                    — multi-step startup checklist
  live_spinner(label)               — context manager helper
  live_scan(label)                  — context manager helper
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator, Iterator, Optional

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.text import Text

from ..config.constants import (
    ANIM_CHAR_TYPEWRITER,
    ANIM_SPINNER_SPEED,
    C_ACCENT,
    C_AMBER,
    C_BANNER,
    C_BLUE,
    C_DARK,
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  FRAME SETS
# ─────────────────────────────────────────────────────────────────────────────

class Frames:
    """Collections of animation frame sequences."""

    # Classic spinner variants
    BRAILLE:   tuple[str, ...] = ("⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏")
    DOTS:      tuple[str, ...] = ("⣾","⣽","⣻","⢿","⡿","⣟","⣯","⣷")
    CLOCK:     tuple[str, ...] = ("🕛","🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚")
    ARROW:     tuple[str, ...] = ("←","↖","↑","↗","→","↘","↓","↙")
    BAR_SPIN:  tuple[str, ...] = ("|","\\","-","/")
    TRIANGLE:  tuple[str, ...] = ("◢","◣","◤","◥")
    BOUNCE:    tuple[str, ...] = ("⠁","⠂","⠄","⡀","⢀","⠠","⠐","⠈")

    # Dots pulse (3-stage)
    DOTS_PULSE: tuple[str, ...] = (
        "·  ", "·· ", "···", " ··", "  ·", "   ",
    )

    # Scan beam (injected at runtime based on width)
    @staticmethod
    def scan_beam(width: int = 20) -> tuple[str, ...]:
        """Generate a left-to-right beam scan animation of given width."""
        beam = "▓▒░"
        frames: list[str] = []
        for i in range(width + len(beam)):
            row = [" "] * width
            for j, ch in enumerate(beam):
                pos = i - j
                if 0 <= pos < width:
                    row[pos] = ch
            frames.append("".join(row))
        return tuple(frames)

    # Vertical pulse bar
    VBAR: tuple[str, ...] = ("▁","▂","▃","▄","▅","▆","▇","█","▇","▆","▅","▄","▃","▂")

    # Horizontal block fill
    HBLOCK: tuple[str, ...] = (" ","▏","▎","▍","▌","▋","▊","▉","█")

    # Heartbeat
    HEARTBEAT: tuple[str, ...] = (
        "♡  ","♡♡ ","♡♡♡","♡♡♡","♡♡ ","♡  ","   ",
    )

    # Cyber / glitch
    GLITCH: tuple[str, ...] = (
        "▓▒░ ","░▓▒ "," ░▓▒","▒ ░▓","▓▒░ ","    ",
    )

    # Check mark appearance
    CHECK_BUILD: tuple[str, ...] = (
        " ","╸","╾","╼","━","╺","▸","►","✓","✔",
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 2  BASE ANIMATION CLASS
# ─────────────────────────────────────────────────────────────────────────────

class _Animation:
    """
    Base class for all live animations.

    Subclasses must implement ``_build_frame(frame_char: str) -> Text``.
    Each animation spawns a background thread. Use as a context manager:

        with Spinner("Generating names...") as s:
            do_work()
            s.update("Still working...")
        # → prints final done message on exit
    """

    def __init__(
        self,
        label:       str,
        frames:      tuple[str, ...] = Frames.BRAILLE,
        speed:       float           = ANIM_SPINNER_SPEED,
        colour:      str             = C_ACCENT,
        done_icon:   str             = "✔",
        done_colour: str             = C_GREEN,
        fail_icon:   str             = "✘",
        fail_colour: str             = C_RED,
    ) -> None:
        self.label        = label
        self.frames       = frames
        self.speed        = speed
        self.colour       = colour
        self.done_icon    = done_icon
        self.done_colour  = done_colour
        self.fail_icon    = fail_icon
        self.fail_colour  = fail_colour
        self._console     = Console(highlight=False, markup=True)
        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._live: Optional[Live] = None
        self._success     = True

    def update(self, label: str) -> None:
        """Change the label text while the animation is running."""
        self.label = label

    def _build_renderable(self, frame: str) -> Text:
        """Build a Rich Text object for one animation frame. Override in subclass."""
        t = Text()
        t.append(f" {frame} ", style=f"bold {self.colour}")
        t.append(self.label, style=C_WHITE)
        return t

    def _run(self) -> None:
        """Background thread loop."""
        for frame in itertools.cycle(self.frames):
            if self._stop_event.is_set():
                break
            if self._live is not None:
                self._live.update(self._build_renderable(frame))
            time.sleep(self.speed)

    def __enter__(self) -> "_Animation":
        self._live = Live(
            self._build_renderable(self.frames[0]),
            console=self._console,
            refresh_per_second=int(1 / self.speed) + 2,
            transient=True,
        )
        self._live.__enter__()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        if self._live:
            self._live.__exit__(exc_type, exc_val, exc_tb)
        # Print final status line
        if exc_type is None:
            icon, col = self.done_icon, self.done_colour
        else:
            icon, col  = self.fail_icon, self.fail_colour
        self._console.print(
            f"   [bold {col}]{icon}[/bold {col}]  [{C_WHITE}]{escape(self.label)}[/{C_WHITE}]"
        )
        return False  # do not suppress exceptions


# ─────────────────────────────────────────────────────────────────────────────
# § 3  SPINNER VARIANTS
# ─────────────────────────────────────────────────────────────────────────────

class Spinner(_Animation):
    """
    Classic braille-dot spinner.

    Usage::

        with Spinner("Generating brand names...") as sp:
            names = engine.generate(keywords)
            sp.update(f"Generated {len(names)} candidates")
    """
    def __init__(self, label: str, colour: str = C_ACCENT) -> None:
        super().__init__(label, frames=Frames.BRAILLE, colour=colour)


class DotsSpinner(_Animation):
    """
    Three-dot pulsing spinner — softer than Braille, good for short waits.
    """
    def __init__(self, label: str, colour: str = C_TEAL) -> None:
        super().__init__(
            label,
            frames=Frames.DOTS_PULSE,
            speed=0.18,
            colour=colour,
        )

    def _build_renderable(self, frame: str) -> Text:
        t = Text()
        t.append(f"   {frame}  ", style=f"{self.colour}")
        t.append(self.label, style=C_GRAY)
        return t


class CyberSpinner(_Animation):
    """
    Glitch-style spinner — used during AI analysis / advanced operations.
    """
    def __init__(self, label: str) -> None:
        super().__init__(
            label,
            frames=Frames.GLITCH,
            speed=0.09,
            colour=C_PURPLE,
        )

    def _build_renderable(self, frame: str) -> Text:
        t = Text()
        t.append(f" [{frame}] ", style=f"bold {C_PURPLE}")
        t.append(self.label, style=C_WHITE)
        return t


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SCAN BEAM  (domain / platform availability checks)
# ─────────────────────────────────────────────────────────────────────────────

class ScanBeam(_Animation):
    """
    Horizontal beam scan — visually represents scanning for domain availability.

    Layout per frame::

      [▓▒░              ] Checking paperdesk.com ...
    """

    def __init__(
        self,
        label:  str,
        width:  int = 22,
        colour: str = C_TEAL,
    ) -> None:
        super().__init__(
            label,
            frames=Frames.scan_beam(width),
            speed=0.045,
            colour=colour,
            done_icon="✔",
        )
        self._width = width

    def _build_renderable(self, frame: str) -> Text:
        t = Text()
        t.append("  [", style=f"dim {C_GRAY}")
        t.append(frame, style=f"bold {self.colour}")
        t.append("] ", style=f"dim {C_GRAY}")
        t.append(self.label, style=C_WHITE)
        return t


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PULSE BAR
# ─────────────────────────────────────────────────────────────────────────────

class PulseBar(_Animation):
    """
    Vertical-block pulse bar — used during scoring / analysis operations.

    Layout per frame::

      ▁▂▃▄▅▆▇█▇▆  Scoring brand strength...
    """

    _BAR_WIDTH = 10

    def __init__(self, label: str, colour: str = C_PURPLE) -> None:
        super().__init__(
            label,
            frames=Frames.VBAR,
            speed=0.07,
            colour=colour,
        )
        self._pos = 0

    def _build_renderable(self, frame: str) -> Text:
        # Build a ripple bar that peaks at a travelling position
        bar = ""
        for i in range(self._BAR_WIDTH):
            idx = (self._pos + i) % len(Frames.VBAR)
            bar += Frames.VBAR[idx]
        self._pos = (self._pos + 1) % len(Frames.VBAR)
        t = Text()
        t.append(f"  {bar}  ", style=f"bold {self.colour}")
        t.append(self.label, style=C_WHITE)
        return t


# ─────────────────────────────────────────────────────────────────────────────
# § 6  TYPEWRITER EFFECTS
# ─────────────────────────────────────────────────────────────────────────────

def typewriter(
    text:   str,
    colour: str   = C_WHITE,
    speed:  float = ANIM_CHAR_TYPEWRITER,
    prefix: str   = "   ",
    newline: bool = True,
) -> None:
    """
    Print text character by character with a typewriter effect.

    Args:
        text:    The string to type.
        colour:  Rich colour for the text.
        speed:   Seconds between characters.
        prefix:  Leading whitespace / prefix string.
        newline: Whether to end with a newline.
    """
    _con = Console(highlight=False, markup=False)
    typed = ""
    for char in text:
        typed += char
        _con.print(
            f"{prefix}[{colour}]{escape(typed)}[/{colour}]",
            end="\r",
            markup=True,
        )
        time.sleep(speed)
    if newline:
        _con.print(
            f"{prefix}[{colour}]{escape(typed)}[/{colour}]",
            markup=True,
        )


def typewriter_panel(
    lines:  list[str],
    colour: str   = C_WHITE,
    speed:  float = ANIM_CHAR_TYPEWRITER * 0.6,
) -> None:
    """
    Type multiple lines one by one. Each line completes before the next starts.
    """
    for line in lines:
        typewriter(line, colour=colour, speed=speed)
        time.sleep(0.08)


# ─────────────────────────────────────────────────────────────────────────────
# § 7  COUNT-UP ANIMATION
# ─────────────────────────────────────────────────────────────────────────────

def count_up(
    label:    str,
    target:   int,
    duration: float = 1.0,
    colour:   str   = C_GOLD,
    unit:     str   = "",
) -> None:
    """
    Animate a number counting up from 0 to target over duration seconds.

    Usage::

        count_up("Names generated", 127, duration=1.2, unit=" names")
    """
    _con    = Console(highlight=False, markup=True)
    steps   = max(20, min(target, 60))
    delay   = duration / steps
    step_sz = max(1, target // steps)

    current = 0
    while current < target:
        current = min(current + step_sz, target)
        _con.print(
            f"   [{C_GRAY}]{escape(label)}:[/{C_GRAY}]  "
            f"[bold {colour}]{current}{escape(unit)}[/bold {colour}]",
            end="\r",
        )
        time.sleep(delay)

    _con.print(
        f"   [{C_GRAY}]{escape(label)}:[/{C_GRAY}]  "
        f"[bold {colour}]{target}{escape(unit)}[/bold {colour}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 8  BOOT SEQUENCE  (startup health checks)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BootStep:
    """A single step in the boot sequence."""
    label:   str
    detail:  str  = ""
    ok:      bool = False
    skipped: bool = False


class BootSequence:
    """
    Animated multi-step startup checklist.

    Renders as a live-updating list of steps with status icons,
    then collapses to a final summary line.

    Usage::

        boot = BootSequence()
        boot.add("Loading datasets",    "common_words, synonyms, tech_terms")
        boot.add("Checking for updates","github.com/cyberempirex/nexagen")
        boot.add("Initialising engine", "keyword + synonym engine ready")
        boot.run(check_fn)   # check_fn(step) → (ok: bool, detail_override: str)
    """

    _CHECK_FRAMES = ("◌","◍","◎","●","◉","◉")

    def __init__(self) -> None:
        self.steps:    list[BootStep] = []
        self._console  = Console(highlight=False, markup=True)

    def add(self, label: str, detail: str = "") -> "BootSequence":
        self.steps.append(BootStep(label=label, detail=detail))
        return self

    def _render(self, active_idx: int, frame: str) -> Text:
        t = Text()
        for i, step in enumerate(self.steps):
            if step.skipped:
                icon = f"[dim {C_GRAY}]—[/dim {C_GRAY}]"
                label_style = f"dim {C_GRAY}"
            elif step.ok:
                icon = f"[bold {C_GREEN}]✔[/bold {C_GREEN}]"
                label_style = C_WHITE
            elif i == active_idx:
                icon = f"[bold {C_ACCENT}]{frame}[/bold {C_ACCENT}]"
                label_style = C_ACCENT
            else:
                icon = f"[dim {C_GRAY}]○[/dim {C_GRAY}]"
                label_style = f"dim {C_GRAY}"

            t.append(f"   ")
            t.append_text(Text.from_markup(icon))
            t.append(f"  ", style="")
            t.append(step.label, style=label_style)
            if step.detail and (step.ok or i == active_idx):
                t.append(f"  ", style="")
                t.append(step.detail, style=f"dim {C_GRAY}")
            t.append("\n")
        return t

    def run(
        self,
        check_fn,  # Callable[[BootStep], tuple[bool, str]] or None
        *,
        speed: float = 0.06,
    ) -> bool:
        """
        Execute all steps calling check_fn(step) for each.

        Args:
            check_fn: Called with each BootStep; returns (ok, detail_override).
                      Pass None to auto-pass all steps (e.g. for demo).
            speed:    Frame rate for the spinner.

        Returns:
            True if all steps passed, False if any failed.
        """
        self._console.print()
        frame_iter = itertools.cycle(self._CHECK_FRAMES)
        all_ok     = True

        with Live(
            self._render(-1, "○"),
            console=self._console,
            refresh_per_second=20,
            transient=False,
        ) as live:
            for idx, step in enumerate(self.steps):
                for _ in range(8):          # animate a few frames per step
                    live.update(self._render(idx, next(frame_iter)))
                    time.sleep(speed)

                if check_fn is not None:
                    try:
                        ok, detail = check_fn(step)
                    except Exception:
                        ok, detail = False, "error"
                else:
                    ok, detail = True, step.detail

                if detail:
                    step.detail = detail
                step.ok = ok
                if not ok:
                    all_ok = False

                live.update(self._render(idx, "✔" if ok else "✘"))
                time.sleep(0.05)

        return all_ok


# ─────────────────────────────────────────────────────────────────────────────
# § 9  CONTEXT MANAGER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def live_spinner(
    label:        str,
    colour:       str = C_ACCENT,
    done_message: Optional[str] = None,
) -> Generator[Spinner, None, None]:
    """
    Context manager wrapping ``Spinner``.

    Usage::

        with live_spinner("Expanding synonyms") as sp:
            result = synonym_engine.expand(keywords)
            sp.update(f"Expanded to {len(result)} words")
    """
    with Spinner(label, colour=colour) as sp:
        yield sp
    if done_message:
        Console(highlight=False, markup=True).print(
            f"   [bold {C_GREEN}]✔[/bold {C_GREEN}]  [{C_WHITE}]{escape(done_message)}[/{C_WHITE}]"
        )


@contextmanager
def live_scan(
    label:  str,
    colour: str = C_TEAL,
) -> Generator[ScanBeam, None, None]:
    """
    Context manager wrapping ``ScanBeam``.

    Usage::

        with live_scan("Checking getpaperdesk.com") as scan:
            result = check_domain("getpaperdesk.com")
            scan.update("paperdesk.io")
    """
    with ScanBeam(label, colour=colour) as scan:
        yield scan


@contextmanager
def live_pulse(label: str) -> Generator[PulseBar, None, None]:
    """Context manager wrapping ``PulseBar`` for analysis operations."""
    with PulseBar(label) as bar:
        yield bar


# ─────────────────────────────────────────────────────────────────────────────
# § 10  FLASH MESSAGES  (single-frame visual confirmations)
# ─────────────────────────────────────────────────────────────────────────────

def flash_success(message: str) -> None:
    """
    Briefly flash a green success confirmation then clear to a static line.
    """
    _con = Console(highlight=False, markup=True)
    icons = ["·", "◦", "○", "◎", "●", "✔"]
    for icon in icons:
        _con.print(
            f"   [bold {C_GREEN}]{icon}[/bold {C_GREEN}]  "
            f"[{C_WHITE}]{escape(message)}[/{C_WHITE}]",
            end="\r",
        )
        time.sleep(0.05)
    _con.print(
        f"   [bold {C_GREEN}]✔[/bold {C_GREEN}]  "
        f"[bold {C_WHITE}]{escape(message)}[/bold {C_WHITE}]"
    )


def flash_check(name: str, status: str, colour: str) -> None:
    """
    Animate a check-mark building up for a domain/platform result.

    Args:
        name:   The domain or handle that was checked.
        status: Status string e.g. "FREE", "TAKEN", "UNKNOWN".
        colour: Rich colour for the status text.
    """
    _con = Console(highlight=False, markup=True)
    for ch in Frames.CHECK_BUILD:
        _con.print(
            f"   [{C_GRAY}]{ch}[/{C_GRAY}]  "
            f"[{C_WHITE}]{escape(name)}[/{C_WHITE}]",
            end="\r",
        )
        time.sleep(0.04)
    _con.print(
        f"   [bold {colour}]✔[/bold {colour}]  "
        f"[{C_WHITE}]{escape(name)}[/{C_WHITE}]  "
        f"[bold {colour}]{escape(status)}[/bold {colour}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 11  NAME REVEAL ANIMATION
# ─────────────────────────────────────────────────────────────────────────────

def reveal_names(
    names:   list[str],
    scores:  Optional[list[int]] = None,
    colours: Optional[list[str]] = None,
    delay:   float = 0.12,
) -> None:
    """
    Reveal generated brand names one by one with a fade-in effect.

    Each name appears after a short delay with its score (if provided).
    Used at the end of the generation phase before the results table.

    Args:
        names:   List of brand name strings.
        scores:  Optional parallel list of integer scores (0–100).
        colours: Optional parallel list of Rich colour strings.
        delay:   Seconds between each name reveal.
    """
    _con      = Console(highlight=False, markup=True)
    _scores   = scores   or []
    _colours  = colours  or []
    pad       = max(len(n) for n in names) if names else 12

    _con.print()
    for i, name in enumerate(names):
        score  = _scores[i]  if i < len(_scores)  else None
        colour = _colours[i] if i < len(_colours) else C_ACCENT

        score_str = (
            f"  [{C_GRAY}]score: [bold {colour}]{score}[/bold {colour}][/{C_GRAY}]"
            if score is not None else ""
        )

        # Fade in: dim → normal → bold
        for sty in (f"dim {colour}", colour, f"bold {colour}"):
            _con.print(
                f"   [{sty}]{escape(name):<{pad}}[/{sty}]{score_str}",
                end="\r",
            )
            time.sleep(delay * 0.25)

        _con.print(
            f"   [bold {colour}]{escape(name):<{pad}}[/bold {colour}]{score_str}"
        )
        time.sleep(delay * 0.5)

    _con.print()
