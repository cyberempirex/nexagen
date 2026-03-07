"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  engine/pattern_engine.py  ·  Brand name candidate generation               ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Turns an expanded seed pool (from SynonymEngine) into a large, diverse set
of brand name candidates.  Each candidate carries metadata about which
strategy produced it — useful for filtering, debugging, and analysis.

Generation strategies
─────────────────────
  1  DIRECT       — seeds that already meet length requirements
  2  PREFIX       — prefix + seed (e.g. "getdata", "openflow")
  3  SUFFIX       — seed + suffix (e.g. "datahub", "flowbase")
  4  COMPOUND     — seed + seed concatenation (e.g. "cloudstream")
  5  BLEND        — portmanteau of two seeds (e.g. "nexagen")
  6  MUTATION     — vowel-drop, consonant swap (e.g. "datx", "flwio")
  7  POWER_ENDING — seed stripped of vowels + power suffix (-ex, -ix, -on)
  8  SOFT_ENDING  — seed + soft suffix (-ly, -fy, -io, -al, -ara)
  9  TRUNCATE     — shortened form (e.g. "datacenter" → "datacen")
  10 ACRONYM      — initials of multi-word seeds (e.g. "nexio")

Style mode routing
──────────────────
  Each style mode enables/disables specific strategies and applies
  strategy-specific length preferences:

  minimal     → DIRECT, PREFIX, SUFFIX, TRUNCATE (short names, 4–6 chars)
  futuristic  → DIRECT, POWER_ENDING, MUTATION, BLEND (sci-fi -ex/-on feel)
  aggressive  → DIRECT, COMPOUND, POWER_ENDING, PREFIX (hard, strong)
  soft        → DIRECT, SOFT_ENDING, SUFFIX, BLEND (vowel endings)
  technical   → DIRECT, PREFIX, SUFFIX, COMPOUND, ACRONYM
  luxury      → DIRECT, TRUNCATE, BLEND, POWER_ENDING (short, premium)

Public API
──────────
  PatternEngine.generate(seeds, cfg)          → GenerationResult
  generate_candidates(seeds, cfg)             → list[str]  (simple)

Data structures
───────────────
  Candidate       — name + strategy + source seeds + score
  GenerationResult — full output with per-strategy breakdown
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config.constants import (
    GEN_MAX_CANDIDATES,
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    VOWELS,
    StyleMode,
)
from ..config.settings import Settings, get_settings
from ..utils.dataset_loader import prefixes as load_prefixes
from ..utils.dataset_loader import suffixes as load_suffixes
from ..utils.text_utils import (
    blend_words,
    has_forbidden_sequence,
    is_pronounceable,
    starts_with_strong_consonant,
    strip_non_alpha,
    truncate_name,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  STRATEGY CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

STRAT_DIRECT       = "direct"
STRAT_PREFIX       = "prefix"
STRAT_SUFFIX       = "suffix"
STRAT_COMPOUND     = "compound"
STRAT_BLEND        = "blend"
STRAT_MUTATION     = "mutation"
STRAT_POWER_ENDING = "power_ending"
STRAT_SOFT_ENDING  = "soft_ending"
STRAT_TRUNCATE     = "truncate"
STRAT_ACRONYM      = "acronym"

# Power endings — futuristic / aggressive sound
_POWER_ENDINGS = ("ex", "ix", "on", "en", "al", "ar", "ax", "or", "um", "us")

# Soft endings — approachable / modern sound
_SOFT_ENDINGS = ("ly", "fy", "ify", "io", "la", "ra", "ia", "aya", "ela", "ova")

# Style → enabled strategies (ordered by priority)
_STYLE_STRATEGIES: dict[str, list[str]] = {
    StyleMode.MINIMAL.value:    [
        STRAT_DIRECT, STRAT_PREFIX, STRAT_SUFFIX, STRAT_TRUNCATE, STRAT_BLEND,
    ],
    StyleMode.FUTURISTIC.value: [
        STRAT_DIRECT, STRAT_POWER_ENDING, STRAT_MUTATION, STRAT_BLEND,
        STRAT_PREFIX, STRAT_TRUNCATE,
    ],
    StyleMode.AGGRESSIVE.value: [
        STRAT_DIRECT, STRAT_COMPOUND, STRAT_POWER_ENDING, STRAT_PREFIX,
        STRAT_MUTATION, STRAT_BLEND,
    ],
    StyleMode.SOFT.value: [
        STRAT_DIRECT, STRAT_SOFT_ENDING, STRAT_SUFFIX, STRAT_BLEND,
        STRAT_PREFIX, STRAT_COMPOUND,
    ],
    StyleMode.TECHNICAL.value: [
        STRAT_DIRECT, STRAT_PREFIX, STRAT_SUFFIX, STRAT_COMPOUND,
        STRAT_ACRONYM, STRAT_POWER_ENDING, STRAT_BLEND,
    ],
    StyleMode.LUXURY.value: [
        STRAT_DIRECT, STRAT_TRUNCATE, STRAT_BLEND, STRAT_POWER_ENDING,
        STRAT_SOFT_ENDING,
    ],
}

# Default (all strategies)
_ALL_STRATEGIES = [
    STRAT_DIRECT, STRAT_PREFIX, STRAT_SUFFIX, STRAT_COMPOUND,
    STRAT_BLEND, STRAT_MUTATION, STRAT_POWER_ENDING, STRAT_SOFT_ENDING,
    STRAT_TRUNCATE, STRAT_ACRONYM,
]

# Style → preferred length range
_STYLE_LENGTH: dict[str, tuple[int, int]] = {
    StyleMode.MINIMAL.value:    (4, 7),
    StyleMode.FUTURISTIC.value: (4, 8),
    StyleMode.AGGRESSIVE.value: (5, 9),
    StyleMode.SOFT.value:       (5, 9),
    StyleMode.TECHNICAL.value:  (5, 10),
    StyleMode.LUXURY.value:     (4, 6),
}


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """
    A single brand name candidate with full provenance metadata.

    Attributes:
        name:     Lowercase alphabetic name string.
        strategy: Which strategy produced this name (STRAT_* constant).
        sources:  Seed words used to generate this name.
        quality:  Quick quality indicator 0–3:
                    0 = may have issues
                    1 = acceptable
                    2 = good (no forbidden sequences, pronounceable)
                    3 = excellent (also ideal length, strong opening)
    """
    name:     str
    strategy: str
    sources:  list[str] = field(default_factory=list)
    quality:  int        = 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Candidate):
            return self.name == other.name
        return False


@dataclass
class GenerationResult:
    """
    Complete output of a pattern generation run.

    Attributes:
        candidates:    All unique Candidate objects, best first.
        by_strategy:   Breakdown of candidates grouped by strategy.
        names:         Plain list of name strings (same order as candidates).
        total:         Total unique candidates before any scoring/filtering.
        strategy_counts: {strategy: count} dict.
    """
    candidates:      list[Candidate]
    by_strategy:     dict[str, list[Candidate]] = field(default_factory=dict)
    names:           list[str]                  = field(default_factory=list)
    total:           int                        = 0
    strategy_counts: dict[str, int]             = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.names = [c.name for c in self.candidates]
        self.total = len(self.candidates)
        for c in self.candidates:
            self.by_strategy.setdefault(c.strategy, []).append(c)
            self.strategy_counts[c.strategy] = \
                self.strategy_counts.get(c.strategy, 0) + 1

    def top(self, n: int = 50) -> list[Candidate]:
        """Return top-N candidates."""
        return self.candidates[:n]


# ─────────────────────────────────────────────────────────────────────────────
# § 3  QUALITY SCORER
# ─────────────────────────────────────────────────────────────────────────────

def _quality(name: str, min_len: int, max_len: int) -> int:
    """
    Fast 0–3 quality indicator without full scoring.

    0 = has a forbidden sequence or not pronounceable
    1 = no forbidden sequences but not ideal
    2 = pronounceable and within length bounds
    3 = pronounceable + ideal length + strong opening consonant
    """
    if has_forbidden_sequence(name):
        return 0
    if not is_pronounceable(name):
        return 1
    if min_len <= len(name) <= max_len:
        if starts_with_strong_consonant(name):
            return 3
        return 2
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# § 4  GENERATION STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def _clean(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())


def _fits(name: str, min_l: int, max_l: int) -> bool:
    return (
        name.isalpha()
        and min_l <= len(name) <= max_l
    )


def _strat_direct(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    for s in seeds:
        if _fits(s, min_l, max_l):
            out.append(Candidate(name=s, strategy=STRAT_DIRECT, sources=[s]))
    return out


def _strat_prefix(
    seeds: list[str], pfx_list: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    for seed in seeds[:25]:
        for pre in pfx_list[:20]:
            combo = pre + seed
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_PREFIX, sources=[pre, seed]))
    return out


def _strat_suffix(
    seeds: list[str], suf_list: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    for seed in seeds[:25]:
        for suf in suf_list[:25]:
            combo = seed + suf
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_SUFFIX, sources=[seed, suf]))
    return out


def _strat_compound(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    for i, a in enumerate(seeds[:20]):
        for b in seeds[i + 1: i + 10]:
            if a == b:
                continue
            combo = a + b
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_COMPOUND, sources=[a, b]))
    return out


def _strat_blend(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    out: list[Candidate] = []
    for i, a in enumerate(seeds[:15]):
        for b in seeds[i + 1: i + 8]:
            if a == b or len(a) < 2 or len(b) < 2:
                continue
            for blend in blend_words(a, b):
                w = _clean(blend)
                if w and _fits(w, min_l, max_l):
                    out.append(Candidate(name=w, strategy=STRAT_BLEND, sources=[a, b]))
    return out


def _strat_mutation(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    """Drop interior vowels to create punchy variants."""
    out: list[Candidate] = []
    for seed in seeds[:15]:
        if len(seed) < 5:
            continue
        # Remove first internal vowel
        for i in range(1, len(seed) - 1):
            if seed[i] in VOWELS:
                mutant = seed[:i] + seed[i + 1:]
                if mutant.isalpha() and _fits(mutant, min_l, max_l):
                    out.append(Candidate(name=mutant, strategy=STRAT_MUTATION, sources=[seed]))
                break
        # Replace last vowel with 'x'
        for i in range(len(seed) - 1, 0, -1):
            if seed[i] in VOWELS:
                mutant = seed[:i] + "x" + seed[i + 1:]
                if mutant.isalpha() and _fits(mutant, min_l, max_l):
                    out.append(Candidate(name=mutant, strategy=STRAT_MUTATION, sources=[seed]))
                break
    return out


def _strat_power_ending(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    """Strip trailing vowels and append power endings."""
    out: list[Candidate] = []
    for seed in seeds[:20]:
        base = seed.rstrip("aeiou") or seed
        for ending in _POWER_ENDINGS:
            combo = base + ending
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_POWER_ENDING, sources=[seed]))
    return out


def _strat_soft_ending(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    """Append soft / vowel endings to create approachable names."""
    out: list[Candidate] = []
    for seed in seeds[:20]:
        base = seed.rstrip("aeiou") or seed
        for ending in _SOFT_ENDINGS:
            combo = base + ending
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_SOFT_ENDING, sources=[seed]))
    return out


def _strat_truncate(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    """Shorten long seeds to a clean truncated form."""
    out: list[Candidate] = []
    for seed in seeds[:20]:
        if len(seed) <= max_l:
            continue
        trunc = truncate_name(seed, max_l)
        if trunc and _fits(trunc, min_l, max_l):
            out.append(Candidate(name=trunc, strategy=STRAT_TRUNCATE, sources=[seed]))
    return out


def _strat_acronym(
    seeds: list[str], min_l: int, max_l: int,
) -> list[Candidate]:
    """
    Build acronym-like names from initial letters of seed combinations.
    For 2–4 seeds, concatenate initials and try suffix expansions.
    """
    out: list[Candidate] = []
    if len(seeds) < 2:
        return out

    for n in (2, 3, 4):
        group = seeds[:n]
        acro  = "".join(s[0] for s in group)
        if _fits(acro, min_l, max_l):
            out.append(Candidate(name=acro, strategy=STRAT_ACRONYM, sources=group))
        # Acronym + common endings
        for ending in ("io", "ex", "al", "on", "ix"):
            combo = acro + ending
            if _fits(combo, min_l, max_l):
                out.append(Candidate(name=combo, strategy=STRAT_ACRONYM, sources=group))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PATTERN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class PatternEngine:
    """
    Brand name candidate generator using 10 linguistic strategies.

    Usage::

        from nexagen.engine.pattern_engine import PatternEngine
        engine = PatternEngine()
        result = engine.generate(expanded_seeds, cfg)
        names  = result.names[:50]

    The engine is stateless — safe to reuse across calls.
    """

    def generate(
        self,
        seeds:   Sequence[str],
        cfg:     Optional[Settings] = None,
        *,
        max_candidates: int = GEN_MAX_CANDIDATES,
    ) -> GenerationResult:
        """
        Generate brand name candidates from a seed pool.

        Args:
            seeds:          Expanded seed word pool (from SynonymEngine or
                            _expand_keywords in commands.py).
            cfg:            Active Settings — controls style, length range,
                            prefix/suffix use, and multiword mode.
            max_candidates: Hard cap on total candidates before dedup.

        Returns:
            :class:`GenerationResult` with candidates sorted by quality desc.
        """
        if cfg is None:
            cfg = get_settings()

        seed_list = [_clean(s) for s in seeds if _clean(s) and len(_clean(s)) >= 2]

        # Length range — use settings, but clamp to hard limits
        min_l = max(cfg.min_len, NAME_LENGTH_HARD_MIN)
        max_l = min(cfg.max_len, NAME_LENGTH_HARD_MAX)

        # Style-specific length preferences (tighten the window)
        style_range = _STYLE_LENGTH.get(cfg.style_mode)
        if style_range:
            min_l = max(min_l, style_range[0])
            max_l = min(max_l, style_range[1])

        # Active strategies for this style
        active_strategies = _STYLE_STRATEGIES.get(cfg.style_mode, _ALL_STRATEGIES)

        pfx_list = load_prefixes() if cfg.use_prefixes else []
        suf_list = load_suffixes() if cfg.use_suffixes else []

        # ── Run strategies ────────────────────────────────────────────────────
        all_candidates: list[Candidate] = []

        strategy_fns: dict[str, object] = {
            STRAT_DIRECT:       lambda: _strat_direct(seed_list, min_l, max_l),
            STRAT_PREFIX:       lambda: _strat_prefix(seed_list, pfx_list, min_l, max_l),
            STRAT_SUFFIX:       lambda: _strat_suffix(seed_list, suf_list, min_l, max_l),
            STRAT_COMPOUND:     lambda: (
                _strat_compound(seed_list, min_l, max_l) if cfg.use_multiword else []
            ),
            STRAT_BLEND:        lambda: _strat_blend(seed_list, min_l, max_l),
            STRAT_MUTATION:     lambda: _strat_mutation(seed_list, min_l, max_l),
            STRAT_POWER_ENDING: lambda: _strat_power_ending(seed_list, min_l, max_l),
            STRAT_SOFT_ENDING:  lambda: _strat_soft_ending(seed_list, min_l, max_l),
            STRAT_TRUNCATE:     lambda: _strat_truncate(seed_list, min_l, max_l),
            STRAT_ACRONYM:      lambda: _strat_acronym(seed_list, min_l, max_l),
        }

        for strat in active_strategies:
            fn = strategy_fns.get(strat)
            if fn:
                batch = fn()  # type: ignore[call-arg]
                all_candidates.extend(batch)
            if len(all_candidates) >= max_candidates * 2:
                break

        # ── Deduplicate by name ───────────────────────────────────────────────
        seen_names: set[str] = set()
        unique: list[Candidate] = []
        for c in all_candidates:
            if c.name not in seen_names:
                seen_names.add(c.name)
                unique.append(c)

        # ── Score quality ─────────────────────────────────────────────────────
        for c in unique:
            c.quality = _quality(c.name, min_l, max_l)

        # ── Sort: quality DESC, strategy priority, then alpha ─────────────────
        strat_order = {s: i for i, s in enumerate(active_strategies)}
        unique.sort(key=lambda c: (
            -c.quality,
            strat_order.get(c.strategy, 99),
            c.name,
        ))

        final = unique[:max_candidates]

        return GenerationResult(candidates=final)

    def generate_names_only(
        self,
        seeds:   Sequence[str],
        cfg:     Optional[Settings] = None,
        count:   int               = 50,
    ) -> list[str]:
        """
        Generate and return a plain list of name strings.

        Convenience wrapper around :meth:`generate`.

        Args:
            seeds:  Expanded seed words.
            cfg:    Active Settings.
            count:  Maximum names to return.

        Returns:
            List of lowercase name strings.
        """
        result = self.generate(seeds, cfg)
        return result.names[:count]


# ─────────────────────────────────────────────────────────────────────────────
# § 6  SIMPLE FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def generate_candidates(
    seeds: Sequence[str],
    cfg:   Optional[Settings] = None,
    *,
    max_candidates: int = GEN_MAX_CANDIDATES,
) -> list[str]:
    """
    Generate brand name candidates and return a plain list of strings.

    Simple interface for callers that don't need Candidate metadata.

    Args:
        seeds:          Expanded seed words.
        cfg:            Active Settings.
        max_candidates: Maximum candidates to return.

    Returns:
        Deduplicated list of lowercase name strings, quality-sorted.
    """
    engine = PatternEngine()
    result = engine.generate(seeds, cfg, max_candidates=max_candidates)
    return result.names
