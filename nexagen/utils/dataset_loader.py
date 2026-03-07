"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  utils/dataset_loader.py  ·  Canonical dataset loading layer               ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Single point of truth for every dataset file read in the project.

Architecture
────────────

  DatasetLoader      — low-level file reader with comment/blank stripping
  DatasetRegistry    — process-level singleton holding all loaded datasets
  WordFilter         — frozenset-backed common-word filter (validator hook)
  SynonymMap         — parsed synonym groups with lookup helpers
  BrandBlacklist     — merged blacklist (file + seed constant) for TM checks
  VocabRegistry      — profile → vocabulary list mapping
  load_all()         — eager load every dataset at startup (used by boot)
  dataset_health()   → DatasetHealth — integrity report for boot diagnostics

Design rules
────────────
  • Every public function returns a plain Python type (list, dict, frozenset).
  • All file I/O is centralised here — no other module reads dataset files
    directly except _DatasetCache in cli/commands.py (legacy shim, kept for
    backwards compatibility; both resolve to the same on-disk files).
  • Files that are missing produce empty collections and emit a warning —
    they never raise uncaught exceptions.
  • Loaded data is cached in the registry for the process lifetime.
    Call reset_registry() in tests or when datasets change on disk.
  • Thread-safe for the common case of read-after-load; concurrent loads
    are protected by a per-dataset lock via _load_locked().

Public API
──────────
  load_wordlist(path)              → list[str]
  load_synonym_map(path)           → dict[str, list[str]]
  common_words()                   → frozenset[str]
  blacklist()                      → frozenset[str]
  tech_terms()                     → list[str]
  ai_terms()                       → list[str]
  business_terms()                 → list[str]
  prefixes()                       → list[str]
  suffixes()                       → list[str]
  tlds()                           → list[str]
  synonyms()                       → dict[str, list[str]]
  vocab_for_profile(profile)       → list[str]
  load_all()                       → DatasetHealth
  dataset_health()                 → DatasetHealth
  reset_registry()                 — clear all cached data (tests)

Singleton helpers
─────────────────
  WordFilter                       — .contains(word) / .is_common(word)
  SynonymMap                       — .get(word) / .expand(words, depth)
  BrandBlacklist                   — .is_protected(name) / .risk_level(name)

"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..config.constants import (
    BRAND_BLACKLIST_SEED,
    DS_AI_TERMS,
    DS_BRAND_BLACKLIST,
    DS_BUSINESS_TERMS,
    DS_COMMON_WORDS,
    DS_PREFIXES,
    DS_SUFFIXES,
    DS_SYNONYMS,
    DS_TECH_TERMS,
    DS_TLDS,
    DATASETS_DIR,
    Profile,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  LOW-LEVEL FILE READER
# ─────────────────────────────────────────────────────────────────────────────

def load_wordlist(path: Path) -> list[str]:
    """
    Read a plain-text word list from *path*.

    Rules applied:
      - Lines starting with ``#`` are treated as comments and skipped.
      - Blank lines are skipped.
      - Each word is stripped and lowercased.
      - Words containing spaces are kept (multi-word entries).
      - Duplicate entries within the file are deduplicated (first wins).

    Args:
        path: Absolute or relative path to the ``.txt`` dataset file.

    Returns:
        Ordered list of unique lowercase words.
        Returns an empty list if the file does not exist or cannot be read.
    """
    if not path.exists():
        log.warning("Dataset file not found: %s", path)
        return []

    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        return []

    seen: set[str] = set()
    result: list[str] = []

    for line in raw:
        word = line.strip().lower()
        if not word or word.startswith("#"):
            continue
        if word not in seen:
            seen.add(word)
            result.append(word)

    return result


def load_synonym_map(path: Path) -> dict[str, list[str]]:
    """
    Parse a synonym group file into a root → synonyms mapping.

    Expected format (one group per line)::

        keyword:synonym1,synonym2,synonym3
        engine:core,processor,runtime,kernel
        cloud:sky,vapor,nimbus,stratus,nebula

    Alternate separators ``|`` and ``;`` are also accepted.
    Lines starting with ``#`` and blank lines are ignored.

    Args:
        path: Path to ``synonyms.txt`` or similar file.

    Returns:
        Dict mapping root word to list of synonyms.
        Empty dict if the file cannot be read.
    """
    if not path.exists():
        log.warning("Synonym file not found: %s", path)
        return {}

    groups: dict[str, list[str]] = {}

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Split on the first colon to get root : synonyms
            if ":" not in line:
                continue

            root, rest = line.split(":", 1)
            root = root.strip().lower()

            # Synonyms may be separated by commas, pipes, or semicolons
            syns = [
                s.strip().lower()
                for s in re.split(r"[,|;]", rest)
                if s.strip()
            ]
            if root and syns:
                if root in groups:
                    # Extend with new entries not already present
                    existing = set(groups[root])
                    groups[root].extend(s for s in syns if s not in existing)
                else:
                    groups[root] = syns

    except OSError as exc:
        log.error("Cannot read synonym file %s: %s", path, exc)

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATASET HEALTH REPORT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DatasetEntry:
    """Status of a single dataset file."""
    name:    str
    path:    Path
    exists:  bool
    entries: int
    note:    str = ""

    @property
    def ok(self) -> bool:
        return self.exists and self.entries > 0


@dataclass
class DatasetHealth:
    """
    Integrity report for all registered dataset files.

    Produced by :func:`dataset_health` and consumed by the boot sequence.
    """
    entries: list[DatasetEntry] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(e.ok for e in self.entries if e.note != "optional")

    @property
    def total_words(self) -> int:
        return sum(e.entries for e in self.entries)

    @property
    def missing(self) -> list[str]:
        return [e.name for e in self.entries if not e.exists and e.note != "optional"]

    @property
    def empty(self) -> list[str]:
        return [e.name for e in self.entries if e.exists and e.entries == 0]

    def summary(self) -> str:
        ok_count = sum(1 for e in self.entries if e.ok)
        total    = len(self.entries)
        words    = self.total_words
        return (
            f"{ok_count}/{total} datasets OK  ·  "
            f"{words:,} total entries"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  DATASET REGISTRY  (process-level singleton)
# ─────────────────────────────────────────────────────────────────────────────

class _DatasetRegistry:
    """
    Process-level singleton that holds all loaded dataset data.

    Datasets are loaded lazily on first access and cached for the process
    lifetime.  Use :func:`reset_registry` to clear the cache (tests only).

    Thread safety:
        Each dataset has its own ``threading.Lock``.  The first thread to
        request a dataset loads it; subsequent threads receive the cached
        value immediately after the lock is released.
    """

    def __init__(self) -> None:
        self._data:  dict[str, Any]            = {}
        self._locks: dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
        return self._locks[key]

    def get_wordlist(self, path: Path, key: Optional[str] = None) -> list[str]:
        """Return (possibly cached) wordlist for *path*."""
        cache_key = key or str(path)
        lock = self._lock_for(cache_key)
        with lock:
            if cache_key not in self._data:
                self._data[cache_key] = load_wordlist(path)
        return self._data[cache_key]  # type: ignore[return-value]

    def get_synonym_map(self, path: Path) -> dict[str, list[str]]:
        """Return (possibly cached) synonym map for *path*."""
        cache_key = f"__syn__{path}"
        lock = self._lock_for(cache_key)
        with lock:
            if cache_key not in self._data:
                self._data[cache_key] = load_synonym_map(path)
        return self._data[cache_key]  # type: ignore[return-value]

    def get_frozenset(self, path: Path, extra: frozenset[str] = frozenset()) -> frozenset[str]:
        """Return (possibly cached) frozenset for *path* merged with *extra*."""
        cache_key = f"__fs__{path}"
        lock = self._lock_for(cache_key)
        with lock:
            if cache_key not in self._data:
                words = load_wordlist(path)
                self._data[cache_key] = frozenset(words) | extra
        return self._data[cache_key]  # type: ignore[return-value]

    def reset(self) -> None:
        """Clear all cached data.  Use only in tests."""
        with self._meta_lock:
            self._data.clear()
            self._locks.clear()


#: Module-level singleton — import directly when needed
_registry = _DatasetRegistry()


# ─────────────────────────────────────────────────────────────────────────────
# § 4  CONVENIENT PUBLIC ACCESSORS
# ─────────────────────────────────────────────────────────────────────────────

def common_words() -> frozenset[str]:
    """
    Return the common English word filter as a frozenset.

    Source: ``nexagen/datasets/common_words.txt``  (1,229 entries)

    Any generated name that appears in this set is flagged as a plain
    dictionary word and penalised on uniqueness scoring.
    """
    return _registry.get_frozenset(DS_COMMON_WORDS)


def blacklist() -> frozenset[str]:
    """
    Return the brand protection blacklist as a frozenset.

    Merges:
      1. ``nexagen/datasets/brand_blacklist.txt``  (365 entries)
      2. ``BRAND_BLACKLIST_SEED`` from ``config/constants.py`` (45 entries)

    Any generated name within Levenshtein distance 2 of an entry here
    triggers a HIGH trademark risk flag.
    """
    return _registry.get_frozenset(DS_BRAND_BLACKLIST, extra=BRAND_BLACKLIST_SEED)


def synonyms() -> dict[str, list[str]]:
    """
    Return the full synonym group map.

    Source: ``nexagen/datasets/synonyms.txt``  (324 groups)
    Format: ``{root: [syn1, syn2, ...]}``
    """
    return _registry.get_synonym_map(DS_SYNONYMS)


def tech_terms() -> list[str]:
    """
    Return technology vocabulary list.

    Source: ``nexagen/datasets/tech_terms.txt``  (302 terms)
    """
    return _registry.get_wordlist(DS_TECH_TERMS, "tech")


def ai_terms() -> list[str]:
    """
    Return AI / ML vocabulary list.

    Source: ``nexagen/datasets/ai_terms.txt``  (150 terms)
    """
    return _registry.get_wordlist(DS_AI_TERMS, "ai")


def business_terms() -> list[str]:
    """
    Return business / finance vocabulary list.

    Source: ``nexagen/datasets/business_terms.txt``  (226 terms)
    """
    return _registry.get_wordlist(DS_BUSINESS_TERMS, "business")


def prefixes() -> list[str]:
    """
    Return domain prefix list.

    Source: ``nexagen/datasets/prefixes.txt``  (62 entries)
    These are prepended to brand names for domain variant generation,
    e.g. ``get`` → ``getnexagen.com``.
    """
    return _registry.get_wordlist(DS_PREFIXES, "prefixes") or [
        "get", "use", "try", "my", "the", "go", "run", "build",
        "open", "free", "fast", "smart", "pro", "next", "meta",
    ]


def suffixes() -> list[str]:
    """
    Return domain suffix / word-suffix list.

    Source: ``nexagen/datasets/suffixes.txt``  (129 entries)
    Used both as word suffixes (nexagenhub) and domain suffixes
    (nexagen.hub.com).
    """
    return _registry.get_wordlist(DS_SUFFIXES, "suffixes") or [
        "hub", "lab", "io", "ai", "ly", "fy", "ify", "er",
        "ops", "base", "kit", "desk", "flow", "forge",
    ]


def tlds() -> list[str]:
    """
    Return ranked TLD list.

    Source: ``nexagen/datasets/tlds.txt``  (40 entries)
    Ordered by desirability for tech/SaaS products.
    """
    return _registry.get_wordlist(DS_TLDS, "tlds") or [
        "com", "io", "co", "ai", "dev", "app", "tech",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PROFILE VOCABULARY MAPPING
# ─────────────────────────────────────────────────────────────────────────────

def vocab_for_profile(profile: str) -> list[str]:
    """
    Return the vocabulary list most relevant to the given industry profile.

    Mapping:
      tech       → tech_terms (302 terms)
      ai         → ai_terms (150 terms)
      security   → tech_terms  (tech vocabulary, security use-case)
      finance    → business_terms (226 terms)
      health     → business_terms
      social     → business_terms
      education  → business_terms
      document   → business_terms
      generic    → tech_terms + business_terms (all vocabularies)

    If the profile is unrecognised, the full combined vocabulary is returned.

    Args:
        profile: Profile value string (e.g. ``"ai"``, ``"tech"``).

    Returns:
        Deduplicated list of lowercase vocabulary words.
    """
    _t = tech_terms()
    _b = business_terms()
    _a = ai_terms()

    mapping: dict[str, list[str]] = {
        Profile.TECH.value:      _t,
        Profile.AI.value:        _a,
        Profile.SECURITY.value:  _t,
        Profile.FINANCE.value:   _b,
        Profile.HEALTH.value:    _b,
        Profile.SOCIAL.value:    _b,
        Profile.EDUCATION.value: _b,
        Profile.DOCUMENT.value:  _b,
        Profile.GENERIC.value:   _t + _b,
    }

    base = mapping.get(profile, _t + _b)

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for w in base:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# § 6  EAGER LOAD + HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

#: All registered datasets with their paths and optional flag
_DATASET_MANIFEST: list[tuple[str, Path, str]] = [
    ("common_words",    DS_COMMON_WORDS,    "required"),
    ("synonyms",        DS_SYNONYMS,        "required"),
    ("tech_terms",      DS_TECH_TERMS,      "required"),
    ("ai_terms",        DS_AI_TERMS,        "required"),
    ("business_terms",  DS_BUSINESS_TERMS,  "required"),
    ("prefixes",        DS_PREFIXES,        "required"),
    ("suffixes",        DS_SUFFIXES,        "required"),
    ("tlds",            DS_TLDS,            "required"),
    ("brand_blacklist", DS_BRAND_BLACKLIST, "optional"),
]


def load_all() -> DatasetHealth:
    """
    Eagerly load every dataset file and return a health report.

    Called by the boot sequence to pre-warm all caches and surface any
    missing or empty files before generation begins.

    Returns:
        :class:`DatasetHealth` instance with per-file status.
    """
    entries: list[DatasetEntry] = []

    for name, path, note in _DATASET_MANIFEST:
        if name == "synonyms":
            data = _registry.get_synonym_map(path)
            count = len(data)
        elif name == "brand_blacklist":
            data_list = load_wordlist(path)
            count = len(data_list)
            # Also prime the merged frozenset cache
            _registry.get_frozenset(path, extra=BRAND_BLACKLIST_SEED)
        else:
            data_list = _registry.get_wordlist(path, name)
            count = len(data_list)

        entry = DatasetEntry(
            name    = name,
            path    = path,
            exists  = path.exists(),
            entries = count,
            note    = note,
        )
        entries.append(entry)

        if not entry.ok:
            if not entry.exists:
                log.warning("Dataset missing: %s (%s)", name, path)
            elif entry.entries == 0:
                log.warning("Dataset empty: %s (%s)", name, path)

    health = DatasetHealth(entries=entries)
    log.info("Dataset load complete: %s", health.summary())
    return health


def dataset_health() -> DatasetHealth:
    """
    Return a health report without triggering any loads.

    Checks file existence and reads entry counts from the registry cache
    where available, or from disk otherwise.  Use :func:`load_all` if
    you want to guarantee all files are actually read into memory.

    Returns:
        :class:`DatasetHealth` instance.
    """
    entries: list[DatasetEntry] = []

    for name, path, note in _DATASET_MANIFEST:
        cache_key = f"__syn__{path}" if name == "synonyms" else name
        cached    = _registry._data.get(cache_key)

        if cached is not None:
            count = len(cached)
        elif path.exists():
            # Quick scan without caching
            try:
                count = sum(
                    1 for ln in path.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                )
            except OSError:
                count = 0
        else:
            count = 0

        entries.append(DatasetEntry(
            name    = name,
            path    = path,
            exists  = path.exists(),
            entries = count,
            note    = note,
        ))

    return DatasetHealth(entries=entries)


def reset_registry() -> None:
    """
    Clear all cached dataset data.

    Intended for use in tests when dataset files are swapped out between
    test cases.  Not safe to call while other threads are reading datasets.
    """
    _registry.reset()


# ─────────────────────────────────────────────────────────────────────────────
# § 7  WORDFILTER SINGLETON  (validator hook)
# ─────────────────────────────────────────────────────────────────────────────

class WordFilter:
    """
    Frozenset-backed common-word filter.

    Used by :func:`~nexagen.utils.validators.validate_common_word` as the
    default word set when no explicit ``common_words`` argument is passed.

    Example::

        from nexagen.utils.dataset_loader import WordFilter
        wf = WordFilter()
        wf.is_common("cloud")   # → True
        wf.is_common("nexagen") # → False

    The underlying frozenset is loaded lazily from ``common_words.txt``
    and shared with the global registry cache.
    """

    _instance: Optional["WordFilter"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "WordFilter":
        # Simple singleton — one WordFilter per process
        with cls._lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._words: frozenset[str] = frozenset()
                obj._loaded = False
                cls._instance = obj
        return cls._instance

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    self._words = common_words()
                    self._loaded = True

    def contains(self, word: str) -> bool:
        """Return True if *word* is in the common-word filter."""
        self._ensure_loaded()
        return word.strip().lower() in self._words

    # Alias used in validators.py comment
    is_common = contains

    @property
    def words(self) -> frozenset[str]:
        """The underlying frozenset of common words."""
        self._ensure_loaded()
        return self._words

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._words)

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return self.contains(item)


# ─────────────────────────────────────────────────────────────────────────────
# § 8  SYNONYMMAP SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

class SynonymMap:
    """
    Parsed synonym groups with lookup and expansion helpers.

    Example::

        from nexagen.utils.dataset_loader import SynonymMap
        sm = SynonymMap()
        sm.get("cloud")        # → ['sky', 'vapor', 'nimbus', ...]
        sm.expand(["engine"])  # → ['engine', 'core', 'processor', ...]

    Loaded once and shared via the registry cache.
    """

    _instance: Optional["SynonymMap"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SynonymMap":
        with cls._lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._map: dict[str, list[str]] = {}
                obj._loaded = False
                cls._instance = obj
        return cls._instance

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    self._map   = synonyms()
                    self._loaded = True

    def get(self, word: str) -> list[str]:
        """
        Return synonyms for *word*, or an empty list if none are registered.
        """
        self._ensure_loaded()
        return self._map.get(word.strip().lower(), [])

    def expand(
        self,
        words: list[str],
        depth: int = 1,
        max_per_seed: int = 6,
    ) -> list[str]:
        """
        Expand *words* by appending synonyms up to *depth* levels.

        Args:
            words:        Seed word list.
            depth:        How many expansion rounds to run (1 = one hop).
            max_per_seed: Maximum synonyms appended per seed word.

        Returns:
            Deduplicated expanded list (seeds first, then expansions).
        """
        self._ensure_loaded()
        seen: set[str]  = set(words)
        result: list[str] = list(words)
        frontier = list(words)

        for _ in range(depth):
            new_frontier: list[str] = []
            for w in frontier:
                for syn in self._map.get(w, [])[:max_per_seed]:
                    if syn not in seen:
                        seen.add(syn)
                        result.append(syn)
                        new_frontier.append(syn)
            frontier = new_frontier
            if not frontier:
                break

        return result

    @property
    def groups(self) -> dict[str, list[str]]:
        """The underlying synonym group mapping."""
        self._ensure_loaded()
        return self._map

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._map)


# ─────────────────────────────────────────────────────────────────────────────
# § 9  BRANDBLACKLIST SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

class BrandBlacklist:
    """
    Merged brand protection blacklist with proximity detection helpers.

    Merges ``brand_blacklist.txt`` (365 entries) with ``BRAND_BLACKLIST_SEED``
    (45 entries) from ``constants.py`` into a single frozenset.

    Example::

        from nexagen.utils.dataset_loader import BrandBlacklist
        bl = BrandBlacklist()
        bl.is_protected("google")    # → True (exact)
        bl.risk_level("gooogle")     # → "high"  (distance=1)
        bl.risk_level("nexagen")     # → "none"

    """

    _instance: Optional["BrandBlacklist"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "BrandBlacklist":
        with cls._lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._brands: frozenset[str] = frozenset()
                obj._loaded = False
                cls._instance = obj
        return cls._instance

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    self._brands = blacklist()
                    self._loaded = True

    def is_protected(self, name: str) -> bool:
        """Return True if *name* is an exact match in the blacklist."""
        self._ensure_loaded()
        return name.strip().lower() in self._brands

    def risk_level(self, name: str, *, low: int = 3, medium: int = 2) -> str:
        """
        Return a trademark risk level string for *name*.

        Uses Levenshtein distance against all blacklisted brands.

        Returns:
            ``"none"``    — no brand within distance *low*
            ``"low"``     — closest brand is within distance *low*
            ``"medium"``  — closest brand is within distance *medium*
            ``"high"``    — closest brand is within distance 1 or exact
        """
        from .levenshtein import levenshtein
        self._ensure_loaded()

        name_lower = name.strip().lower()
        min_dist   = min(
            (levenshtein(name_lower, b) for b in self._brands),
            default=999,
        )

        if min_dist == 0:
            return "high"
        if min_dist <= 1:
            return "high"
        if min_dist <= medium:
            return "medium"
        if min_dist <= low:
            return "low"
        return "none"

    @property
    def brands(self) -> frozenset[str]:
        """The underlying frozenset of protected brand names."""
        self._ensure_loaded()
        return self._brands

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._brands)

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return self.is_protected(item)
