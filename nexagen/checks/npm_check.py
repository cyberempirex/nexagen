"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  checks/npm_check.py  ·  npm package name availability checker             ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Standalone npm package name availability checker with metadata extraction.
Supports both unscoped (``mypackage``) and scoped (``@scope/name``) packages.

API used
────────
  GET https://registry.npmjs.org/{package}

  200 → package EXISTS (TAKEN)  — JSON body with full package manifest
  404 → package is FREE
  other → UNKNOWN

  For scoped packages the name must be URL-encoded:
    @scope/name  →  %40scope%2fname  (handled automatically)

Name rules (npm)
────────────────
  Unscoped:
    • Lowercase only (npm rejects uppercase)
    • Letters, digits, hyphens, underscores, dots
    • No leading dot or underscore
    • Max 214 characters
    • Not a built-in Node.js module name

  Scoped (e.g. @myorg/mypackage):
    • Starts with @, then a scope name, then /, then a package name
    • Scope: lowercase letters, digits, hyphens
    • Package part follows same rules as unscoped

Public API
──────────
  is_scoped_package(name)                               → bool
  normalize_npm_name(name)                              → str
  validate_npm_name(name)                               → (bool, str)
  check_npm_package(package, timeout, ...)              → NpmCheckResult
  batch_check_npm(packages, workers, timeout, ...)      → list[NpmCheckResult]

Data structures
───────────────
  NpmCheckResult  — package + status + rich registry metadata
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..config.constants import (
    CACHE_TTL_SECONDS,
    CHECK_MAX_WORKERS,
    CHECK_TIMEOUT_SEC,
    DEFAULT_HEADERS,
    NPM_API_URL,
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

_CACHE_PREFIX = "npm"

# Unscoped name: lowercase alphanumeric + - _ .
# No leading . or _ ; no uppercase
_UNSCOPED_RE = re.compile(r"^(?![._])[a-z0-9._-]{1,214}$")

# Scoped name: @scope/name
_SCOPED_RE = re.compile(r"^@([a-z0-9-]+)/([a-z0-9._-]{1,214})$")

# Node.js built-in module names that npm rejects as package names
_BUILTINS: frozenset[str] = frozenset({
    "assert", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "dns", "domain", "events", "fs", "http", "http2",
    "https", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream", "string_decoder",
    "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm",
    "worker_threads", "zlib",
})

_NPM_HEADERS: dict[str, str] = {
    **DEFAULT_HEADERS,
    "Accept": "application/vnd.npm.install-v1+json",
}


# ─────────────────────────────────────────────────────────────────────────────
# § 2  RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NpmCheckResult:
    """
    Full result of an npm package name availability check.

    Attributes:
        package:        The package name as supplied (e.g. \"mylib\" or \"@org/lib\").
        status:         \"free\" | \"taken\" | \"unknown\"
        is_available:   True if status == \"free\".
        is_scoped:      True if this is a scoped package (starts with @).
        scope:          Scope portion without @, e.g. \"myorg\" (\"\" if unscoped).
        from_cache:     True if served from local cache.
        checked_at:     Unix timestamp of the check.
        latest_version: Most recent published version string.
        description:    One-line package description.
        license:        SPDX license string.
        author:         Author name string.
        homepage:       Project homepage URL.
        repository_url: Source repository URL.
        keywords:       Up to 5 package keywords from package.json.
        maintainers:    Number of package maintainers.
        dist_tags:      Dict of dist-tags (e.g. {\"latest\": \"1.2.3\",\"next\": ...}).
        error:          Non-empty if a non-fatal error occurred.
    """
    package:        str
    status:         str
    is_available:   bool            = False
    is_scoped:      bool            = False
    scope:          str             = ""
    from_cache:     bool            = False
    checked_at:     float           = field(default_factory=time.time)
    latest_version: str             = ""
    description:    str             = ""
    license:        str             = ""
    author:         str             = ""
    homepage:       str             = ""
    repository_url: str             = ""
    keywords:       list[str]       = field(default_factory=list)
    maintainers:    int             = 0
    dist_tags:      dict[str, str]  = field(default_factory=dict)
    error:          str             = ""

    @property
    def npm_url(self) -> str:
        """Direct link to this package on npmjs.com."""
        if self.status == AvailStatus.TAKEN.value:
            encoded = urllib.parse.quote(self.package, safe="@/")
            return f"https://www.npmjs.com/package/{encoded}"
        return ""

    @property
    def status_icon(self) -> str:
        return AvailStatus(self.status).icon if self.status in ("free","taken","unknown","skip") else "?"

    def __str__(self) -> str:
        detail = f"  v{self.latest_version}" if self.latest_version else ""
        return f"npm:{self.package}  →  {self.status.upper()}{detail}"


# ─────────────────────────────────────────────────────────────────────────────
# § 3  VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_scoped_package(name: str) -> bool:
    """
    Return True if *name* is a scoped npm package (e.g. ``@myorg/pkg``).

    Args:
        name: Package name string.

    Returns:
        bool
    """
    return name.startswith("@") and "/" in name


def normalize_npm_name(name: str) -> str:
    """
    Normalise an npm package name for cache keying.

    Lowercases the name; scoped names keep their ``@scope/`` prefix.

    Args:
        name: Package name.

    Returns:
        Lowercased package name.
    """
    return name.lower()


def validate_npm_name(name: str) -> tuple[bool, str]:
    """
    Validate an npm package name.

    Checks both unscoped and scoped formats against npm's enforced rules.

    Args:
        name: Package name to validate.

    Returns:
        Tuple (is_valid: bool, reason: str).
        reason is empty on success.
    """
    if not name:
        return False, "Package name must not be empty."

    if is_scoped_package(name):
        if not _SCOPED_RE.match(name):
            return False, (
                "Scoped package must match @scope/name where scope and name "
                "are lowercase alphanumeric + hyphens."
            )
        return True, ""

    # Unscoped checks
    if name != name.lower():
        return False, "npm package names must be lowercase."
    if name.startswith(".") or name.startswith("_"):
        return False, "npm package names must not start with '.' or '_'."
    if len(name) > 214:
        return False, "npm package names must be 214 characters or fewer."
    if not _UNSCOPED_RE.match(name):
        return False, (
            "npm package names may only contain lowercase letters, digits, "
            "hyphens, underscores, and dots."
        )
    if name in _BUILTINS:
        return False, f"'{name}' is a Node.js built-in module name and cannot be used."
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SINGLE PACKAGE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_npm_package(
    package:   str,
    timeout:   float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = CACHE_TTL_SECONDS,
) -> NpmCheckResult:
    """
    Check a single npm package name for availability.

    Calls the npm registry JSON API.  Scoped package names are
    URL-encoded automatically (@ → %40, / → %2F).

    Args:
        package:   Package name (unscoped or ``@scope/name``).
        timeout:   Per-attempt HTTP timeout in seconds.
        use_cache: Read / write the local cache.
        cache_ttl: Cache entry lifetime in seconds.

    Returns:
        :class:`NpmCheckResult`
    """
    ok, reason = validate_npm_name(package)
    if not ok:
        log.debug("Invalid npm name %r: %s", package, reason)
        return NpmCheckResult(
            package=package,
            status=AvailStatus.UNKNOWN.value,
            error=reason,
        )

    scoped = is_scoped_package(package)
    scope  = package.split("/")[0].lstrip("@") if scoped else ""

    cache_key = f"{_CACHE_PREFIX}:{normalize_npm_name(package)}"

    # ── Cache read ────────────────────────────────────────────────────────────
    if use_cache:
        cached = _load_cache(cache_key, cache_ttl)
        if cached is not None:
            log.debug("Cache hit npm:%s → %s", package, cached)
            return NpmCheckResult(
                package=package,
                status=cached,
                is_available=(cached == AvailStatus.FREE.value),
                is_scoped=scoped,
                scope=scope,
                from_cache=True,
            )

    # ── Build URL (encode scoped names) ──────────────────────────────────────
    # npm registry accepts %40scope%2fname for scoped packages
    encoded = urllib.parse.quote(package, safe="")
    url     = f"{NPM_API_URL}/{encoded}"

    t0   = time.monotonic()
    code, body = _http_get(url, _NPM_HEADERS, timeout)
    elapsed = time.monotonic() - t0

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    result = NpmCheckResult(
        package=package,
        status=status,
        is_available=(status == AvailStatus.FREE.value),
        is_scoped=scoped,
        scope=scope,
        from_cache=False,
        checked_at=time.time(),
    )

    # ── Extract metadata from JSON body ───────────────────────────────────────
    if code == 200 and body:
        try:
            data = json.loads(body)

            # dist-tags contains {"latest": "1.2.3", ...}
            dist_tags = data.get("dist-tags", {})
            result.dist_tags      = {k: str(v) for k, v in dist_tags.items()}
            result.latest_version = dist_tags.get("latest", "")

            # Latest version manifest (may not be present in abbreviated docs)
            latest  = data.get("versions", {}).get(result.latest_version, {})
            result.description    = (data.get("description", "") or latest.get("description", ""))[:120]
            result.license        = data.get("license", "") or latest.get("license", "")

            # Author — could be a string or {name:, email:} object
            raw_author = data.get("author", latest.get("author", ""))
            if isinstance(raw_author, dict):
                result.author = raw_author.get("name", "")
            else:
                result.author = str(raw_author)

            result.homepage = data.get("homepage", "") or latest.get("homepage", "")

            # Repository
            repo = data.get("repository", latest.get("repository", {}))
            if isinstance(repo, dict):
                result.repository_url = repo.get("url", "")
            elif isinstance(repo, str):
                result.repository_url = repo

            result.keywords    = list(data.get("keywords", []))[:5]
            result.maintainers = len(data.get("maintainers", []))

        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            log.debug("npm body parse error for %r: %s", package, exc)

    log.debug("npm:%s  HTTP %d  status=%s  %.2fs", package, code, status, elapsed)

    if use_cache:
        _save_cache(cache_key, status)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# § 5  BATCH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def batch_check_npm(
    packages:  Sequence[str],
    *,
    workers:   int   = CHECK_MAX_WORKERS,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = CACHE_TTL_SECONDS,
    on_result: Optional[Callable[[NpmCheckResult], None]] = None,
) -> list[NpmCheckResult]:
    """
    Check multiple npm package names in parallel.

    Args:
        packages:  Sequence of package name strings to check.
        workers:   ThreadPoolExecutor worker count (capped at CHECK_MAX_WORKERS).
        timeout:   Per-request timeout.
        use_cache: Enable local cache.
        cache_ttl: Cache entry lifetime.
        on_result: Optional callback fired with each result as it completes.

    Returns:
        List of :class:`NpmCheckResult` in the same order as *packages*.
    """
    if not packages:
        return []

    actual_workers = min(workers, len(packages), CHECK_MAX_WORKERS)
    results: dict[str, NpmCheckResult] = {}

    def _check(p: str) -> NpmCheckResult:
        return check_npm_package(p, timeout, use_cache=use_cache, cache_ttl=cache_ttl)

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        futures = {ex.submit(_check, p): p for p in packages}
        for fut in as_completed(futures):
            r = fut.result()
            results[normalize_npm_name(r.package)] = r
            if on_result:
                on_result(r)

    return [results[normalize_npm_name(p)] for p in packages
            if normalize_npm_name(p) in results]
