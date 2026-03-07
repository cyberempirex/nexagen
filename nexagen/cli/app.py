"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  cli/app.py  ·  Application entry point and main event loop                ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

This is the top-level entry point wired to the ``nexagen`` CLI command
in pyproject.toml::

    [project.scripts]
    nexagen = "nexagen.cli.app:main"

Responsibilities
────────────────
  main()                 — CLI entry point (called by pip-installed command)
  NexagenApp             — Application controller (lifecycle, event loop)
  _check_for_update()    — Non-blocking GitHub release check
  _boot_sequence()       — Animated startup checklist
  _run_event_loop()      — Menu dispatch → command router

Boot order
──────────
  1. Parse CLI flags (--no-anim, --profile, --count, --version, --help)
  2. Clear screen
  3. Print animated banner
  4. Boot sequence (datasets loaded, update check, engine ready)
  5. Show update notification if a newer version exists
  6. Enter main menu loop
  7. Dispatch to menu.py handlers based on selected option
  8. On exit: print session footer + goodbye
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from ..config.constants import (
    CACHE_DIR,
    GEN_DEFAULT_COUNT,
    GEN_MAX_COUNT,
    TOOL_AUTHOR,
    TOOL_ECOSYSTEM,
    TOOL_NAME,
    TOOL_REPO,
    UPDATE_CACHE_FILE,
    UPDATE_CACHE_TTL,
    UPDATE_CHECK_TIMEOUT,
    UPDATE_CHECK_URL,
    VERSION,
    VERSION_TAG,
    MenuOption,
    Profile,
    StyleMode,
)
from ..config.settings import (
    apply_env_overrides,
    get_settings,
    save_settings,
    settings_summary,
)
from ..ui.banner import (
    clear_screen,
    console,
    msg_fail,
    msg_info,
    msg_ok,
    print_banner,
    print_checking_update,
    print_goodbye,
    print_interrupted,
    print_ready,
    print_session_footer,
    print_update_available,
    print_update_check_skipped,
    print_up_to_date,
    section,
)
from ..ui.animations import BootSequence, BootStep, Spinner

# ─────────────────────────────────────────────────────────────────────────────
# § 1  ARGUMENT PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the ``nexagen`` command."""
    parser = argparse.ArgumentParser(
        prog="nexagen",
        description=(
            f"{TOOL_NAME}  —  Platform Naming Intelligence Engine\n"
            f"{TOOL_AUTHOR} · {TOOL_ECOSYSTEM}\n"
            f"{TOOL_REPO}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )

    # ── Version ───────────────────────────────────────────────────────────────
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"NEXAGEN {VERSION_TAG}  ·  {TOOL_AUTHOR}",
    )

    # ── Display control ───────────────────────────────────────────────────────
    parser.add_argument(
        "--no-anim",
        action="store_true",
        default=False,
        help="Disable all animations (useful in CI or piped output).",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        default=False,
        help="Do not clear the screen on startup.",
    )

    # ── Generation shortcuts ──────────────────────────────────────────────────
    parser.add_argument(
        "--profile", "-p",
        choices=Profile.choices(),
        default=None,
        metavar="PROFILE",
        help=(
            f"Industry profile for this session. "
            f"Choices: {', '.join(Profile.choices())}. "
            f"Default: from settings."
        ),
    )
    parser.add_argument(
        "--style",
        choices=StyleMode.choices(),
        default=None,
        metavar="STYLE",
        help=(
            f"Naming style mode. "
            f"Choices: {', '.join(StyleMode.choices())}. "
            f"Default: from settings."
        ),
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=None,
        metavar="N",
        help=f"Number of names to generate (1–{GEN_MAX_COUNT}). Default: {GEN_DEFAULT_COUNT}.",
    )

    # ── Operation shortcuts ───────────────────────────────────────────────────
    parser.add_argument(
        "--generate", "-g",
        nargs="+",
        metavar="KEYWORD",
        default=None,
        help=(
            "Generate names immediately from keyword(s) and exit. "
            "Example: nexagen --generate ai data platform"
        ),
    )
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        default=False,
        help="Skip the GitHub update check on startup.",
    )

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# § 2  UPDATE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _load_update_cache() -> Optional[dict]:
    """Return cached update check data if within TTL, else None."""
    try:
        if UPDATE_CACHE_FILE.exists():
            data = json.loads(UPDATE_CACHE_FILE.read_text())
            if time.time() - data.get("ts", 0) < UPDATE_CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _save_update_cache(data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        UPDATE_CACHE_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _check_for_update() -> Optional[str]:
    """
    Check GitHub releases for a newer version.

    Returns the latest version string if newer than VERSION, else None.
    Uses a 24-hour file cache to avoid hammering the API.
    Fails silently on any network error (timeout 5 s).
    """
    # Try cache first
    cached = _load_update_cache()
    if cached:
        latest = cached.get("latest", VERSION)
        return latest if _is_newer(latest, VERSION) else None

    # Live check
    try:
        import urllib.request
        req = urllib.request.Request(
            UPDATE_CHECK_URL,
            headers={
                "User-Agent": f"nexagen/{VERSION}",
                "Accept":     "application/vnd.github+json",
            },
        )
        import urllib.error
        with urllib.request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as resp:
            payload  = json.loads(resp.read().decode())
            tag      = payload.get("tag_name", VERSION)
            latest   = tag.lstrip("v")
            _save_update_cache({"ts": time.time(), "latest": latest})
            return latest if _is_newer(latest, VERSION) else None
    except Exception:
        _save_update_cache({"ts": time.time(), "latest": VERSION})
        return None


def _is_newer(a: str, b: str) -> bool:
    """Return True if semver string a is strictly greater than b."""
    def _parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split(".")[:3])
        except ValueError:
            return (0, 0, 0)
    return _parts(a) > _parts(b)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  APPLICATION CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

class NexagenApp:
    """
    Top-level application controller.

    Owns the session lifecycle:
      boot → event loop → shutdown

    Attributes:
        cfg:              Active Settings instance.
        animated:         Whether animations are enabled this session.
        _start_time:      Monotonic timestamp of app start.
        _names_generated: Running count of generated names.
        _checks_run:      Running count of domain/platform checks.
        _exports:         Running count of exports written.
        _new_version:     Latest version string if update available.
    """

    def __init__(
        self,
        animated:         bool = True,
        clear_on_start:   bool = True,
        skip_update_check:bool = False,
    ) -> None:
        self.cfg               = get_settings()
        self.animated          = animated and self.cfg.animations
        self.clear_on_start    = clear_on_start and self.cfg.clear_on_start
        self.skip_update_check = skip_update_check

        self._start_time:      float = time.monotonic()
        self._names_generated: int   = 0
        self._checks_run:      int   = 0
        self._exports:         int   = 0
        self._new_version:     Optional[str] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self) -> int:
        """
        Full application lifecycle.

        Returns:
            Exit code (0 = clean exit, 1 = error).
        """
        try:
            self._startup()
            self._event_loop()
            self._shutdown()
            return 0
        except KeyboardInterrupt:
            print_interrupted()
            return 0
        except Exception as exc:  # noqa: BLE001
            console.print_exception()
            msg_fail(f"Fatal error: {exc}")
            return 1

    def _startup(self) -> None:
        """Run the full startup sequence."""
        if self.clear_on_start:
            clear_screen()

        print_banner(animated=self.animated)
        self._boot_sequence()

        # Show update notification if found
        if self._new_version:
            print_update_available(self._new_version)

        # Show ready line with active profile
        print_ready(
            profile=self.cfg.profile,
            style=self.cfg.style_mode,
        )

    def _shutdown(self) -> None:
        """Print session stats and exit message."""
        elapsed = time.monotonic() - self._start_time
        print_session_footer(
            names_generated=self._names_generated,
            checks_run=self._checks_run,
            exports=self._exports,
            elapsed=elapsed,
        )
        print_goodbye()

    # ── Boot Sequence ─────────────────────────────────────────────────────────

    def _boot_sequence(self) -> None:
        """
        Animated startup checklist with real checks.

        Steps:
          1. Load datasets (verify files exist)
          2. Check for updates (GitHub API, cached)
          3. Initialise settings (load TOML config)
          4. Engine ready (import health check)
        """
        from ..config.constants import (
            DS_AI_TERMS, DS_BUSINESS_TERMS, DS_COMMON_WORDS,
            DS_SYNONYMS, DS_TECH_TERMS, DS_TLDS,
        )

        boot = BootSequence()
        boot.add("Loading datasets",      "common_words · synonyms · tech_terms · ai_terms")
        boot.add("Checking for updates",  "github.com/cyberempirex/nexagen")
        boot.add("Initialising settings", "~/.nexagen/settings.toml")
        boot.add("Engine ready",          "keyword + pattern + synonym engine")

        update_result: list[Optional[str]] = [None]  # mutable container for thread result

        def check_step(step: BootStep) -> tuple[bool, str]:
            label = step.label

            # ── Step 1: Datasets ──────────────────────────────────────────────
            if label.startswith("Loading"):
                required = [
                    DS_COMMON_WORDS, DS_SYNONYMS, DS_TECH_TERMS,
                    DS_AI_TERMS, DS_BUSINESS_TERMS, DS_TLDS,
                ]
                missing = [p.name for p in required if not p.exists()]
                if missing:
                    return False, f"missing: {', '.join(missing)}"
                total = sum(
                    sum(1 for ln in p.read_text().splitlines()
                        if ln.strip() and not ln.startswith("#"))
                    for p in required if p.exists()
                )
                return True, f"{total:,} entries loaded"

            # ── Step 2: Update check ──────────────────────────────────────────
            if label.startswith("Checking"):
                if self.skip_update_check or not self.cfg.check_for_updates:
                    return True, "skipped"
                latest = _check_for_update()
                update_result[0] = latest
                if latest:
                    return True, f"v{latest} available"
                return True, f"up to date ({VERSION_TAG})"

            # ── Step 3: Settings ──────────────────────────────────────────────
            if label.startswith("Initialising"):
                from ..config.settings import USER_SETTINGS_FILE
                cfg = get_settings()
                errors = cfg.validate()
                if errors:
                    return False, f"{len(errors)} validation errors"
                src = "TOML" if USER_SETTINGS_FILE.exists() else "defaults"
                return True, f"loaded from {src}"

            # ── Step 4: Engine ────────────────────────────────────────────────
            if label.startswith("Engine"):
                try:
                    from ..utils.text_utils import normalize, syllable_count
                    from ..utils.levenshtein import levenshtein
                    from ..utils.validators import validate_brand_name
                    _  = normalize("nexagen")
                    _  = levenshtein("test", "best")
                    return True, "all modules imported"
                except ImportError as e:
                    return False, f"import error: {e}"

            return True, ""

        # Run the animated boot sequence
        if self.animated:
            boot.run(check_step, speed=0.055)
        else:
            # Silent boot — just run the checks
            for step in boot.steps:
                ok, detail = check_step(step)
                step.ok    = ok
                step.detail = detail

        # Store the update result for display after the banner
        if update_result[0]:
            self._new_version = update_result[0]

    # ── Event Loop ────────────────────────────────────────────────────────────

    def _event_loop(self) -> None:
        """
        Main menu dispatch loop.

        Renders the menu, reads user input, delegates to menu.py handlers.
        Loops until the user selects EXIT or presses Ctrl+C.
        """
        from .menu import MenuController
        menu = MenuController(app=self)

        while True:
            clear_screen()
            print_banner(animated=False)
            menu.print_menu()
            choice = menu.get_choice()

            if choice is None:
                continue

            if choice == int(MenuOption.EXIT):
                break

            try:
                menu.dispatch(choice)
            except KeyboardInterrupt:
                # Ctrl+C inside a sub-command → return to menu
                console.print()
                msg_info("Returned to main menu.")
                time.sleep(0.6)


# ─────────────────────────────────────────────────────────────────────────────
# § 4  QUICK GENERATE MODE  (nexagen --generate keyword ...)
# ─────────────────────────────────────────────────────────────────────────────

def _run_quick_generate(
    keywords: list[str],
    cfg_overrides: dict,
) -> int:
    """
    Headless generation mode — no menu, no banner animation.
    Prints a clean results table and exits.

    Used when ``nexagen --generate <keywords>`` is passed at the CLI.
    """
    cfg = get_settings()
    for k, v in cfg_overrides.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)

    print_banner(animated=False)
    section("Quick Generate Mode", cfg.__class__.__mro__[0].__name__)

    from .commands import cmd_generate_names
    result = cmd_generate_names(keywords=keywords, cfg=cfg, animated=False)

    elapsed = 0.0
    print_session_footer(
        names_generated=len(result) if result else 0,
        elapsed=elapsed,
    )
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# § 5  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    """
    Primary entry point — wired to the ``nexagen`` console script.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code passed to sys.exit().
    """
    parser = _build_arg_parser()
    args   = parser.parse_args(argv)

    # ── Load and patch settings from CLI flags ─────────────────────────────
    cfg = get_settings()
    cfg = apply_env_overrides(cfg)

    cfg_overrides: dict = {}
    if args.profile:
        cfg.profile    = args.profile
        cfg_overrides["profile"] = args.profile
    if args.style:
        cfg.style_mode = args.style
        cfg_overrides["style_mode"] = args.style
    if args.count:
        cfg.count      = args.count
        cfg_overrides["count"] = args.count
    if args.no_anim:
        cfg.animations = False
    if args.no_clear:
        cfg.clear_on_start = False

    # ── Quick-generate mode ────────────────────────────────────────────────
    if args.generate:
        return _run_quick_generate(args.generate, cfg_overrides)

    # ── Full interactive mode ──────────────────────────────────────────────
    app = NexagenApp(
        animated=cfg.animations,
        clear_on_start=cfg.clear_on_start,
        skip_update_check=args.no_update_check,
    )
    exit_code = app.run()
    return exit_code


# ─────────────────────────────────────────────────────────────────────────────
# § 6  DIRECT INVOCATION  (python -m nexagen.cli.app)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(main())
