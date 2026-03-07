"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  checks/github_check.py  ·  GitHub handle / org availability checker       ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Standalone GitHub availability checker with rich metadata extraction.

API used
────────
  GET https://api.github.com/users/{handle}

  200 → handle is TAKEN  (returns JSON with user/org metadata)
  404 → handle is FREE
  403 → rate-limited → UNKNOWN (not cached)
  other → UNKNOWN

Handle rules (GitHub enforces)
───────────────────────────────
  • 1–39 characters
  • Alphanumeric and hyphens only  (a-z A-Z 0-9 -)
  • Cannot start or end with a hyphen
  • No consecutive hyphens
  • Case-insensitive (GitHub treats them equivalently)

Public API
──────────
  validate_github_handle(handle)                         → (bool, str)
  check_github_handle(handle, timeout, ...)              → GitHubCheckResult
  batch_check_github(handles, workers, timeout, ...)     → list[GitHubCheckResult]

Data structures
───────────────
  GitHubCheckResult  — handle + status + rich API metadata
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..config.constants import (
    CACHE_TTL_SECONDS,
    CHECK_MAX_WORKERS,
    CHECK_TIMEOUT_SEC,
    DEFAULT_HEADERS,
    GITHUB_API_URL,
    AvailStatus,
)
from ..domains.domain_checker import (
    _http_get,
    _load_cache,
    _save_cache,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_PREFIX    = "github"
_MAX_HANDLE_LEN  = 39
_MIN_HANDLE_LEN  = 1
_HANDLE_RE       = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$|^[a-zA-Z0-9]$")

# GitHub-specific request headers
_GITHUB_HEADERS: dict[str, str] = {
    "User-Agent":            DEFAULT_HEADERS["User-Agent"],
    "Accept":                "application/vnd.github+json",
    "X-GitHub-Api-Version":  "2022-11-28",
}

# Rate-limit header names returned by GitHub
_RL_REMAINING = "X-RateLimit-Remaining"
_RL_RESET     = "X-RateLimit-Reset"


# ─────────────────────────────────────────────────────────────────────────────
# § 2  RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GitHubCheckResult:
    """
    Full result of a GitHub handle availability check.

    Attributes:
        handle:            The handle / username that was checked.
        status:            \"free\" | \"taken\" | \"unknown\"
        is_available:      True if status == \"free\".
        from_cache:        True if the result was served from local cache.
        checked_at:        Unix timestamp of when the check completed.
        account_type:      \"User\" | \"Organization\" | \"\" (empty if free/unknown).
        login:             Actual cased login name from GitHub (may differ from input).
        public_repos:      Number of public repos (0 if free/unknown).
        public_gists:      Number of public gists.
        followers:         Follower count (0 if free/unknown).
        created_at:        ISO 8601 creation date string (\"\" if free/unknown).
        avatar_url:        Avatar image URL (\"\" if free/unknown).
        profile_url:       HTML profile URL (\"\" if free/unknown).
        rate_limit_left:   X-RateLimit-Remaining from the response (-1 if unknown).
        error:             Non-empty if the check encountered a non-fatal error.
    """
    handle:         str
    status:         str
    is_available:   bool      = False
    from_cache:     bool      = False
    checked_at:     float     = field(default_factory=time.time)
    account_type:   str       = ""
    login:          str       = ""
    public_repos:   int       = 0
    public_gists:   int       = 0
    followers:      int       = 0
    created_at:     str       = ""
    avatar_url:     str       = ""
    profile_url:    str       = ""
    rate_limit_left:int       = -1
    error:          str       = ""

    @property
    def is_user(self) -> bool:
        """True if the account is a personal user account."""
        return self.account_type == "User"

    @property
    def is_org(self) -> bool:
        """True if the account is an organisation."""
        return self.account_type == "Organization"

    @property
    def status_icon(self) -> str:
        return AvailStatus(self.status).icon if self.status in ("free","taken","unknown","skip") else "?"

    def __str__(self) -> str:
        return (
            f"GitHub:{self.handle}  →  {self.status.upper()}"
            + (f"  ({self.account_type})" if self.account_type else "")
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_github_handle(handle: str) -> tuple[bool, str]:
    """
    Validate a GitHub username / organisation handle.

    Rules (GitHub-enforced):
      • 1–39 characters
      • Alphanumeric characters and hyphens only
      • Cannot start or end with a hyphen
      • No consecutive hyphens  (GitHub blocks "--")

    Args:
        handle: The handle string to validate (casing is ignored).

    Returns:
        Tuple (is_valid: bool, reason: str).
        reason is empty if valid, or a human-readable message if not.
    """
    if not handle:
        return False, "Handle must not be empty."
    if len(handle) < _MIN_HANDLE_LEN:
        return False, f"Handle is too short (minimum {_MIN_HANDLE_LEN} character)."
    if len(handle) > _MAX_HANDLE_LEN:
        return False, f"Handle exceeds {_MAX_HANDLE_LEN} characters."
    if handle.startswith("-") or handle.endswith("-"):
        return False, "Handle cannot start or end with a hyphen."
    if "--" in handle:
        return False, "Handle cannot contain consecutive hyphens."
    if not _HANDLE_RE.match(handle):
        return False, "Handle may only contain letters, digits, and hyphens."
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SINGLE HANDLE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_github_handle(
    handle:    str,
    timeout:   float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = CACHE_TTL_SECONDS,
) -> GitHubCheckResult:
    """
    Check a single GitHub handle / org for availability.

    Calls the GitHub Users API and extracts full account metadata when
    the handle is taken (200 response).  For free handles (404) and
    unknown results, metadata fields are left at their defaults.

    Rate-limit notes:
      • Unauthenticated calls are limited to 60 requests/hour per IP.
      • 403 responses usually mean rate-limited — returned as UNKNOWN
        and NOT cached so the next run will retry.

    Args:
        handle:    GitHub username / org name.
        timeout:   Per-attempt HTTP timeout in seconds.
        use_cache: Read / write the local SHA-1-keyed cache.
        cache_ttl: Cache entry lifetime in seconds.

    Returns:
        :class:`GitHubCheckResult`
    """
    ok, reason = validate_github_handle(handle)
    if not ok:
        log.debug("Invalid GitHub handle %r: %s", handle, reason)
        return GitHubCheckResult(
            handle=handle,
            status=AvailStatus.UNKNOWN.value,
            error=reason,
        )

    cache_key = f"{_CACHE_PREFIX}:{handle.lower()}"

    # ── Cache read ────────────────────────────────────────────────────────────
    if use_cache:
        cached = _load_cache(cache_key, cache_ttl)
        if cached is not None:
            log.debug("Cache hit GitHub:%s → %s", handle, cached)
            return GitHubCheckResult(
                handle=handle,
                status=cached,
                is_available=(cached == AvailStatus.FREE.value),
                from_cache=True,
            )

    # ── HTTP request ──────────────────────────────────────────────────────────
    url    = f"{GITHUB_API_URL}/{handle}"
    t0     = time.monotonic()
    code, body = _http_get(url, _GITHUB_HEADERS, timeout)
    elapsed = time.monotonic() - t0

    # ── Parse status ──────────────────────────────────────────────────────────
    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    elif code == 403:
        # Rate-limited — do NOT cache
        log.warning("GitHub rate-limit hit for handle %r", handle)
        return GitHubCheckResult(
            handle=handle,
            status=AvailStatus.UNKNOWN.value,
            error="GitHub API rate limit exceeded. Try again later.",
        )
    else:
        status = AvailStatus.UNKNOWN.value

    # ── Extract metadata from JSON body ───────────────────────────────────────
    result = GitHubCheckResult(
        handle=handle,
        status=status,
        is_available=(status == AvailStatus.FREE.value),
        from_cache=False,
        checked_at=time.time(),
    )

    if code == 200 and body:
        try:
            data             = json.loads(body)
            result.account_type = data.get("type", "")
            result.login        = data.get("login", handle)
            result.public_repos = int(data.get("public_repos", 0))
            result.public_gists = int(data.get("public_gists", 0))
            result.followers    = int(data.get("followers", 0))
            result.created_at   = data.get("created_at", "")
            result.avatar_url   = data.get("avatar_url", "")
            result.profile_url  = data.get("html_url", f"https://github.com/{handle}")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            log.debug("GitHub body parse error for %r: %s", handle, exc)

    log.debug("GitHub:%s  HTTP %d  status=%s  %.2fs", handle, code, status, elapsed)

    # ── Cache write ───────────────────────────────────────────────────────────
    if use_cache:
        _save_cache(cache_key, status)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# § 5  BATCH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def batch_check_github(
    handles:   Sequence[str],
    *,
    workers:   int   = CHECK_MAX_WORKERS,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = CACHE_TTL_SECONDS,
    on_result: Optional[Callable[[GitHubCheckResult], None]] = None,
) -> list[GitHubCheckResult]:
    """
    Check multiple GitHub handles in parallel.

    Args:
        handles:   Sequence of handle strings to check.
        workers:   ThreadPoolExecutor worker count (capped at CHECK_MAX_WORKERS).
        timeout:   Per-request timeout in seconds.
        use_cache: Enable local cache.
        cache_ttl: Cache entry lifetime.
        on_result: Optional callback fired with each result as it completes.

    Returns:
        List of :class:`GitHubCheckResult` in the same order as *handles*.
    """
    if not handles:
        return []

    actual_workers = min(workers, len(handles), CHECK_MAX_WORKERS)
    results: dict[str, GitHubCheckResult] = {}

    def _check(h: str) -> GitHubCheckResult:
        return check_github_handle(
            h, timeout, use_cache=use_cache, cache_ttl=cache_ttl,
        )

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        futures = {ex.submit(_check, h): h for h in handles}
        for fut in as_completed(futures):
            r = fut.result()
            results[r.handle.lower()] = r
            if on_result:
                on_result(r)

    return [results[h.lower()] for h in handles if h.lower() in results]
