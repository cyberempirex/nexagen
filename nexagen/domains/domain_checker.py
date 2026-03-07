"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  domains/domain_checker.py  ·  Domain + platform availability checking     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Single module for all availability checking — domains via RDAP and platform
handles via their public APIs.

Design principles
─────────────────
  • Every checker returns exactly one of: "free" | "taken" | "unknown"
  • Retry logic: up to CHECK_RETRY_COUNT attempts with exponential back-off
  • Results are cached in ~/.nexagen/cache/domains/ (TTL from settings)
  • All I/O uses stdlib urllib only — no third-party HTTP library required
  • Parallel batch checking via CheckBatch context manager
  • Graceful degradation — network errors never raise to callers

Public API
──────────
  check_domain(domain, timeout)           → str  "free"|"taken"|"unknown"
  check_github(handle, timeout)           → str
  check_pypi(package, timeout)            → str
  check_npm(package, timeout)             → str
  check_dockerhub(name, timeout)          → str
  check_huggingface(name, timeout)        → str
  check_platform(handle, platform, timeout) → str
  batch_check_domains(domains, cfg)       → list[DomainEntry]
  batch_check_platforms(handle, cfg)      → list[PlatformEntry]

Internal
────────
  _http_get(url, headers, timeout, retries) → tuple[int, str]
  _load_cache(key)  → Optional[str]
  _save_cache(key, value, ttl)
  _cache_path(key)  → Path
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..config.constants import (
    CACHE_DIR,
    CHECK_MAX_WORKERS,
    CHECK_RETRY_COUNT,
    CHECK_TIMEOUT_SEC,
    DEFAULT_HEADERS,
    DOCKER_API_URL,
    GITHUB_API_URL,
    HF_BASE_URL,
    NPM_API_URL,
    PYPI_API_URL,
    RDAP_BASE_URL,
    TLD_SCORES,
    AvailStatus,
)
from ..ui.tables import DomainEntry, PlatformEntry

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  CACHE LAYER
# ─────────────────────────────────────────────────────────────────────────────

_DOMAIN_CACHE_DIR: Path = CACHE_DIR / "domains"


def _cache_path(key: str) -> Path:
    """Return the cache file path for a given cache key."""
    safe = hashlib.sha1(key.encode()).hexdigest()[:16]
    return _DOMAIN_CACHE_DIR / f"{safe}.json"


def _load_cache(key: str, ttl: int = 3600) -> Optional[str]:
    """
    Load a cached availability result.

    Args:
        key: The lookup key (e.g. domain name or handle).
        ttl: Maximum age in seconds before the entry is considered stale.

    Returns:
        Cached status string, or None if not found / expired.
    """
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age  = time.time() - data.get("ts", 0)
        if age > ttl:
            return None
        return data.get("status")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _save_cache(key: str, status: str) -> None:
    """
    Persist a check result to the domain cache.

    Only "free" and "taken" are cached — "unknown" is never cached so that
    network failures do not poison future checks.
    """
    if status == AvailStatus.UNKNOWN.value:
        return
    try:
        _DOMAIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(key)
        path.write_text(
            json.dumps({"key": key, "status": status, "ts": time.time()}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.debug("Cache write failed for %s: %s", key, exc)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  HTTP HELPER WITH RETRY
# ─────────────────────────────────────────────────────────────────────────────

def _http_get(
    url:      str,
    headers:  dict[str, str],
    timeout:  float,
    retries:  int = CHECK_RETRY_COUNT,
) -> tuple[int, str]:
    """
    Perform an HTTP GET with retry and exponential back-off.

    Args:
        url:     Full URL to fetch.
        headers: Request headers dict.
        timeout: Per-attempt timeout in seconds.
        retries: Number of additional attempts after the first.

    Returns:
        Tuple (status_code, body_text).
        Returns (-1, "") on complete failure.
    """
    req = urllib.request.Request(url, headers=headers)
    last_code = -1

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(4096).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            last_code = exc.code
            if exc.code in (404, 410):
                return exc.code, ""   # definitive "not found" — no retry
            if attempt < retries:
                time.sleep(0.3 * (2 ** attempt))
        except urllib.error.URLError as exc:
            log.debug("URLError on %s (attempt %d): %s", url, attempt + 1, exc)
            if attempt < retries:
                time.sleep(0.2 * (2 ** attempt))
        except Exception as exc:
            log.debug("HTTP error on %s: %s", url, exc)
            break

    return last_code, ""


# ─────────────────────────────────────────────────────────────────────────────
# § 3  DOMAIN CHECKER  (RDAP)
# ─────────────────────────────────────────────────────────────────────────────

def check_domain(
    domain:  str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache:   bool = True,
    cache_ttl:   int  = 3600,
) -> str:
    """
    Check domain registration status via RDAP (rdap.org).

    Method:
        GET https://rdap.org/domain/{domain}
        200  → TAKEN  (domain is registered)
        404  → FREE   (domain is unregistered)
        other → UNKNOWN

    Args:
        domain:    Full domain name, e.g. "nexagen.io".
        timeout:   Per-request timeout in seconds.
        use_cache: Whether to read / write the local cache.
        cache_ttl: Cache entry lifetime in seconds.

    Returns:
        "free" | "taken" | "unknown"
    """
    key = f"rdap:{domain}"

    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            log.debug("Cache hit: %s → %s", domain, cached)
            return cached

    url = f"{RDAP_BASE_URL}/{domain}"
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept":     "application/rdap+json, application/json",
    }

    code, _ = _http_get(url, headers, timeout)

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    log.debug("RDAP %s → HTTP %d → %s", domain, code, status)

    if use_cache:
        _save_cache(key, status)

    return status


# ─────────────────────────────────────────────────────────────────────────────
# § 4  PLATFORM CHECKERS
# ─────────────────────────────────────────────────────────────────────────────

def check_github(
    handle:  str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check GitHub user/org handle availability.

    Endpoint: GET https://api.github.com/users/{handle}
    200 → TAKEN  |  404 → FREE  |  other → UNKNOWN
    """
    key = f"github:{handle}"
    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            return cached

    url = f"{GITHUB_API_URL}/{handle}"
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept":     "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    code, _ = _http_get(url, headers, timeout)

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(key, status)
    return status


def check_pypi(
    package: str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check PyPI package name availability.

    Endpoint: GET https://pypi.org/pypi/{package}/json
    200 → TAKEN  |  404 → FREE  |  other → UNKNOWN
    """
    key = f"pypi:{package}"
    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            return cached

    url = f"{PYPI_API_URL}/{package}/json"
    code, _ = _http_get(url, {**DEFAULT_HEADERS}, timeout)

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(key, status)
    return status


def check_npm(
    package: str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check npm package name availability.

    Endpoint: GET https://registry.npmjs.org/{package}
    200 → TAKEN  |  404 → FREE  |  other → UNKNOWN
    """
    key = f"npm:{package}"
    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            return cached

    url = f"{NPM_API_URL}/{package}"
    code, _ = _http_get(url, {**DEFAULT_HEADERS}, timeout)

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(key, status)
    return status


def check_dockerhub(
    name:    str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check Docker Hub user/org name availability.

    Endpoint: GET https://hub.docker.com/v2/users/{name}
    200 → TAKEN  |  404 → FREE  |  other → UNKNOWN
    """
    key = f"docker:{name}"
    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            return cached

    url = f"{DOCKER_API_URL}/{name}"
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept":     "application/json",
    }
    code, _ = _http_get(url, headers, timeout)

    if code == 200:
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(key, status)
    return status


def check_huggingface(
    name:    str,
    timeout: float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check HuggingFace user/org handle availability.

    Endpoint: GET https://huggingface.co/{name}
    HuggingFace returns 200 for both existing and non-existing profiles on
    the base URL, so we check the API endpoint instead.
    200 with JSON payload → TAKEN  |  404 → FREE  |  other → UNKNOWN
    """
    key = f"hf:{name}"
    if use_cache:
        cached = _load_cache(key, cache_ttl)
        if cached is not None:
            return cached

    # HuggingFace API: check user existence
    url = f"https://huggingface.co/api/users/{name}"
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept":     "application/json",
    }
    code, body = _http_get(url, headers, timeout)

    if code == 200 and body.strip():
        status = AvailStatus.TAKEN.value
    elif code == 404:
        status = AvailStatus.FREE.value
    else:
        status = AvailStatus.UNKNOWN.value

    if use_cache:
        _save_cache(key, status)
    return status


# ─────────────────────────────────────────────────────────────────────────────
# § 5  UNIFIED PLATFORM DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

_PLATFORM_CHECKERS: dict[str, Callable[..., str]] = {
    "github":      check_github,
    "pypi":        check_pypi,
    "npm":         check_npm,
    "docker":      check_dockerhub,
    "dockerhub":   check_dockerhub,
    "huggingface": check_huggingface,
    "hf":          check_huggingface,
}


def check_platform(
    handle:   str,
    platform: str,
    timeout:  float = CHECK_TIMEOUT_SEC,
    *,
    use_cache: bool = True,
    cache_ttl: int  = 3600,
) -> str:
    """
    Check handle availability on a named platform.

    Args:
        handle:   The username / package name to check.
        platform: Platform identifier — "github" | "pypi" | "npm" |
                  "docker" | "huggingface".
        timeout:  Request timeout in seconds.
        use_cache: Enable local cache.
        cache_ttl: Cache TTL in seconds.

    Returns:
        "free" | "taken" | "unknown"
    """
    fn = _PLATFORM_CHECKERS.get(platform.lower())
    if fn is None:
        log.warning("Unknown platform: %s", platform)
        return AvailStatus.UNKNOWN.value
    return fn(handle, timeout, use_cache=use_cache, cache_ttl=cache_ttl)


# ─────────────────────────────────────────────────────────────────────────────
# § 6  BATCH DOMAIN CHECKER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckProgress:
    """Live progress counters for a batch check operation."""
    total:     int
    completed: int = 0
    free:      int = 0
    taken:     int = 0
    unknown:   int = 0

    @property
    def done(self) -> bool:
        return self.completed >= self.total

    def record(self, status: str) -> None:
        self.completed += 1
        if status == AvailStatus.FREE.value:
            self.free += 1
        elif status == AvailStatus.TAKEN.value:
            self.taken += 1
        else:
            self.unknown += 1


def batch_check_domains(
    domains:   Sequence[str],
    *,
    workers:   int   = CHECK_MAX_WORKERS,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = 3600,
    on_result: Optional[Callable[[DomainEntry], None]] = None,
) -> list[DomainEntry]:
    """
    Check a sequence of domain names in parallel.

    Args:
        domains:   Domain strings to check, e.g. ["nexagen.io", "nexagen.ai"].
        workers:   ThreadPoolExecutor worker count.
        timeout:   Per-request timeout.
        use_cache: Enable local cache.
        cache_ttl: Cache entry lifetime in seconds.
        on_result: Optional callback called with each DomainEntry as it
                   completes — useful for streaming progress updates.

    Returns:
        List of DomainEntry objects in the same order as input.
    """
    actual_workers = min(workers, len(domains), CHECK_MAX_WORKERS)
    results: dict[str, DomainEntry] = {}

    def _check_one(domain: str) -> DomainEntry:
        tld  = domain.rsplit(".", 1)[-1] if "." in domain else ""
        rank = TLD_SCORES.get(tld, 10)
        st   = check_domain(
            domain, timeout,
            use_cache=use_cache, cache_ttl=cache_ttl,
        )
        return DomainEntry(domain=domain, status=st, tld=tld, tld_rank=rank)

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        futures = {ex.submit(_check_one, d): d for d in domains}
        for fut in as_completed(futures):
            entry = fut.result()
            results[entry.domain] = entry
            if on_result:
                on_result(entry)

    # Return in original input order
    return [results[d] for d in domains if d in results]


def batch_check_platforms(
    handle:    str,
    *,
    platforms: Optional[Sequence[str]] = None,
    timeout:   float = CHECK_TIMEOUT_SEC,
    use_cache: bool  = True,
    cache_ttl: int   = 3600,
) -> list[PlatformEntry]:
    """
    Check handle availability on multiple platforms in parallel.

    Args:
        handle:    The brand handle / username / package name to check.
        platforms: List of platform names to check. Defaults to all five:
                   ["github", "pypi", "npm", "docker", "huggingface"].
        timeout:   Per-request timeout.
        use_cache: Enable local cache.
        cache_ttl: Cache entry lifetime.

    Returns:
        List of PlatformEntry objects.
    """
    if platforms is None:
        platforms = ["github", "pypi", "npm", "docker", "huggingface"]

    def _check_one(platform: str) -> PlatformEntry:
        status = check_platform(
            handle, platform, timeout,
            use_cache=use_cache, cache_ttl=cache_ttl,
        )
        return PlatformEntry(handle=handle, platform=platform, status=status)

    n = len(platforms)
    if n == 0:
        return []

    with ThreadPoolExecutor(max_workers=min(n, CHECK_MAX_WORKERS)) as ex:
        return list(ex.map(_check_one, platforms))


# ─────────────────────────────────────────────────────────────────────────────
# § 7  CACHE MANAGEMENT UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def clear_domain_cache(older_than_seconds: int = 0) -> int:
    """
    Remove cached domain check results.

    Args:
        older_than_seconds: If > 0, only remove entries older than this many
                            seconds. If 0, clears all entries.

    Returns:
        Number of cache files removed.
    """
    if not _DOMAIN_CACHE_DIR.exists():
        return 0

    now     = time.time()
    removed = 0

    for path in _DOMAIN_CACHE_DIR.glob("*.json"):
        try:
            if older_than_seconds > 0:
                data = json.loads(path.read_text(encoding="utf-8"))
                age  = now - data.get("ts", 0)
                if age < older_than_seconds:
                    continue
            path.unlink()
            removed += 1
        except (OSError, json.JSONDecodeError):
            pass

    log.info("Cleared %d domain cache entries", removed)
    return removed


def cache_stats() -> dict[str, Any]:
    """
    Return statistics about the domain check cache.

    Returns:
        Dict with keys: "entries", "free", "taken", "unknown",
        "oldest_sec", "newest_sec", "dir".
    """
    if not _DOMAIN_CACHE_DIR.exists():
        return {"entries": 0, "dir": str(_DOMAIN_CACHE_DIR)}

    now   = time.time()
    stats = {"free": 0, "taken": 0, "unknown": 0, "entries": 0}
    ages: list[float] = []

    for path in _DOMAIN_CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            st   = data.get("status", "unknown")
            stats[st] = stats.get(st, 0) + 1
            stats["entries"] += 1
            ages.append(now - data.get("ts", now))
        except (OSError, json.JSONDecodeError):
            pass

    stats["oldest_sec"] = round(max(ages), 1) if ages else 0
    stats["newest_sec"] = round(min(ages), 1) if ages else 0
    stats["dir"]        = str(_DOMAIN_CACHE_DIR)
    return stats
