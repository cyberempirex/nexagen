"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  checks/pypi_check.py  ·  PyPI package name availability checker           ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Standalone PyPI package name availability checker with metadata extraction
and PEP 508 / PEP 503 name normalisation.

API used
────────
  GET https://pypi.org/pypi/{package}/json

  200 → package EXISTS (TAKEN)  — JSON body contains full metadata
  404 → package is FREE
  other → UNKNOWN

Name rules (PyPI / PEP 508)
────────────────────────────
  • Letters, digits, underscores, hyphens, and dots only
  • Must start and end with a letter or digit
  • No consecutive separators (e.g. \"--\", \"__\", \"..\")
  • Case-insensitive; PyPI normalises names per PEP 503
    (lowercase + replace [-_.] with single hyphen)

Public API
──────────
  normalize_pypi_name(name)                             → str
  validate_pypi_name(name)                              → (bool, str)
  check_pypi_package(package, timeout, ...)             → PyPICheckResult
  batch_check_pypi(packages, workers, timeout, ...)     → list[PyPICheckResult]

Data structures
───────────────
  PyPICheckResult  — package + status + rich metadata from JSON
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
    PYPI_API_URL,
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

_CACHE_PREFIX = "pypi"

# PEP 508 — valid package name characters
_NAME_RE = re.compile(r"^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$")

# PEP 503 normalisation: replace any run of [-_.] with a single hyphen
_NORMALISE_RE = re.compile(r"[-_.]+")

_PYPI_HEADERS: dict[str, str] = {**DEFAULT_HEADERS}


# ─────────────────────────────────────────────────────────────────────────────
# § 2  RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PyPICheckResult:
    """
    Full result of a PyPI package name availability check.

    Attributes:
        package:         The package name as supplied by the caller.
        normalized:      PEP 503 normalised name (lowercase + hyphens).
        status:          \"free\" | \"taken\" | \"unknown\"
        is_available:    True if status == \"free\".
        from_cache:      True if served from local cache.
        checked_at:      Unix timestamp of the check.
        latest_version:  Most recent release version string (\"\" if free).
        author:          Package author string from PyPI metadata.
        author_email:    Author email.
        summary:         One-line description from setup.cfg / pyproject.
        home_page:       Project homepage URL.
        license:         SPDX license identifier string.
        release_count:   Total number of published release versions.
        requires_python: Python version specifier string.
        classifiers:     First 3 PyPI classifiers (trimmed for brevity).
        error:           Non-empty if a non-fatal error occurred.
    """
    package:         str
    normalized:      str
    status:          str
    is_available:    bool      = False
    from_cache:      bool      = False
    checked_at:      float     = field(default_factory=time.time)
    latest_version:  str       = ""
    author:          str       = ""
    author_email:    str       = ""
    summary:         str       = ""
    home_page:       str       = ""
    license:         str       = ""
    release_count:   int       = 0
    requires_python: str       = ""
    classifiers:     list[str] = field(default_factory=list)
    error:           str       = ""

    @property
    def pypi_url(self) -> str:
        """Direct link to this package on pypi.org."""
        return f"https://pypi.org/project/{self.normalized}/" if self.status == AvailStatus.TAKEN.value else ""

    @property
    def status_icon(self) -> str:
        return AvailStatus(self.status).icon if self.status in ("free","taken","unknown","skip") else "?"

    def __str__(self) -> str:
        detail = f"  v{self.latest_version}" if self.latest_version else ""
        return f"PyPI:{self.package}  →  {self.status.upper()}{detail}"


# ─────────────────────────────────────────────────────────────────────────────
# § 3  NAME NORMALISATION & VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def normalize_pypi_name(name: str) -> str:
    """
    Normalise a PyPI package name per PEP 503.

    Converts to lowercase and replaces any run of ``[-_.]`` with a
    single hyphen, making ``My.Package_Name`` → ``my-package-name``.

    Args:
        name: Raw package name string.

    Returns:
        Normalised package name string.
    """
    return _NORMALISE_RE.sub("-", name).lower()


def validate_pypi_name(name: str) -> tuple[bool, str]:
    """
    Validate a PyPI package name against PEP 508 rules.

    Rules:
      • Letters, digits, underscores, hyphens, and dots only
      • Must start and end with a letter or digit
      • No consecutive separator characters (e.g. \"--\", \"__\")
      • Length 1–200 characters

    Args:
        name: Package name to validate.

    Returns:
        Tuple (is_valid: bool, reason: str).
        reason is empty on success.
    """
    if not name:
        return False, "Package name must not be empty."
    if len(name) > 200:
        return False, "Package name exceeds 200 characters."
    if not _NAME_RE.match(name):
        return False, (
            "Package name may only contain letters, digits, hyphens, "
            "underscores, and dots, and must start/end with a letter or digit."
        )
    # Reject consecutive separators
    if re.search(r"[-_.]{2,}", name):
        return False, "Package name must not contain consecutive separator characters (-, _, .)."
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SINGLE PACKAGE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_pypi_package(
    package:   str,
    timeout:   float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = CACHE_TTL_SECONDS,
) -> PyPICheckResult:
    """
    Check a single PyPI package name for availability.

    Calls the PyPI JSON API and extracts package metadata when the name
    is taken (200 response).

    The cache key uses the *normalised* name so that ``My-Package`` and
    ``my_package`` share the same cache entry.

    Args:
        package:   Package name to check (any casing / separator style).
        timeout:   Per-attempt HTTP timeout in seconds.
        use_cache: Read / write the local cache.
        cache_ttl: Cache entry lifetime in seconds.

    Returns:
        :class:`PyPICheckResult`
    """
    ok, reason = validate_pypi_name(package)
    if not ok:
        log.debug("Invalid PyPI name %r: %s", package, reason)
        return PyPICheckResult(
            package=package,
            normalized=normalize_pypi_name(package),
            status=AvailStatus.UNKNOWN.value,
            error=reason,
        )

    normalised = normalize_pypi_name(package)
    cache_key  = f"{_CACHE_PREFIX}:{normalised}"

    # ── Cache read ────────────────────────────────────────────────────────────
    if use_cache:
        cached = _load_cache(cache_key, cache_ttl)
        if cached is not None:
            log.debug("Cache hit PyPI:%s → %s", package, cached)
            return PyPICheckResult(
                package=package,
                normalized=normalised,
                status=cached,
                is_available=(cached == AvailStatus.FREE.value),
                from_cache=True,
            )

    # ── HTTP request ──────────────────────────────────────────────────────────
    url  = f"{PYPI_API_URL}/{normalised}/json"
    t0   = time.monotonic()
    code, body = _http_get(url, _PYPI_HEADERS, timeout)
    elapsed = time.monotonic() - t0

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    result = PyPICheckResult(
        package=package,
        normalized=normalised,
        status=status,
        is_available=(status == AvailStatus.FREE.value),
        from_cache=False,
        checked_at=time.time(),
    )

    # ── Extract metadata from JSON body ───────────────────────────────────────
    if code == 200 and body:
        try:
            data = json.loads(body)
            info = data.get("info", {})
            releases = data.get("releases", {})

            result.latest_version  = info.get("version", "")
            result.author          = info.get("author", "")
            result.author_email    = info.get("author_email", "")
            result.summary         = info.get("summary", "")[:120]  # trim long summaries
            result.home_page       = info.get("home_page", "") or info.get("project_url", "")
            result.license         = info.get("license", "")
            result.requires_python = info.get("requires_python", "")
            result.release_count   = len([v for v in releases if releases[v]])
            raw_classifiers        = info.get("classifiers", [])
            result.classifiers     = raw_classifiers[:3]
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            log.debug("PyPI body parse error for %r: %s", package, exc)

    log.debug("PyPI:%s  HTTP %d  status=%s  %.2fs", package, code, status, elapsed)

    if use_cache:
        _save_cache(cache_key, status)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# § 5  BATCH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def batch_check_pypi(
    packages:  Sequence[str],
    *,
    workers:   int   = CHECK_MAX_WORKERS,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = CACHE_TTL_SECONDS,
    on_result: Optional[Callable[[PyPICheckResult], None]] = None,
) -> list[PyPICheckResult]:
    """
    Check multiple PyPI package names in parallel.

    Args:
        packages:  Package name strings to check.
        workers:   ThreadPoolExecutor worker count (capped at CHECK_MAX_WORKERS).
        timeout:   Per-request timeout.
        use_cache: Enable local cache.
        cache_ttl: Cache TTL in seconds.
        on_result: Optional callback called with each result as it completes.

    Returns:
        List of :class:`PyPICheckResult` in the same order as *packages*.
    """
    if not packages:
        return []

    actual_workers = min(workers, len(packages), CHECK_MAX_WORKERS)
    results: dict[str, PyPICheckResult] = {}

    def _check(p: str) -> PyPICheckResult:
        return check_pypi_package(p, timeout, use_cache=use_cache, cache_ttl=cache_ttl)

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        futures = {ex.submit(_check, p): p for p in packages}
        for fut in as_completed(futures):
            r = fut.result()
            results[r.normalized] = r
            if on_result:
                on_result(r)

    return [results[normalize_pypi_name(p)] for p in packages
            if normalize_pypi_name(p) in results]
