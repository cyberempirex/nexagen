"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  ui/progress.py  ·  Progress bars, step trackers, batch-check progress     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Public API
──────────
  GenerationProgress    — name generation pipeline tracker
  AnalysisProgress      — brand scoring tracker
  DomainCheckProgress   — parallel domain/platform check tracker
  MultiStepProgress     — generic named-step workflow tracker
  SimpleBar             — minimal inline bar for small tasks
  track(iterable, ...)  — wrap any iterable with progress
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Iterable, Iterator, Optional, Sequence

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

from ..config.constants import (
    ANIM_PROGRESS_MIN,
    ANIM_SPINNER_SPEED,
    C_ACCENT,
    C_AMBER,
    C_BANNER,
    C_BLUE, C_DARK,
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
)

_con = Console(highlight=False, markup=True)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  CUSTOM PROGRESS COLUMNS
# ─────────────────────────────────────────────────────────────────────────────

class PercentColumn(ProgressColumn):
    """Render completion as a right-aligned bold percentage."""
    def render(self, task: Task) -> Text:
        pct = task.percentage
        if pct >= 100:
            colour = C_GREEN
        elif pct >= 60:
            colour = C_ACCENT
        else:
            colour = C_AMBER
        return Text(f"{pct:5.1f}%", style=f"bold {colour}")


class RateColumn(ProgressColumn):
    """Render processing rate (items/sec)."""
    def render(self, task: Task) -> Text:
        if task.speed is None or task.speed == 0:
            return Text("  —/s  ", style=f"dim {C_GRAY}")
        rate = task.speed
        return Text(f"{rate:5.1f}/s", style=f"dim {C_GRAY}")


class StatusBadge(ProgressColumn):
    """Show a colour-coded status badge in the right column."""

    def __init__(self, badge_text: str = "", badge_colour: str = C_ACCENT) -> None:
        super().__init__()
        self._text   = badge_text
        self._colour = badge_colour

    def update_badge(self, text: str, colour: str) -> None:
        self._text   = text
        self._colour = colour

    def render(self, task: Task) -> Text:
        if not self._text:
            return Text("")
        return Text(f" {self._text} ", style=f"bold {self._colour}")


class PhaseColumn(ProgressColumn):
    """Render the current phase / label set via task.fields['phase']."""
    def render(self, task: Task) -> Text:
        phase = task.fields.get("phase", "")
        if not phase:
            return Text("")
        return Text(f"[{escape(str(phase))}]", style=f"dim {C_GRAY}")


# ─────────────────────────────────────────────────────────────────────────────
# § 2  GENERATION PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

class GenerationProgress:
    """
    Multi-phase progress tracker for the name generation pipeline.

    Phases:
      1. Keyword expansion
      2. Synonym lookup
      3. Pattern generation
      4. Mutation / blending
      5. Scoring & filtering
      6. Deduplication

    Usage::

        with GenerationProgress(total=200) as gp:
            gp.phase("Expanding keywords", 10)
            for kw in keywords:
                expand(kw)
                gp.advance()
            gp.phase("Scoring candidates", 80)
            ...
    """

    PHASES: list[tuple[str, str]] = [
        ("Expanding keywords",  C_TEAL),
        ("Synonym lookup",      C_ACCENT),
        ("Pattern generation",  C_BLUE),
        ("Mutation & blending", C_PURPLE),
        ("Scoring & filtering", C_GOLD),
        ("Deduplication",       C_GREEN),
    ]

    def __init__(self, total: int = 100, label: str = "Generating names") -> None:
        self.total  = total
        self.label  = label
        self._phase_label = PHASES[0][0] if (PHASES := self.PHASES) else ""
        self._phase_col   = C_ACCENT
        self._prog: Optional[Progress]  = None
        self._task: Optional[TaskID]    = None

    def _make_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(spinner_name="dots", style=f"bold {C_BANNER}"),
            TextColumn(f"[bold {C_WHITE}]{self.label}[/bold {C_WHITE}]"),
            BarColumn(
                bar_width=30,
                style=f"dim {C_DARK}",
                complete_style=C_ACCENT,
                finished_style=C_GREEN,
            ),
            PercentColumn(),
            TextColumn("[dim {C_GRAY}]·[/dim {C_GRAY}]"),
            PhaseColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=_con,
            expand=False,
        )

    def __enter__(self) -> "GenerationProgress":
        self._prog = self._make_progress()
        self._prog.__enter__()
        self._task = self._prog.add_task(
            description=self.label,
            total=self.total,
            phase=self._phase_label,
        )
        return self

    def phase(self, label: str, step_total: Optional[int] = None) -> None:
        """Advance to a new named phase."""
        self._phase_label = label
        if self._prog and self._task is not None:
            self._prog.update(self._task, phase=label)

    def advance(self, amount: int = 1) -> None:
        """Advance the progress bar by amount steps."""
        if self._prog and self._task is not None:
            self._prog.advance(self._task, amount)

    def set(self, completed: int) -> None:
        """Jump to an absolute completion value."""
        if self._prog and self._task is not None:
            self._prog.update(self._task, completed=completed)

    def __exit__(self, *args) -> None:
        if self._prog and self._task is not None:
            self._prog.update(self._task, completed=self.total)
        if self._prog:
            self._prog.__exit__(*args)
        time.sleep(ANIM_PROGRESS_MIN * 0.3)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  ANALYSIS PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisProgress:
    """
    Progress tracker for brand strength analysis.
    Shows one bar per scoring dimension, then a composite summary.

    Usage::

        with AnalysisProgress(name="Paperdesk", n_candidates=50) as ap:
            for name in candidates:
                score = scorer.score(name)
                ap.advance(score)
    """

    DIMENSIONS: list[tuple[str, str]] = [
        ("Phonetic analysis",  C_PURPLE),
        ("Memorability check", C_TEAL),
        ("Uniqueness score",   C_ACCENT),
        ("Length fitness",     C_GOLD),
    ]

    def __init__(self, name: str = "", n_candidates: int = 100) -> None:
        self.name          = name
        self.n_candidates  = n_candidates
        self._prog: Optional[Progress] = None
        self._tasks: dict[str, TaskID] = {}

    def _make_progress(self) -> Progress:
        return Progress(
            TextColumn("{task.description:<26}", style=f"dim {C_WHITE}"),
            BarColumn(
                bar_width=28,
                style=f"dim {C_DARK}",
                complete_style=C_PURPLE,
                finished_style=C_GREEN,
            ),
            PercentColumn(),
            TimeElapsedColumn(),
            console=_con,
            expand=False,
        )

    def __enter__(self) -> "AnalysisProgress":
        header = f"  [{C_BANNER}]Analyzing[/{C_BANNER}]"
        if self.name:
            header += f"  [{C_WHITE}]{escape(self.name)}[/{C_WHITE}]"
        _con.print(header)
        self._prog = self._make_progress()
        self._prog.__enter__()
        for label, colour in self.DIMENSIONS:
            tid = self._prog.add_task(
                description=label,
                total=self.n_candidates,
                complete_style=colour,
            )
            self._tasks[label] = tid
        return self

    def advance(self, dimension: Optional[str] = None, amount: int = 1) -> None:
        """Advance one dimension (or all if dimension is None)."""
        if not self._prog:
            return
        if dimension and dimension in self._tasks:
            self._prog.advance(self._tasks[dimension], amount)
        else:
            for tid in self._tasks.values():
                self._prog.advance(tid, amount)

    def finish_dimension(self, dimension: str) -> None:
        """Mark a specific dimension as 100% complete."""
        if self._prog and dimension in self._tasks:
            self._prog.update(self._tasks[dimension], completed=self.n_candidates)

    def __exit__(self, *args) -> None:
        if self._prog:
            for tid in self._tasks.values():
                self._prog.update(tid, completed=self.n_candidates)
            self._prog.__exit__(*args)


# ─────────────────────────────────────────────────────────────────────────────
# § 4  DOMAIN CHECK PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Stores a completed domain/platform check result for display."""
    target:    str                       # e.g. "paperdesk.com" or "github/paperdesk"
    platform:  str                       # e.g. "domain", "github", "pypi"
    available: bool
    detail:    str = ""

    @property
    def icon(self) -> str:
        return "✔" if self.available else "✘"

    @property
    def colour(self) -> str:
        return C_GREEN if self.available else C_RED

    @property
    def status(self) -> str:
        return "FREE" if self.available else "TAKEN"


class DomainCheckProgress:
    """
    Live progress display for parallel domain and platform availability checks.

    Renders a progress bar + a rolling log of completed checks.

    Usage::

        checks = [("paperdesk.com","domain"), ("paperdesk.io","domain"),
                  ("github/paperdesk","github")]
        with DomainCheckProgress(total=len(checks)) as dcp:
            for target, platform in checks:
                result = checker.check(target, platform)
                dcp.record(CheckResult(target, platform, result.available))
    """

    def __init__(self, total: int, label: str = "Availability checks") -> None:
        self.total    = total
        self.label    = label
        self.results: list[CheckResult] = []
        self._prog: Optional[Progress]  = None
        self._task: Optional[TaskID]    = None
        self._free  = 0
        self._taken = 0

    def _make_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(spinner_name="arc", style=f"bold {C_TEAL}"),
            TextColumn(f"[{C_WHITE}]{self.label}[/{C_WHITE}]"),
            BarColumn(
                bar_width=26,
                style=f"dim {C_DARK}",
                complete_style=C_TEAL,
                finished_style=C_GREEN,
            ),
            MofNCompleteColumn(),
            PercentColumn(),
            RateColumn(),
            TimeElapsedColumn(),
            console=_con,
            expand=False,
        )

    def __enter__(self) -> "DomainCheckProgress":
        self._prog = self._make_progress()
        self._prog.__enter__()
        self._task = self._prog.add_task(self.label, total=self.total)
        return self

    def record(self, result: CheckResult) -> None:
        """
        Record a completed check and update the progress display.
        Also prints the result line below the progress bar.
        """
        self.results.append(result)
        if result.available:
            self._free  += 1
        else:
            self._taken += 1

        if self._prog and self._task is not None:
            self._prog.advance(self._task, 1)
            self._prog.update(
                self._task,
                description=(
                    f"[{C_WHITE}]{self.label}[/{C_WHITE}]  "
                    f"[{C_GREEN}]✔ {self._free}[/{C_GREEN}]  "
                    f"[{C_RED}]✘ {self._taken}[/{C_RED}]"
                ),
            )

        # Inline result line (printed below progress bar)
        _con.print(
            f"   [{result.colour}]{result.icon}[/{result.colour}]  "
            f"[{C_WHITE}]{escape(result.target):<32}[/{C_WHITE}]"
            f"[dim {C_GRAY}]{escape(result.platform):<10}[/dim {C_GRAY}]"
            f"[bold {result.colour}]{result.status}[/bold {result.colour}]"
        )

    def __exit__(self, *args) -> None:
        if self._prog and self._task is not None:
            self._prog.update(self._task, completed=self.total)
        if self._prog:
            self._prog.__exit__(*args)

        # Summary line
        _con.print()
        _con.print(
            f"   [{C_GRAY}]Checks complete:[/{C_GRAY}]  "
            f"[bold {C_GREEN}]{self._free} free[/bold {C_GREEN}]  "
            f"[bold {C_RED}]{self._taken} taken[/bold {C_RED}]  "
            f"[dim {C_GRAY}]{self.total} total[/dim {C_GRAY}]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  MULTI-STEP WORKFLOW PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """A single named step in a workflow."""
    name:    str
    total:   int = 100
    colour:  str = C_ACCENT
    task_id: Optional[TaskID] = None


class MultiStepProgress:
    """
    Stacked progress bars for a named multi-step workflow.

    One bar per step, all visible simultaneously — ideal for the
    startup report which runs several independent analysis passes.

    Usage::

        steps = [
            WorkflowStep("Keyword analysis",   total=50,  colour=C_TEAL),
            WorkflowStep("Name generation",    total=200, colour=C_ACCENT),
            WorkflowStep("Domain checks",      total=30,  colour=C_GREEN),
            WorkflowStep("Scoring",            total=200, colour=C_PURPLE),
        ]
        with MultiStepProgress(steps, title="Startup Report") as msp:
            for kw in keywords:
                process(kw)
                msp.advance("Keyword analysis")
            ...
    """

    def __init__(
        self,
        steps: list[WorkflowStep],
        title: str = "Workflow",
    ) -> None:
        self.steps  = steps
        self.title  = title
        self._prog: Optional[Progress] = None

    def _make_progress(self) -> Progress:
        return Progress(
            TextColumn("{task.description:<28}", style=f"{C_WHITE}"),
            BarColumn(
                bar_width=24,
                style=f"dim {C_DARK}",
                complete_style=C_ACCENT,
                finished_style=C_GREEN,
            ),
            PercentColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=_con,
            expand=False,
        )

    def __enter__(self) -> "MultiStepProgress":
        _con.print()
        _con.print(f"  [{C_BANNER}]● {escape(self.title)}[/{C_BANNER}]")
        _con.print(f"  [dim {C_GRAY}]{'─'*46}[/dim {C_GRAY}]")
        self._prog = self._make_progress()
        self._prog.__enter__()
        for step in self.steps:
            step.task_id = self._prog.add_task(
                description=step.name,
                total=step.total,
                complete_style=step.colour,
            )
        return self

    def advance(self, step_name: str, amount: int = 1) -> None:
        """Advance the bar for the named step by amount."""
        if not self._prog:
            return
        for step in self.steps:
            if step.name == step_name and step.task_id is not None:
                self._prog.advance(step.task_id, amount)
                return

    def complete(self, step_name: str) -> None:
        """Mark a step as 100% complete immediately."""
        if not self._prog:
            return
        for step in self.steps:
            if step.name == step_name and step.task_id is not None:
                self._prog.update(step.task_id, completed=step.total)
                return

    def __exit__(self, *args) -> None:
        if self._prog:
            for step in self.steps:
                if step.task_id is not None:
                    self._prog.update(step.task_id, completed=step.total)
            self._prog.__exit__(*args)
        _con.print()


# ─────────────────────────────────────────────────────────────────────────────
# § 6  SIMPLE INLINE BAR
# ─────────────────────────────────────────────────────────────────────────────

class SimpleBar:
    """
    Minimal single-line progress bar for quick inline feedback.
    Does not use Rich Live — just overwrites the current line.

    Usage::

        bar = SimpleBar("Loading dataset", total=1229)
        for word in words:
            process(word)
            bar.tick()
        bar.done()
    """

    _FILL  = "█"
    _EMPTY = "░"
    _WIDTH = 24

    def __init__(
        self,
        label:  str,
        total:  int,
        colour: str = C_ACCENT,
        width:  int = _WIDTH,
    ) -> None:
        self.label   = label
        self.total   = max(1, total)
        self.colour  = colour
        self.width   = width
        self._done   = 0
        self._start  = time.monotonic()

    def tick(self, amount: int = 1) -> None:
        """Advance by amount and redraw the bar."""
        self._done = min(self._done + amount, self.total)
        self._draw()

    def set(self, value: int) -> None:
        """Jump to an absolute value and redraw."""
        self._done = max(0, min(value, self.total))
        self._draw()

    def _draw(self) -> None:
        pct    = self._done / self.total
        filled = int(pct * self.width)
        bar    = self._FILL * filled + self._EMPTY * (self.width - filled)
        elapsed = time.monotonic() - self._start
        print(
            f"\r   {self.label}  [{bar}]  "
            f"{pct:5.1%}  {self._done}/{self.total}  "
            f"{elapsed:.1f}s",
            end="",
            flush=True,
        )

    def done(self, message: Optional[str] = None) -> None:
        """Mark complete and print the final line."""
        self._done = self.total
        elapsed    = time.monotonic() - self._start
        bar        = self._FILL * self.width
        final_msg  = message or self.label
        print(
            f"\r   \033[32m✔\033[0m  {escape(final_msg)}"
            f"  [{bar}]  100%  {self._done}/{self.total}  {elapsed:.1f}s"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 7  RICH track() WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

def track(
    iterable:    Iterable[Any],
    description: str = "Processing",
    total:       Optional[int] = None,
    colour:      str = C_ACCENT,
) -> Iterator[Any]:
    """
    Wrap any iterable with a Rich progress bar.

    Drop-in replacement for ``rich.progress.track`` with NEXAGEN theming.

    Usage::

        for name in track(candidates, "Scoring names", total=len(candidates)):
            score = scorer.score(name)
    """
    prog = Progress(
        SpinnerColumn(spinner_name="dots", style=f"bold {colour}"),
        TextColumn(f"[{C_WHITE}]{escape(description)}[/{C_WHITE}]"),
        BarColumn(
            bar_width=28,
            style=f"dim {C_DARK}",
            complete_style=colour,
            finished_style=C_GREEN,
        ),
        PercentColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=_con,
        expand=False,
    )

    items = list(iterable) if total is None else iterable
    _total = total if total is not None else len(items)  # type: ignore[arg-type]

    with prog:
        task = prog.add_task(description, total=_total)
        for item in items:
            yield item
            prog.advance(task, 1)


# ─────────────────────────────────────────────────────────────────────────────
# § 8  CONTEXT MANAGER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def generation_progress(total: int = 100) -> Generator[GenerationProgress, None, None]:
    """Context manager convenience wrapper for GenerationProgress."""
    with GenerationProgress(total=total) as gp:
        yield gp


@contextmanager
def domain_check_progress(total: int) -> Generator[DomainCheckProgress, None, None]:
    """Context manager convenience wrapper for DomainCheckProgress."""
    with DomainCheckProgress(total=total) as dcp:
        yield dcp
