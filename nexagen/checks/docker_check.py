"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  checks/docker_check.py  ·  Docker Hub namespace availability checker      ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Standalone Docker Hub namespace availability checker with org/user
disambiguation and metadata extraction.

A Docker Hub \"namespace\" is the username or organisation name that prefixes
image names (e.g. the ``mycompany`` in ``mycompany/myimage``).

API strategy
────────────
  Docker Hub v2 API:

  1. Check user endpoint:    GET https://hub.docker.com/v2/users/{name}
     200 → TAKEN (personal user account)
     404 → not a user — try org endpoint

  2. Check org endpoint:     GET https://hub.docker.com/v2/orgs/{name}
     200 → TAKEN (organisation)
     404 → namespace is FREE

  Both 404s → FREE
  Network error on either → UNKNOWN

Namespace rules (Docker Hub)
─────────────────────────────
  • 4–30 characters
  • Lowercase letters, digits, and underscores only
  • Must start with a letter or digit
  • No consecutive underscores

Public API
──────────
  validate_docker_namespace(name)                       → (bool, str)
  check_docker_namespace(name, timeout, ...)            → DockerCheckResult
  batch_check_docker(names, workers, timeout, ...)      → list[DockerCheckResult]

Data structures
───────────────
  DockerCheckResult  — name + status + namespace type + metadata
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
    DOCKER_API_URL,
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

_CACHE_PREFIX   = "docker"
_MIN_NS_LEN     = 4
_MAX_NS_LEN     = 30

# Docker Hub namespace regex: lowercase alphanumeric + underscore
_NS_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,28}[a-z0-9]$|^[a-z0-9]{4}$")

# Docker Hub v2 orgs endpoint
_DOCKER_ORGS_URL = "https://hub.docker.com/v2/orgs"

_DOCKER_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "Accept":     "application/json",
}

# Namespace type labels
NS_USER = "user"
NS_ORG  = "org"
NS_FREE = ""


# ─────────────────────────────────────────────────────────────────────────────
# § 2  RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DockerCheckResult:
    """
    Full result of a Docker Hub namespace availability check.

    Attributes:
        name:           The namespace / username that was checked.
        status:         \"free\" | \"taken\" | \"unknown\"
        is_available:   True if status == \"free\".
        namespace_type: \"user\" | \"org\" | \"\" (empty if free/unknown).
        from_cache:     True if served from local cache.
        checked_at:     Unix timestamp of the check.
        full_name:      Display name / company name from the API.
        location:       Geographic location string (if present).
        company:        Company field from the user/org profile.
        bio:            Profile bio text (trimmed to 120 chars).
        joined_at:      ISO 8601 date the account was created.
        hub_url:        Direct link to Docker Hub profile.
        error:          Non-empty if a non-fatal error occurred.
    """
    name:           str
    status:         str
    is_available:   bool   = False
    namespace_type: str    = NS_FREE
    from_cache:     bool   = False
    checked_at:     float  = field(default_factory=time.time)
    full_name:      str    = ""
    location:       str    = ""
    company:        str    = ""
    bio:            str    = ""
    joined_at:      str    = ""
    hub_url:        str    = ""
    error:          str    = ""

    @property
    def is_user(self) -> bool:
        """True if the namespace belongs to a personal user account."""
        return self.namespace_type == NS_USER

    @property
    def is_org(self) -> bool:
        """True if the namespace belongs to a Docker Hub organisation."""
        return self.namespace_type == NS_ORG

    @property
    def status_icon(self) -> str:
        return AvailStatus(self.status).icon if self.status in ("free","taken","unknown","skip") else "?"

    def __str__(self) -> str:
        ns_label = f"  ({self.namespace_type})" if self.namespace_type else ""
        return f"Docker:{self.name}  →  {self.status.upper()}{ns_label}"


# ─────────────────────────────────────────────────────────────────────────────
# § 3  VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_docker_namespace(name: str) -> tuple[bool, str]:
    """
    Validate a Docker Hub namespace (username / organisation name).

    Rules (Docker Hub enforced):
      • 4–30 characters
      • Lowercase letters, digits, and underscores only
      • Must start and end with a letter or digit
      • No consecutive underscores

    Args:
        name: Namespace string to validate.

    Returns:
        Tuple (is_valid: bool, reason: str).
        reason is empty on success.
    """
    if not name:
        return False, "Namespace must not be empty."
    if len(name) < _MIN_NS_LEN:
        return False, f"Namespace is too short (minimum {_MIN_NS_LEN} characters)."
    if len(name) > _MAX_NS_LEN:
        return False, f"Namespace exceeds {_MAX_NS_LEN} characters."
    if name != name.lower():
        return False, "Docker Hub namespaces must be lowercase."
    if not _NS_RE.match(name):
        return False, (
            "Namespace may only contain lowercase letters, digits, and underscores, "
            "and must start/end with a letter or digit."
        )
    if "__" in name:
        return False, "Namespace must not contain consecutive underscores."
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SINGLE NAMESPACE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _parse_user_meta(data: dict, result: DockerCheckResult) -> None:
    """Populate metadata fields from a Docker Hub user JSON payload."""
    result.full_name  = data.get("full_name", "") or data.get("username", "")
    result.location   = data.get("location", "")
    result.company    = data.get("company", "")
    result.bio        = (data.get("bio", "") or "")[:120]
    result.joined_at  = data.get("date_joined", "")
    result.hub_url    = f"https://hub.docker.com/u/{result.name}"


def _parse_org_meta(data: dict, result: DockerCheckResult) -> None:
    """Populate metadata fields from a Docker Hub org JSON payload."""
    result.full_name  = data.get("full_name", "") or data.get("orgname", "")
    result.location   = data.get("location", "")
    result.company    = data.get("company", "")
    result.bio        = (data.get("description", "") or "")[:120]
    result.joined_at  = data.get("date_joined", "")
    result.hub_url    = f"https://hub.docker.com/u/{result.name}"


def check_docker_namespace(
    name:      str,
    timeout:   float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = CACHE_TTL_SECONDS,
) -> DockerCheckResult:
    """
    Check a Docker Hub username / organisation namespace for availability.

    Uses a two-step probe strategy:
      1. Check users endpoint (hub.docker.com/v2/users/{name})
      2. If not found, check orgs endpoint (hub.docker.com/v2/orgs/{name})

    Both endpoints returning 404 means the namespace is FREE.

    Args:
        name:      Docker Hub namespace to check.
        timeout:   Per-attempt HTTP timeout in seconds.
        use_cache: Read / write the local cache.
        cache_ttl: Cache entry lifetime in seconds.

    Returns:
        :class:`DockerCheckResult`
    """
    ok, reason = validate_docker_namespace(name)
    if not ok:
        log.debug("Invalid Docker namespace %r: %s", name, reason)
        return DockerCheckResult(
            name=name,
            status=AvailStatus.UNKNOWN.value,
            error=reason,
        )

    cache_key = f"{_CACHE_PREFIX}:{name.lower()}"

    # ── Cache read ────────────────────────────────────────────────────────────
    if use_cache:
        cached = _load_cache(cache_key, cache_ttl)
        if cached is not None:
            log.debug("Cache hit Docker:%s → %s", name, cached)
            return DockerCheckResult(
                name=name,
                status=cached,
                is_available=(cached == AvailStatus.FREE.value),
                from_cache=True,
            )

    t0 = time.monotonic()

    # ── Step 1: Check user endpoint ───────────────────────────────────────────
    user_url         = f"{DOCKER_API_URL}/{name}"
    user_code, user_body = _http_get(user_url, _DOCKER_HEADERS, timeout)

    if user_code == 200:
        status = AvailStatus.TAKEN.value
        result = DockerCheckResult(
            name=name,
            status=status,
            is_available=False,
            namespace_type=NS_USER,
            from_cache=False,
            checked_at=time.time(),
        )
        if user_body:
            try:
                _parse_user_meta(json.loads(user_body), result)
            except (json.JSONDecodeError, TypeError) as exc:
                log.debug("Docker user body parse error for %r: %s", name, exc)

        log.debug("Docker:%s  user-hit  %.2fs", name, time.monotonic() - t0)
        if use_cache:
            _save_cache(cache_key, status)
        return result

    # user was not found — try org endpoint
    if user_code == 404:
        org_url         = f"{_DOCKER_ORGS_URL}/{name}"
        org_code, org_body = _http_get(org_url, _DOCKER_HEADERS, timeout)

        if org_code == 200:
            status = AvailStatus.TAKEN.value
            result = DockerCheckResult(
                name=name,
                status=status,
                is_available=False,
                namespace_type=NS_ORG,
                from_cache=False,
                checked_at=time.time(),
            )
            if org_body:
                try:
                    _parse_org_meta(json.loads(org_body), result)
                except (json.JSONDecodeError, TypeError) as exc:
                    log.debug("Docker org body parse error for %r: %s", name, exc)

            log.debug("Docker:%s  org-hit  %.2fs", name, time.monotonic() - t0)
            if use_cache:
                _save_cache(cache_key, status)
            return result

        elif org_code == 404:
            # Neither user nor org — namespace is free
            status = AvailStatus.FREE.value
            log.debug("Docker:%s  FREE  %.2fs", name, time.monotonic() - t0)
            if use_cache:
                _save_cache(cache_key, status)
            return DockerCheckResult(
                name=name,
                status=status,
                is_available=True,
                from_cache=False,
                checked_at=time.time(),
            )

    # Any other status code → unknown
    log.debug(
        "Docker:%s  user=%d  could not determine status  %.2fs",
        name, user_code, time.monotonic() - t0,
    )
    return DockerCheckResult(
        name=name,
        status=AvailStatus.UNKNOWN.value,
        is_available=False,
        from_cache=False,
        checked_at=time.time(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  BATCH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def batch_check_docker(
    names:     Sequence[str],
    *,
    workers:   int   = CHECK_MAX_WORKERS,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = CACHE_TTL_SECONDS,
    on_result: Optional[Callable[[DockerCheckResult], None]] = None,
) -> list[DockerCheckResult]:
    """
    Check multiple Docker Hub namespace names in parallel.

    Args:
        names:     Sequence of namespace strings to check.
        workers:   ThreadPoolExecutor worker count (capped at CHECK_MAX_WORKERS).
        timeout:   Per-request timeout.
        use_cache: Enable local cache.
        cache_ttl: Cache entry lifetime.
        on_result: Optional callback fired with each result as it completes.

    Returns:
        List of :class:`DockerCheckResult` in the same order as *names*.
    """
    if not names:
        return []

    actual_workers = min(workers, len(names), CHECK_MAX_WORKERS)
    results: dict[str, DockerCheckResult] = {}

    def _check(n: str) -> DockerCheckResult:
        return check_docker_namespace(n, timeout, use_cache=use_cache, cache_ttl=cache_ttl)

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        futures = {ex.submit(_check, n): n for n in names}
        for fut in as_completed(futures):
            r = fut.result()
            results[r.name.lower()] = r
            if on_result:
                on_result(r)

    return [results[n.lower()] for n in names if n.lower() in results]
