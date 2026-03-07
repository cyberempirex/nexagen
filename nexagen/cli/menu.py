"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  cli/menu.py  ·  MenuController — input, dispatch, sub-menus               ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

MenuController owns every user-facing prompt inside the menu system:

  print_menu()       — renders the main menu via ui/banner.py
  get_choice()       → int | None — reads and validates user input
  dispatch(choice)   — routes to the correct command handler
  _ask_keywords()    → list[str] — keyword input flow with hints
  _ask_name()        → str — single name input
  _ask_export()      — export format prompt + triggers export
  _settings_menu()   — settings sub-menu (profile / style / count / tlds)
  _ask_profile()     — profile selection prompt
  _ask_style()       — style selection prompt
  _ask_count()       — count input with validation

MenuController is stateless between calls except for a reference to
the parent NexagenApp instance (for session counters and settings).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.markup import escape

from ..config.constants import (
    C_ACCENT,
    C_AMBER,
    C_BLUE,
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
    GEN_MAX_COUNT,
    GEN_MIN_COUNT,
    MenuOption,
    Profile,
    StyleMode,
)
from ..config.settings import get_settings, save_settings, update_setting
from ..ui.banner import (
    clear_screen,
    console,
    msg_fail,
    msg_info,
    msg_ok,
    msg_warn,
    print_about,
    print_hint,
    print_main_menu,
    prompt_confirm,
    prompt_menu,
    prompt_text,
    section,
    separator,
    subsection,
)

if TYPE_CHECKING:
    from .app import NexagenApp

_co = Console(highlight=False, markup=True)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  MENU CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

class MenuController:
    """
    Interactive menu controller.

    Handles:
      - Rendering the main menu
      - Reading and validating user input
      - Dispatching choices to command handlers
      - All sub-menus and secondary prompts
    """

    def __init__(self, app: "NexagenApp") -> None:
        self.app = app
        self.cfg = app.cfg

    # ── Main menu interface ───────────────────────────────────────────────────

    def print_menu(self) -> None:
        """Render the styled main menu."""
        print_main_menu()

    def get_choice(self) -> Optional[int]:
        """
        Read user input for the main menu.

        Returns:
            Integer option 1–6, or None if input was invalid.
        """
        raw = prompt_menu()

        if not raw:
            return None

        try:
            choice = int(raw)
        except ValueError:
            msg_warn(f"'{escape(raw)}' is not a valid option. Enter a number 1–6.")
            time.sleep(0.8)
            return None

        valid = set(int(opt) for opt in MenuOption)
        if choice not in valid:
            msg_warn(f"Option {choice} does not exist. Choose from 1 to {max(valid)}.")
            time.sleep(0.8)
            return None

        return choice

    def dispatch(self, choice: int) -> None:
        """
        Route a validated menu choice to the correct handler.

        Args:
            choice: Validated integer from 1–6.
        """
        handlers = {
            int(MenuOption.GENERATE_NAMES): self._flow_generate,
            int(MenuOption.ANALYZE_BRAND):  self._flow_analyze,
            int(MenuOption.DOMAIN_SUGGEST): self._flow_domains,
            int(MenuOption.STARTUP_REPORT): self._flow_report,
            int(MenuOption.ABOUT):          self._flow_about,
        }
        handler = handlers.get(choice)
        if handler:
            handler()

    # ─────────────────────────────────────────────────────────────────────────
    # § 2  FLOW — GENERATE NAMES
    # ─────────────────────────────────────────────────────────────────────────

    def _flow_generate(self) -> None:
        """
        Complete name generation flow.

        Steps:
          1. Collect keywords from user
          2. Optionally customise profile / style / count
          3. Call command handler
          4. Offer export
        """
        clear_screen()
        section("GENERATE BRAND NAMES", C_GREEN)
        _co.print()
        _co.print(
            f"  [{C_GRAY}]Enter keywords that describe your product, idea, or domain.\n"
            f"  [{C_GRAY}]Examples:  [bold {C_WHITE}]ai document tool[/bold {C_WHITE}]  "
            f"·  [bold {C_WHITE}]cloud security platform[/bold {C_WHITE}]  "
            f"·  [bold {C_WHITE}]note taking app[/bold {C_WHITE}][/{C_GRAY}]"
        )
        _co.print()

        keywords = self._ask_keywords(max_keywords=8)
        if not keywords:
            msg_warn("No keywords entered. Returning to menu.")
            time.sleep(1.0)
            return

        # Optional quick-customise before generating
        _co.print()
        separator()
        _co.print()
        subsection("Generation Settings", C_ACCENT)
        _co.print(
            f"  [{C_GRAY}]Current: profile=[bold {C_ACCENT}]{self.cfg.profile}[/bold {C_ACCENT}]  "
            f"style=[bold {C_ACCENT}]{self.cfg.style_mode}[/bold {C_ACCENT}]  "
            f"count=[bold {C_ACCENT}]{self.cfg.count}[/bold {C_ACCENT}][/{C_GRAY}]"
        )
        _co.print()

        if prompt_confirm("Customise settings for this run?", default=False):
            self._quick_customise()

        _co.print()

        from .commands import cmd_generate_names
        results = cmd_generate_names(
            keywords=keywords,
            cfg=self.cfg,
            animated=self.app.animated,
        )

        if results:
            self.app._names_generated += len(results)
            _co.print()
            self._ask_export(results, context="names")

        self._press_any_key()

    # ─────────────────────────────────────────────────────────────────────────
    # § 3  FLOW — ANALYZE BRAND
    # ─────────────────────────────────────────────────────────────────────────

    def _flow_analyze(self) -> None:
        """
        Brand strength analysis flow.

        Accepts one or multiple names, runs full scoring,
        displays score cards + analysis table.
        """
        clear_screen()
        section("ANALYZE BRAND STRENGTH", C_PURPLE)
        _co.print()
        _co.print(
            f"  [{C_GRAY}]Enter a name (or multiple names separated by commas)\n"
            f"  to analyze their brand strength, phonetics, and uniqueness.[/{C_GRAY}]"
        )
        _co.print()

        raw = prompt_text("Name(s) to analyze")
        if not raw:
            msg_warn("No name entered. Returning to menu.")
            time.sleep(1.0)
            return

        names = [n.strip().lower() for n in raw.split(",") if n.strip()]
        if not names:
            msg_warn("Could not parse names. Returning to menu.")
            time.sleep(1.0)
            return

        _co.print()
        from .commands import cmd_analyze_brand
        results = cmd_analyze_brand(
            names=names,
            cfg=self.cfg,
            animated=self.app.animated,
        )

        if results:
            _co.print()
            self._ask_export(results, context="analysis")

        self._press_any_key()

    # ─────────────────────────────────────────────────────────────────────────
    # § 4  FLOW — DOMAIN SUGGESTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _flow_domains(self) -> None:
        """
        Domain discovery flow.

        Accepts a brand name, generates domain variants across
        preferred TLDs and optional prefixes/suffixes, then runs
        availability checks.
        """
        clear_screen()
        section("DOMAIN SUGGESTIONS", C_TEAL)
        _co.print()
        _co.print(
            f"  [{C_GRAY}]Enter a brand name to generate and check domain availability.\n"
            f"  Checks are run against {', '.join(self.cfg.preferred_tlds[:5])} "
            f"and others from your settings.[/{C_GRAY}]"
        )
        _co.print()

        name = self._ask_name(label="Brand name")
        if not name:
            msg_warn("No name entered. Returning to menu.")
            time.sleep(1.0)
            return

        _co.print()
        _co.print(
            f"  [{C_GRAY}]Include platform handle checks?  "
            f"(GitHub, PyPI, npm, Docker)[/{C_GRAY}]"
        )
        do_platforms = prompt_confirm("Check platforms too?", default=True)

        _co.print()

        from .commands import cmd_domain_suggestions
        results = cmd_domain_suggestions(
            name=name,
            cfg=self.cfg,
            animated=self.app.animated,
            check_platforms=do_platforms,
        )

        if results:
            total_checks = len(results.get("domains", [])) + len(results.get("platforms", []))
            self.app._checks_run += total_checks
            _co.print()
            self._ask_export(results, context="domains")

        self._press_any_key()

    # ─────────────────────────────────────────────────────────────────────────
    # § 5  FLOW — STARTUP REPORT
    # ─────────────────────────────────────────────────────────────────────────

    def _flow_report(self) -> None:
        """
        Full startup naming report flow.

        Generates names from keywords, scores them, runs domain checks,
        and produces a combined summary report.
        """
        clear_screen()
        section("STARTUP NAMING REPORT", C_GOLD)
        _co.print()
        _co.print(
            f"  [{C_GRAY}]The startup report combines name generation, brand scoring,\n"
            f"  domain discovery, and platform checks into a single output.[/{C_GRAY}]"
        )
        _co.print()

        project = prompt_text("Project or startup name (for the report header)", default="My Project")
        _co.print()

        keywords = self._ask_keywords(
            max_keywords=6,
            prompt="Keywords / themes",
        )
        if not keywords:
            msg_warn("No keywords entered. Returning to menu.")
            time.sleep(1.0)
            return

        _co.print()
        count = self._ask_count(label="How many names to generate?")
        _co.print()

        from .commands import cmd_startup_report
        report = cmd_startup_report(
            project=project,
            keywords=keywords,
            count=count,
            cfg=self.cfg,
            animated=self.app.animated,
        )

        if report:
            self.app._names_generated += report.get("names_generated", 0)
            self.app._checks_run      += report.get("checks_run", 0)
            _co.print()
            self._ask_export(report, context="report")

        self._press_any_key()

    # ─────────────────────────────────────────────────────────────────────────
    # § 6  FLOW — ABOUT
    # ─────────────────────────────────────────────────────────────────────────

    def _flow_about(self) -> None:
        """Display the About screen and wait for keypress."""
        print_about()
        self._press_any_key()

    # ─────────────────────────────────────────────────────────────────────────
    # § 7  INPUT HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _ask_keywords(
        self,
        max_keywords: int = 8,
        prompt: str = "Keywords",
    ) -> list[str]:
        """
        Prompt the user for keywords with validation and hints.

        Accepts: comma-separated or space-separated keywords.
        Returns deduplicated, lowercased list.
        """
        _co.print(
            f"  [{C_GRAY}]{escape(prompt)} "
            f"[dim](comma or space separated)[/dim][/{C_GRAY}]"
        )
        raw = prompt_text(prompt)
        if not raw:
            return []

        # Split on commas or spaces
        import re
        tokens = [t.strip().lower() for t in re.split(r"[,\s]+", raw) if t.strip()]

        # Deduplicate
        seen:    set[str]  = set()
        cleaned: list[str] = []
        for t in tokens:
            if t and t not in seen and t.isalpha() and len(t) >= 2:
                seen.add(t)
                cleaned.append(t)

        if len(tokens) > len(cleaned):
            skipped = len(tokens) - len(cleaned)
            print_hint(f"{skipped} invalid or duplicate token(s) removed.")

        if len(cleaned) > max_keywords:
            print_hint(
                f"Using first {max_keywords} keywords "
                f"(entered {len(cleaned)})."
            )
            cleaned = cleaned[:max_keywords]

        if not cleaned:
            msg_warn("No valid keywords found. Keywords must be alphabetic and ≥ 2 chars.")
            return []

        _co.print(
            f"  [{C_GREEN}]✔[/{C_GREEN}]  "
            f"[{C_GRAY}]Using keywords:[/{C_GRAY}]  "
            + "  ".join(
                f"[bold {C_ACCENT}]{escape(k)}[/bold {C_ACCENT}]"
                for k in cleaned
            )
        )
        return cleaned

    def _ask_name(self, label: str = "Name") -> str:
        """Prompt for a single alphabetic name."""
        raw = prompt_text(label)
        if not raw:
            return ""
        name = raw.strip().lower()
        import re
        name = re.sub(r"[^a-z]", "", name)
        if not name:
            msg_warn("Name must contain at least one alphabetic character.")
            return ""
        if len(name) < 2:
            msg_warn("Name must be at least 2 characters.")
            return ""
        return name

    def _ask_count(self, label: str = "Count") -> int:
        """Prompt for generation count with range validation."""
        raw = prompt_text(label, default=str(self.cfg.count))
        try:
            n = int(raw)
            if not (GEN_MIN_COUNT <= n <= GEN_MAX_COUNT):
                msg_warn(
                    f"Count must be between {GEN_MIN_COUNT} and {GEN_MAX_COUNT}. "
                    f"Using {self.cfg.count}."
                )
                return self.cfg.count
            return n
        except (ValueError, TypeError):
            return self.cfg.count

    def _ask_export(self, data: object, context: str = "results") -> None:
        """
        Offer export after a command completes.

        Args:
            data:    The result data to export (list or dict).
            context: Describes the data type for prompts.
        """
        _co.print()
        separator()
        _co.print()

        if not prompt_confirm(f"Export {context}?", default=False):
            return

        section("EXPORT", C_ACCENT)
        _co.print()
        _co.print(
            f"  [{C_GRAY}]Format options:[/{C_GRAY}]  "
            f"[{C_WHITE}]json[/{C_WHITE}]  "
            f"[{C_WHITE}]csv[/{C_WHITE}]  "
            f"[{C_WHITE}]markdown[/{C_WHITE}]  "
            f"[{C_WHITE}]all[/{C_WHITE}]"
        )

        fmt = prompt_text("Format", default="json").lower().strip()
        if fmt not in ("json", "csv", "markdown", "all"):
            msg_warn(f"Unknown format '{fmt}'. Using json.")
            fmt = "json"

        from .commands import cmd_export
        path = cmd_export(data=data, fmt=fmt, cfg=self.cfg)
        if path:
            self.app._exports += 1

    # ─────────────────────────────────────────────────────────────────────────
    # § 8  QUICK CUSTOMISE  (one-screen settings tweak)
    # ─────────────────────────────────────────────────────────────────────────

    def _quick_customise(self) -> None:
        """
        Lightweight in-session settings override without full settings menu.
        Changes apply only to this session unless user confirms save.
        """
        _co.print()
        subsection("Quick Customise", C_ACCENT)

        # Profile
        self._ask_profile()

        # Style
        self._ask_style()

        # Count
        self.cfg.count = self._ask_count("Names to generate")

        # Offer to persist
        _co.print()
        if prompt_confirm("Save these settings for future sessions?", default=False):
            save_settings(self.cfg)
            msg_ok("Settings saved to ~/.nexagen/settings.toml")

    def _ask_profile(self) -> None:
        """Profile selection sub-prompt."""
        choices = Profile.choices()
        _co.print(
            f"  [{C_GRAY}]Profile choices:[/{C_GRAY}]  "
            + "  ".join(
                f"[{'bold ' + C_ACCENT if c == self.cfg.profile else C_GRAY}]{c}[/]"
                for c in choices
            )
        )
        raw = prompt_text("Profile", default=self.cfg.profile)
        if raw in choices:
            self.cfg.profile = raw
            msg_ok(f"Profile set to '{raw}'.")
        else:
            msg_warn(f"Unknown profile '{raw}'. Keeping '{self.cfg.profile}'.")

    def _ask_style(self) -> None:
        """Style mode selection sub-prompt."""
        choices = StyleMode.choices()
        _co.print(
            f"  [{C_GRAY}]Style choices:[/{C_GRAY}]  "
            + "  ".join(
                f"[{'bold ' + C_ACCENT if c == self.cfg.style_mode else C_GRAY}]{c}[/]"
                for c in choices
            )
        )
        raw = prompt_text("Style", default=self.cfg.style_mode)
        if raw in choices:
            self.cfg.style_mode = raw
            msg_ok(f"Style set to '{raw}'.")
        else:
            msg_warn(f"Unknown style '{raw}'. Keeping '{self.cfg.style_mode}'.")

    # ─────────────────────────────────────────────────────────────────────────
    # § 9  SETTINGS SUB-MENU
    # ─────────────────────────────────────────────────────────────────────────

    def _settings_menu(self) -> None:
        """
        Full settings editor sub-menu.

        Not wired to the main menu by default — can be triggered from
        future builds by adding a Settings option.
        """
        clear_screen()
        section("SETTINGS", C_ACCENT)
        _co.print()

        from ..config.settings import settings_summary
        _co.print(settings_summary())
        _co.print()

        _SETTINGS_OPTIONS = [
            ("1", "Change profile",    self._ask_profile),
            ("2", "Change style",      self._ask_style),
            ("3", "Change count",      lambda: setattr(self.cfg, "count", self._ask_count())),
            ("4", "Toggle animations", self._toggle_animations),
            ("5", "Toggle domain checks", self._toggle_domain_checks),
            ("6", "Reset to defaults", self._reset_settings),
            ("7", "Back",              None),
        ]

        for key, label, _ in _SETTINGS_OPTIONS:
            _co.print(
                f"  [{C_ACCENT}]{key}[/{C_ACCENT}]  [{C_WHITE}]{label}[/{C_WHITE}]"
            )

        _co.print()
        raw = prompt_text("Option").strip()

        for key, _, handler in _SETTINGS_OPTIONS:
            if raw == key:
                if handler is None:
                    return
                handler()
                save_settings(self.cfg)
                msg_ok("Settings saved.")
                time.sleep(0.6)
                return

        msg_warn("Invalid option.")
        time.sleep(0.5)

    def _toggle_animations(self) -> None:
        self.cfg.animations = not self.cfg.animations
        self.app.animated   = self.cfg.animations
        status = "enabled" if self.cfg.animations else "disabled"
        msg_ok(f"Animations {status}.")

    def _toggle_domain_checks(self) -> None:
        self.cfg.do_domain_checks = not self.cfg.do_domain_checks
        status = "enabled" if self.cfg.do_domain_checks else "disabled"
        msg_ok(f"Domain checks {status}.")

    def _reset_settings(self) -> None:
        if prompt_confirm("Reset ALL settings to defaults?", default=False):
            from ..config.settings import reset_settings
            self.cfg    = reset_settings()
            self.app.cfg = self.cfg
            msg_ok("Settings reset to defaults.")

    # ─────────────────────────────────────────────────────────────────────────
    # § 10  UTILITY
    # ─────────────────────────────────────────────────────────────────────────

    def _press_any_key(self) -> None:
        """Wait for the user to press Enter before returning to the menu."""
        _co.print()
        _co.print(
            f"  [dim {C_GRAY}]Press [bold {C_WHITE}]Enter[/bold {C_WHITE}] "
            f"to return to the main menu...[/dim {C_GRAY}]"
        )
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
