"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  checks/platform_dispatcher.py  ·  Unified platform check orchestrator     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Orchestrates availability checks across all five supported platforms —
GitHub, PyPI, npm, Docker Hub, and HuggingFace — in a single call.

Responsibilities
────────────────
  • Reads Settings to determine which platforms are enabled
    (cfg.check_github, cfg.check_pypi, cfg.check_npm,
     cfg.check_docker, cfg.check_huggingface)
  • Dispatches to the specialised checker in each checks/*.py module
  • Handles HuggingFace checks inline (no dedicated hf_check.py)
  • Parallelises all enabled checks via ThreadPoolExecutor
  • Streams results to an optional on_result callback for live UI updates
  • Converts rich PlatformCheckResult objects to the ui/tables.PlatformEntry
    format consumed by print_platform_table()
  • Reports per-platform timing and a combined summary

Public API
──────────
  PlatformDispatcher.dispatch_all(handle, cfg, ...)    → list[PlatformCheckResult]
  PlatformDispatcher.dispatch_one(handle, platform, cfg) → PlatformCheckResult
  PlatformDispatcher.to_platform_entries(results)      → list[PlatformEntry]
  dispatch_all(handle, cfg, ...)                       → list[PlatformCheckResult]
  dispatch_one(handle, platform, cfg)                  → PlatformCheckResult
  to_platform_entries(results)                         → list[PlatformEntry]

Data structures
───────────────
  PlatformCheckResult  — unified result for any platform
  DispatchSummary      — aggregate stats for a full dispatch_all() run
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..config.constants import (
    CACHE_TTL_SECONDS,
    CHECK_MAX_WORKERS,
    CHECK_TIMEOUT_SEC,
    DEFAULT_HEADERS,
    HF_BASE_URL,
    AvailStatus,
)
from ..config.settings import Settings, get_settings
from ..domains.domain_checker import (
    _http_get,
    _load_cache,
    _save_cache,
)
from ..ui.tables import PlatformEntry
from .docker_check import DockerCheckResult, check_docker_namespace
from .github_check import GitHubCheckResult, check_github_handle
from .npm_check import NpmCheckResult, check_npm_package
from .pypi_check import PyPICheckResult, check_pypi_package

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  PLATFORM REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

#: All platform identifiers supported by the dispatcher
ALL_PLATFORMS: tuple[str, ...] = (
    "github",
    "pypi",
    "npm",
    "docker",
    "huggingface",
)

#: Human-readable display labels per platform
PLATFORM_LABELS: dict[str, str] = {
    "github":      "GitHub",
    "pypi":        "PyPI",
    "npm":         "npm",
    "docker":      "Docker Hub",
    "huggingface": "HuggingFace",
}

#: Settings attribute names that gate each platform check
_SETTINGS_FLAGS: dict[str, str] = {
    "github":      "check_github",
    "pypi":        "check_pypi",
    "npm":         "check_npm",
    "docker":      "check_docker",
    "huggingface": "check_huggingface",
}

# ─────────────────────────────────────────────────────────────────────────────
# § 2  HUGGINGFACE INLINE CHECK
# ─────────────────────────────────────────────────────────────────────────────

_HF_CACHE_PREFIX = "hf"
_HF_API_URL      = f"{HF_BASE_URL}/api/users"
_HF_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "Accept":     "application/json",
}


def _check_huggingface_handle(
    name:      str,
    timeout:   float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = CACHE_TTL_SECONDS,
) -> str:
    """
    Check HuggingFace user/org handle availability.

    HuggingFace returns 200 for all base-URL requests, so we use the
    dedicated API endpoint instead.

    Returns:
        \"free\" | \"taken\" | \"unknown\"
    """
    cache_key = f"{_HF_CACHE_PREFIX}:{name.lower()}"
    if use_cache:
        cached = _load_cache(cache_key, cache_ttl)
        if cached is not None:
            return cached

    url      = f"{_HF_API_URL}/{name}"
    code, body = _http_get(url, _HF_HEADERS, timeout)

    if code == 200 and body.strip():
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(cache_key, status)
    return status


# ─────────────────────────────────────────────────────────────────────────────
# § 3  UNIFIED RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlatformCheckResult:
    """
    Unified availability result for a single platform check.

    Wraps the richer per-platform result (GitHubCheckResult etc.) plus
    dispatcher-level metadata (timing, platform label).

    Attributes:
        handle:         The handle / package name that was checked.
        platform:       Lowercase platform identifier (e.g. \"github\").
        label:          Human-readable platform name (e.g. \"GitHub\").
        status:         \"free\" | \"taken\" | \"unknown\" | \"skip\"
        is_available:   True if status == \"free\".
        skipped:        True if the platform was disabled in Settings.
        from_cache:     True if served from local cache.
        checked_at:     Unix timestamp.
        duration_ms:    Wall-clock time of the HTTP request in milliseconds.
        metadata:       Dict of platform-specific fields extracted from API.
        error:          Non-empty if a non-fatal error occurred.
        detail:         Short human-readable detail line for display.
    """
    handle:       str
    platform:     str
    label:        str       = ""
    status:       str       = AvailStatus.UNKNOWN.value
    is_available: bool      = False
    skipped:      bool      = False
    from_cache:   bool      = False
    checked_at:   float     = field(default_factory=time.time)
    duration_ms:  float     = 0.0
    metadata:     dict      = field(default_factory=dict)
    error:        str       = ""
    detail:       str       = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = PLATFORM_LABELS.get(self.platform, self.platform.capitalize())

    @property
    def status_icon(self) -> str:
        s = self.status if self.status in ("free","taken","unknown","skip") else "unknown"
        return AvailStatus(s).icon

    def to_platform_entry(self) -> PlatformEntry:
        """Convert to the ui/tables.PlatformEntry format for table rendering."""
        return PlatformEntry(
            handle   = self.handle,
            platform = self.platform,
            status   = self.status,
        )

    def __str__(self) -> str:
        suffix = "  (cached)" if self.from_cache else f"  {self.duration_ms:.0f}ms"
        return f"{self.label:<14} {self.handle}  →  {self.status.upper()}{suffix}"


@dataclass
class DispatchSummary:
    """
    Aggregate statistics for a complete dispatch_all() run.

    Attributes:
        handle:        The brand handle that was checked.
        total:         Total platforms attempted (not counting skipped).
        skipped:       Count of platforms disabled in Settings.
        free:          Count of FREE results.
        taken:         Count of TAKEN results.
        unknown:       Count of UNKNOWN results.
        duration_ms:   Total wall-clock time for the full dispatch.
        best_platforms: Names of platforms where the handle is FREE.
    """
    handle:         str
    total:          int          = 0
    skipped:        int          = 0
    free:           int          = 0
    taken:          int          = 0
    unknown:        int          = 0
    duration_ms:    float        = 0.0
    best_platforms: list[str]    = field(default_factory=list)

    @property
    def all_free(self) -> bool:
        """True if every checked platform returned FREE."""
        return self.free == self.total and self.total > 0

    @property
    def any_free(self) -> bool:
        """True if at least one checked platform returned FREE."""
        return self.free > 0


# ─────────────────────────────────────────────────────────────────────────────
# § 4  PLATFORM DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

class PlatformDispatcher:
    """
    Orchestrates availability checks across all supported platforms.

    Usage — full run respecting Settings flags::

        from nexagen.checks.platform_dispatcher import PlatformDispatcher
        dispatcher = PlatformDispatcher()
        results    = dispatcher.dispatch_all("paperdesk", cfg=settings)
        entries    = dispatcher.to_platform_entries(results)
        # entries: list[PlatformEntry]  → pass to print_platform_table()

    Usage — single platform::

        result = dispatcher.dispatch_one("paperdesk", "github")
        print(result.status)  # "free" | "taken" | "unknown"

    The dispatcher is stateless — safe to reuse across multiple calls.
    """

    # ── Single platform check ─────────────────────────────────────────────────

    def dispatch_one(
        self,
        handle:    str,
        platform:  str,
        cfg:       Optional[Settings] = None,
        *,
        timeout:   Optional[float] = None,
        use_cache: bool  = True,
        cache_ttl: int   = CACHE_TTL_SECONDS,
    ) -> PlatformCheckResult:
        """
        Check handle availability on a single named platform.

        Args:
            handle:    Username / package name to check.
            platform:  Lowercase platform identifier from ALL_PLATFORMS.
            cfg:       Active Settings (for timeout override if not passed).
            timeout:   Override timeout in seconds. Uses cfg.check_timeout
                       if None.
            use_cache: Enable local cache.
            cache_ttl: Cache entry lifetime.

        Returns:
            :class:`PlatformCheckResult`
        """
        if cfg is None:
            cfg = get_settings()
        if timeout is None:
            timeout = cfg.check_timeout

        platform = platform.lower()
        label    = PLATFORM_LABELS.get(platform, platform.capitalize())

        if platform not in ALL_PLATFORMS:
            log.warning("Unknown platform: %r", platform)
            return PlatformCheckResult(
                handle=handle, platform=platform, label=label,
                status=AvailStatus.UNKNOWN.value,
                error=f"Unknown platform: {platform!r}",
            )

        t0 = time.monotonic()

        try:
            status, meta, from_cache, detail = self._call_checker(
                handle, platform, timeout, use_cache=use_cache, cache_ttl=cache_ttl,
            )
        except Exception as exc:
            log.exception("Dispatcher error on %s/%s: %s", platform, handle, exc)
            status, meta, from_cache, detail = AvailStatus.UNKNOWN.value, {}, False, str(exc)

        duration_ms = (time.monotonic() - t0) * 1000.0

        return PlatformCheckResult(
            handle       = handle,
            platform     = platform,
            label        = label,
            status       = status,
            is_available = (status == AvailStatus.FREE.value),
            from_cache   = from_cache,
            checked_at   = time.time(),
            duration_ms  = round(duration_ms, 1),
            metadata     = meta,
            detail       = detail,
        )

    # ── Full dispatch (all enabled platforms in parallel) ─────────────────────

    def dispatch_all(
        self,
        handle:    str,
        cfg:       Optional[Settings] = None,
        *,
        platforms: Optional[Sequence[str]] = None,
        timeout:   Optional[float]         = None,
        use_cache: bool                    = True,
        cache_ttl: int                     = CACHE_TTL_SECONDS,
        on_result: Optional[Callable[[PlatformCheckResult], None]] = None,
    ) -> list[PlatformCheckResult]:
        """
        Check handle availability on all enabled platforms in parallel.

        Which platforms run is controlled by Settings boolean flags
        (``cfg.check_github``, ``cfg.check_pypi``, …) unless an explicit
        *platforms* list is provided.

        If ``cfg.do_handle_checks`` is False, all platforms are SKIPPED.

        Args:
            handle:    Handle / username / package name to check.
            cfg:       Active Settings.
            platforms: Explicit list of platform ids to check. Overrides
                       Settings flags when provided.
            timeout:   Per-request timeout. Falls back to cfg.check_timeout.
            use_cache: Enable local cache.
            cache_ttl: Cache entry lifetime.
            on_result: Optional callback called with each result as it arrives.

        Returns:
            List of :class:`PlatformCheckResult`, one per platform (including
            skipped ones with status \"skip\").  Order follows ALL_PLATFORMS.
        """
        if cfg is None:
            cfg = get_settings()
        if timeout is None:
            timeout = cfg.check_timeout

        # Determine which platforms to run
        if platforms is not None:
            enabled   = [p.lower() for p in platforms if p.lower() in ALL_PLATFORMS]
            disabled  = []
        elif not cfg.do_handle_checks:
            enabled   = []
            disabled  = list(ALL_PLATFORMS)
        else:
            enabled  = []
            disabled = []
            for plat in ALL_PLATFORMS:
                flag = _SETTINGS_FLAGS.get(plat, "")
                if flag and getattr(cfg, flag, True):
                    enabled.append(plat)
                else:
                    disabled.append(plat)

        # Build skip entries for disabled platforms
        skip_results: list[PlatformCheckResult] = [
            PlatformCheckResult(
                handle=handle,
                platform=p,
                status=AvailStatus.SKIP.value,
                skipped=True,
            )
            for p in disabled
        ]

        if not enabled:
            return skip_results

        # Parallel dispatch for enabled platforms
        active_results: dict[str, PlatformCheckResult] = {}

        def _run(plat: str) -> PlatformCheckResult:
            return self.dispatch_one(
                handle, plat, cfg,
                timeout=timeout, use_cache=use_cache, cache_ttl=cache_ttl,
            )

        workers = min(len(enabled), cfg.check_workers, CHECK_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_run, p): p for p in enabled}
            for fut in as_completed(futures):
                r = fut.result()
                active_results[r.platform] = r
                if on_result:
                    on_result(r)

        # Return in canonical ALL_PLATFORMS order
        ordered: list[PlatformCheckResult] = []
        for plat in ALL_PLATFORMS:
            if plat in active_results:
                ordered.append(active_results[plat])
            else:
                # disabled
                ordered.append(PlatformCheckResult(
                    handle=handle,
                    platform=plat,
                    status=AvailStatus.SKIP.value,
                    skipped=True,
                ))

        return ordered

    # ── Conversion helpers ────────────────────────────────────────────────────

    def to_platform_entries(
        self,
        results: Sequence[PlatformCheckResult],
    ) -> list[PlatformEntry]:
        """
        Convert a list of PlatformCheckResult to ui/tables PlatformEntry.

        Skipped platforms are excluded from the output list so that
        print_platform_table() only shows platforms that were checked.

        Args:
            results: Results from dispatch_all() or dispatch_one().

        Returns:
            List of :class:`~nexagen.ui.tables.PlatformEntry` ready for
            ``print_platform_table()``.
        """
        return [
            r.to_platform_entry()
            for r in results
            if not r.skipped
        ]

    def summarise(
        self,
        handle:  str,
        results: Sequence[PlatformCheckResult],
    ) -> DispatchSummary:
        """
        Build a :class:`DispatchSummary` from a list of results.

        Args:
            handle:  The checked handle string.
            results: Results from dispatch_all().

        Returns:
            :class:`DispatchSummary` with aggregate counts and timing.
        """
        summary = DispatchSummary(handle=handle)
        total_ms = 0.0
        for r in results:
            if r.skipped:
                summary.skipped += 1
                continue
            summary.total    += 1
            total_ms         += r.duration_ms
            if r.status == AvailStatus.FREE.value:
                summary.free += 1
                summary.best_platforms.append(r.label or r.platform)
            elif r.status == AvailStatus.TAKEN.value:
                summary.taken += 1
            else:
                summary.unknown += 1
        summary.duration_ms = round(total_ms, 1)
        return summary

    # ── Private dispatcher core ───────────────────────────────────────────────

    def _call_checker(
        self,
        handle:    str,
        platform:  str,
        timeout:   float,
        *,
        use_cache: bool,
        cache_ttl: int,
    ) -> tuple[str, dict, bool, str]:
        """
        Call the appropriate platform checker and extract normalised fields.

        Returns:
            Tuple (status, metadata_dict, from_cache, detail_str).
        """
        kw = dict(use_cache=use_cache, cache_ttl=cache_ttl)

        if platform == "github":
            r = check_github_handle(handle, timeout, **kw)
            meta = {
                "account_type": r.account_type,
                "login":        r.login,
                "public_repos": r.public_repos,
                "followers":    r.followers,
                "created_at":   r.created_at,
                "profile_url":  r.profile_url,
            }
            detail = r.account_type or ""
            return r.status, meta, r.from_cache, detail

        if platform == "pypi":
            r = check_pypi_package(handle, timeout, **kw)
            meta = {
                "normalized":      r.normalized,
                "latest_version":  r.latest_version,
                "author":          r.author,
                "summary":         r.summary,
                "license":         r.license,
                "release_count":   r.release_count,
                "pypi_url":        r.pypi_url,
            }
            detail = f"v{r.latest_version}" if r.latest_version else ""
            return r.status, meta, r.from_cache, detail

        if platform == "npm":
            r = check_npm_package(handle, timeout, **kw)
            meta = {
                "is_scoped":       r.is_scoped,
                "scope":           r.scope,
                "latest_version":  r.latest_version,
                "description":     r.description,
                "license":         r.license,
                "maintainers":     r.maintainers,
                "npm_url":         r.npm_url,
            }
            detail = f"v{r.latest_version}" if r.latest_version else ""
            return r.status, meta, r.from_cache, detail

        if platform == "docker":
            r = check_docker_namespace(handle, timeout, **kw)
            meta = {
                "namespace_type": r.namespace_type,
                "full_name":      r.full_name,
                "location":       r.location,
                "company":        r.company,
                "joined_at":      r.joined_at,
                "hub_url":        r.hub_url,
            }
            detail = r.namespace_type or ""
            return r.status, meta, r.from_cache, detail

        if platform == "huggingface":
            status = _check_huggingface_handle(handle, timeout, **kw)
            meta   = {
                "profile_url": f"{HF_BASE_URL}/{handle}" if status == AvailStatus.TAKEN.value else "",
            }
            return status, meta, False, ""

        return AvailStatus.UNKNOWN.value, {}, False, f"Unknown platform: {platform!r}"


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SIMPLE FUNCTIONAL INTERFACES
# ─────────────────────────────────────────────────────────────────────────────

def dispatch_all(
    handle:    str,
    cfg:       Optional[Settings] = None,
    *,
    platforms: Optional[Sequence[str]]                              = None,
    on_result: Optional[Callable[[PlatformCheckResult], None]]      = None,
    use_cache: bool                                                 = True,
) -> list[PlatformCheckResult]:
    """
    Check *handle* on all enabled platforms and return results.

    Functional wrapper around :meth:`PlatformDispatcher.dispatch_all`.

    Args:
        handle:    Username / package name to check.
        cfg:       Active Settings.
        platforms: Explicit platform list. Defaults to Settings-gated set.
        on_result: Optional streaming callback.
        use_cache: Enable local cache.

    Returns:
        List of :class:`PlatformCheckResult`, canonical order.
    """
    return PlatformDispatcher().dispatch_all(
        handle, cfg,
        platforms=platforms,
        on_result=on_result,
        use_cache=use_cache,
    )


def dispatch_one(
    handle:   str,
    platform: str,
    cfg:      Optional[Settings] = None,
) -> PlatformCheckResult:
    """
    Check *handle* on a single *platform*.

    Functional wrapper around :meth:`PlatformDispatcher.dispatch_one`.

    Args:
        handle:   Username / package name to check.
        platform: Platform identifier (see ALL_PLATFORMS).
        cfg:      Active Settings.

    Returns:
        :class:`PlatformCheckResult`
    """
    return PlatformDispatcher().dispatch_one(handle, platform, cfg)


def to_platform_entries(
    results: Sequence[PlatformCheckResult],
) -> list[PlatformEntry]:
    """
    Convert dispatcher results to ui/tables PlatformEntry list.

    Functional wrapper around :meth:`PlatformDispatcher.to_platform_entries`.

    Args:
        results: Results from :func:`dispatch_all` or :func:`dispatch_one`.

    Returns:
        List of :class:`~nexagen.ui.tables.PlatformEntry`.
    """
    return PlatformDispatcher().to_platform_entries(results)
