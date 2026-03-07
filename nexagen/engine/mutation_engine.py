"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  engine/mutation_engine.py  ·  Linguistic mutation strategies               ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Applies systematic linguistic mutations to a seed word pool to produce
brand name variants that retain the feel of the original but are more
distinctive, memorable, or domain-available.

Relationship to PatternEngine
──────────────────────────────
  PatternEngine runs macro-level strategies (PREFIX, SUFFIX, COMPOUND…)
  that combine whole words.  MutationEngine works at the character and
  phoneme level on individual words — it goes deeper, not wider.

  PatternEngine.Candidate and MutationEngine.MutatedCandidate both feed
  into NameGenerator's unified scoring pipeline.

Mutation strategies  (12 total)
────────────────────────────────
  VOWEL_DROP     — remove one interior vowel             "data"  → "dta"
  VOWEL_REPLACE  — swap a vowel for another              "nexus" → "noxus"
  CONSONANT_SWAP — replace a consonant with phonetic near "kore"  → "core"
  PHONEME_SUB    — multi-char phoneme substitution       "phone" → "fone"
  POWER_ENDING   — strip trailing vowels + power suffix  "cloud" → "cloudex"
  SOFT_ENDING    — vowel-softened suffix                 "data"  → "datalia"
  LETTER_DOUBLE  — double a strong consonant             "nova"  → "novva"
  SYLLABLE_DROP  — remove weakest syllable from long words
  INITIAL_SHIFT  — change opening consonant cluster      "base"  → "vase"/"dase"
  X_INFUSION     — inject 'x' or 'z' for modern feel    "core"  → "xcore"/"corex"
  REVERSE_BLEND  — end of A + start of B                "data"+"flow" → "taflow"
  COMPRESS       — consonant cluster compression         "cloud" → "clud"

Style-mode routing (same system as PatternEngine)
──────────────────────────────────────────────────
  minimal     → VOWEL_DROP, COMPRESS, SYLLABLE_DROP
  futuristic  → POWER_ENDING, X_INFUSION, PHONEME_SUB, CONSONANT_SWAP
  aggressive  → POWER_ENDING, CONSONANT_SWAP, INITIAL_SHIFT, LETTER_DOUBLE
  soft        → SOFT_ENDING, VOWEL_REPLACE, VOWEL_DROP
  technical   → PHONEME_SUB, COMPRESS, POWER_ENDING, SYLLABLE_DROP
  luxury      → VOWEL_REPLACE, SOFT_ENDING, COMPRESS

Public API
──────────
  MutationEngine.apply(seeds, cfg)              → MutationResult
  MutationEngine.apply_one(word, strategies)    → list[MutatedCandidate]
  apply_mutations(seeds, cfg)                   → list[str]  (simple)

Data structures
───────────────
  MutatedCandidate  — name + strategy + source + fitness flag
  MutationResult    — full output with per-strategy breakdown and stats
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config.constants import (
    CONSONANTS,
    FORBIDDEN_SEQUENCES,
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    RARE_CONSONANTS,
    STRONG_START_CONSONANTS,
    VOWELS,
    StyleMode,
)
from ..config.settings import Settings, get_settings
from ..utils.text_utils import (
    has_forbidden_sequence,
    is_pronounceable,
    starts_with_strong_consonant,
)

# Re-export strategy constants from pattern_engine for shared use
from .pattern_engine import (
    STRAT_MUTATION,
    STRAT_POWER_ENDING,
    STRAT_SOFT_ENDING,
    _POWER_ENDINGS,
    _SOFT_ENDINGS,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  MUTATION STRATEGY CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

MUT_VOWEL_DROP    = "vowel_drop"
MUT_VOWEL_REPLACE = "vowel_replace"
MUT_CONSONANT_SWAP= "consonant_swap"
MUT_PHONEME_SUB   = "phoneme_sub"
MUT_POWER_ENDING  = STRAT_POWER_ENDING   # reuse pattern_engine constant
MUT_SOFT_ENDING   = STRAT_SOFT_ENDING    # reuse pattern_engine constant
MUT_LETTER_DOUBLE = "letter_double"
MUT_SYLLABLE_DROP = "syllable_drop"
MUT_INITIAL_SHIFT = "initial_shift"
MUT_X_INFUSION    = "x_infusion"
MUT_REVERSE_BLEND = "reverse_blend"
MUT_COMPRESS      = "compress"

# Style → active mutation strategies (ordered by priority within style)
_STYLE_MUTATIONS: dict[str, list[str]] = {
    StyleMode.MINIMAL.value:    [MUT_VOWEL_DROP, MUT_COMPRESS, MUT_SYLLABLE_DROP],
    StyleMode.FUTURISTIC.value: [MUT_POWER_ENDING, MUT_X_INFUSION, MUT_PHONEME_SUB,
                                 MUT_CONSONANT_SWAP],
    StyleMode.AGGRESSIVE.value: [MUT_POWER_ENDING, MUT_CONSONANT_SWAP,
                                 MUT_INITIAL_SHIFT, MUT_LETTER_DOUBLE],
    StyleMode.SOFT.value:       [MUT_SOFT_ENDING, MUT_VOWEL_REPLACE, MUT_VOWEL_DROP],
    StyleMode.TECHNICAL.value:  [MUT_PHONEME_SUB, MUT_COMPRESS, MUT_POWER_ENDING,
                                 MUT_SYLLABLE_DROP],
    StyleMode.LUXURY.value:     [MUT_VOWEL_REPLACE, MUT_SOFT_ENDING, MUT_COMPRESS],
}

_ALL_MUTATIONS: list[str] = [
    MUT_VOWEL_DROP, MUT_VOWEL_REPLACE, MUT_CONSONANT_SWAP, MUT_PHONEME_SUB,
    MUT_POWER_ENDING, MUT_SOFT_ENDING, MUT_LETTER_DOUBLE, MUT_SYLLABLE_DROP,
    MUT_INITIAL_SHIFT, MUT_X_INFUSION, MUT_REVERSE_BLEND, MUT_COMPRESS,
]

# ─────────────────────────────────────────────────────────────────────────────
# § 2  PHONEME SUBSTITUTION TABLES
# ─────────────────────────────────────────────────────────────────────────────

# Multi-char → single-char phoneme simplifications (left to right)
_PHONEME_SUBS: list[tuple[str, str]] = [
    ("ph", "f"),   # phone → fone
    ("ck", "k"),   # track → trak
    ("ch", "k"),   # tech  → tek
    ("qu", "k"),   # quest → kest
    ("wh", "w"),   # where → were
    ("th", "t"),   # think → tink
    ("gh", "g"),   # high  → hig
    ("tch","ch"),  # match → mach (ch already handled above)
    ("tion","shn"),# action → ackshn  (brand shorthand)
    ("ous", "us"), # porous → porus
    ("ness","ns"), # darkness → darkns
    ("ing", "ng"), # loading → loadng
]

# Vowel-for-vowel substitution map (each vowel → nearby vowels)
_VOWEL_ALTS: dict[str, list[str]] = {
    "a": ["e", "o"],
    "e": ["a", "i"],
    "i": ["e", "y"],
    "o": ["u", "a"],
    "u": ["o", "e"],
}

# Strong consonants available for CONSONANT_SWAP and INITIAL_SHIFT
_STRONG_CONSONANTS: tuple[str, ...] = ("b", "d", "f", "g", "k", "p", "r", "s", "t", "v", "z")

# Consonants to avoid introducing (too rare or awkward)
_AVOID_CONSONANTS: frozenset[str] = frozenset("qxj")


# ─────────────────────────────────────────────────────────────────────────────
# § 3  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MutatedCandidate:
    """
    A brand name variant produced by a specific mutation strategy.

    Attributes:
        name:       The mutated lowercase alphabetic name string.
        strategy:   Which mutation strategy produced this (MUT_* constant).
        source:     The seed word this was derived from.
        source_b:   Second seed word for two-word mutations (REVERSE_BLEND).
        is_valid:   Pre-checked flag: no forbidden sequences, pronounceable.
        quality:    Quick quality score 0–3 (same scale as PatternEngine.Candidate).
    """
    name:     str
    strategy: str
    source:   str
    source_b: str = ""
    is_valid: bool = True
    quality:  int  = 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MutatedCandidate) and self.name == other.name


@dataclass
class MutationResult:
    """
    Complete output of a MutationEngine.apply() run.

    Attributes:
        candidates:      All unique MutatedCandidate objects, quality-sorted.
        names:           Plain list of name strings (same order).
        by_strategy:     Candidates grouped by strategy name.
        strategy_counts: {strategy: count} summary dict.
        total:           Total unique candidates.
    """
    candidates:      list[MutatedCandidate]
    names:           list[str]                  = field(default_factory=list)
    by_strategy:     dict[str, list[MutatedCandidate]] = field(default_factory=dict)
    strategy_counts: dict[str, int]             = field(default_factory=dict)
    total:           int                        = 0

    def __post_init__(self) -> None:
        self.names = [c.name for c in self.candidates]
        self.total = len(self.candidates)
        for c in self.candidates:
            self.by_strategy.setdefault(c.strategy, []).append(c)
            self.strategy_counts[c.strategy] = \
                self.strategy_counts.get(c.strategy, 0) + 1


# ─────────────────────────────────────────────────────────────────────────────
# § 4  QUALITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clean(w: str) -> str:
    return re.sub(r"[^a-z]", "", w.lower())


def _fits(name: str, min_l: int, max_l: int) -> bool:
    return name.isalpha() and min_l <= len(name) <= max_l


def _quality(name: str, min_l: int, max_l: int) -> int:
    """Return 0–3 quality score for a mutated name."""
    if has_forbidden_sequence(name):
        return 0
    if not is_pronounceable(name):
        return 1
    if min_l <= len(name) <= max_l:
        return 3 if starts_with_strong_consonant(name) else 2
    return 1


def _make(name: str, strategy: str, source: str, min_l: int, max_l: int,
          source_b: str = "") -> Optional[MutatedCandidate]:
    """Create a MutatedCandidate only if the name passes all filters."""
    if not _fits(name, min_l, max_l):
        return None
    q = _quality(name, min_l, max_l)
    return MutatedCandidate(
        name=name,
        strategy=strategy,
        source=source,
        source_b=source_b,
        is_valid=(q > 0),
        quality=q,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  INDIVIDUAL MUTATION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _mut_vowel_drop(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Remove one interior vowel to create a tighter, punchier variant.

    Works through every interior vowel position and yields one candidate
    per removal. Preserves the first and last characters.
    """
    out: list[MutatedCandidate] = []
    if len(seed) < 5:
        return out
    for i in range(1, len(seed) - 1):
        if seed[i] in VOWELS:
            mutant = seed[:i] + seed[i + 1:]
            c = _make(mutant, MUT_VOWEL_DROP, seed, min_l, max_l)
            if c:
                out.append(c)
    return out


def _mut_vowel_replace(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Substitute each vowel with a nearby vowel for a fresh sound.

    Uses the _VOWEL_ALTS table to ensure phonetic proximity.
    """
    out: list[MutatedCandidate] = []
    for i, ch in enumerate(seed):
        if ch in _VOWEL_ALTS:
            for alt in _VOWEL_ALTS[ch]:
                mutant = seed[:i] + alt + seed[i + 1:]
                c = _make(mutant, MUT_VOWEL_REPLACE, seed, min_l, max_l)
                if c:
                    out.append(c)
    return out


def _mut_consonant_swap(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Replace the opening consonant with a phonetically strong alternative.

    Only modifies the first consonant to preserve recognisability.
    """
    out: list[MutatedCandidate] = []
    if not seed or seed[0] not in CONSONANTS:
        return out
    original = seed[0]
    for alt in _STRONG_CONSONANTS:
        if alt == original or alt in _AVOID_CONSONANTS:
            continue
        mutant = alt + seed[1:]
        c = _make(mutant, MUT_CONSONANT_SWAP, seed, min_l, max_l)
        if c:
            out.append(c)
            if len(out) >= 3:   # cap per seed to avoid explosion
                break
    return out


def _mut_phoneme_sub(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Apply phoneme-level substitutions (ph→f, ck→k, qu→k, etc.).

    Each substitution is tried independently. If the first match applies
    we yield that variant; otherwise try the next rule.
    """
    out: list[MutatedCandidate] = []
    for old, new in _PHONEME_SUBS:
        if old in seed:
            mutant = _clean(seed.replace(old, new, 1))
            c = _make(mutant, MUT_PHONEME_SUB, seed, min_l, max_l)
            if c:
                out.append(c)
    return out


def _mut_power_ending(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Strip trailing vowels and append a power suffix (-ex, -ix, -on, …).

    Matches pattern_engine._strat_power_ending but returns MutatedCandidate.
    """
    out: list[MutatedCandidate] = []
    base = seed.rstrip("aeiou") or seed
    for ending in _POWER_ENDINGS:
        mutant = base + ending
        c = _make(mutant, MUT_POWER_ENDING, seed, min_l, max_l)
        if c:
            out.append(c)
    return out


def _mut_soft_ending(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Append a soft vowel-heavy suffix (-ly, -io, -la, …) for warmth.

    Matches pattern_engine._strat_soft_ending but returns MutatedCandidate.
    """
    out: list[MutatedCandidate] = []
    base = seed.rstrip("aeiou") or seed
    for ending in _SOFT_ENDINGS:
        mutant = base + ending
        c = _make(mutant, MUT_SOFT_ENDING, seed, min_l, max_l)
        if c:
            out.append(c)
    return out


def _mut_letter_double(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Double a strong interior consonant for a bolder visual look.

    Example: "kova" → "kovva",  "dana" → "danna"
    Only doubles consonants in the _STRONG_CONSONANTS set to avoid
    creating FORBIDDEN_SEQUENCES.
    """
    out: list[MutatedCandidate] = []
    for i in range(1, len(seed) - 1):
        ch = seed[i]
        if ch in STRONG_START_CONSONANTS and ch + ch not in FORBIDDEN_SEQUENCES:
            mutant = seed[:i] + ch + seed[i:]   # inserts extra char
            c = _make(mutant, MUT_LETTER_DOUBLE, seed, min_l, max_l)
            if c:
                out.append(c)
                break   # one double per seed
    return out


def _mut_syllable_drop(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Remove the weakest (shortest) vowel-consonant syllable from a long word.

    Target: words of 8+ chars. Finds the first VC pair that can be
    removed without leaving a forbidden sequence.
    """
    out: list[MutatedCandidate] = []
    if len(seed) < 7:
        return out
    # Find a VC pair to drop (skip first and last chars)
    for i in range(1, len(seed) - 2):
        if seed[i] in VOWELS and seed[i + 1] in CONSONANTS:
            mutant = seed[:i] + seed[i + 2:]
            c = _make(mutant, MUT_SYLLABLE_DROP, seed, min_l, max_l)
            if c:
                out.append(c)
                break
    return out


def _mut_initial_shift(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Replace the entire opening consonant cluster with a different strong consonant.

    "blast" → "fast", "trak" → "vrak"
    Useful for creating related-sounding alternatives.
    """
    out: list[MutatedCandidate] = []
    # Find where the initial consonant cluster ends
    cluster_end = 0
    for i, ch in enumerate(seed):
        if ch in VOWELS:
            cluster_end = i
            break
    if cluster_end == 0 or cluster_end > 3:
        return out   # no opening cluster, or too long
    vowel_tail = seed[cluster_end:]
    for alt in _STRONG_CONSONANTS:
        mutant = alt + vowel_tail
        c = _make(mutant, MUT_INITIAL_SHIFT, seed, min_l, max_l)
        if c and mutant != seed:
            out.append(c)
            if len(out) >= 3:
                break
    return out


def _mut_x_infusion(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Inject 'x' or 'z' to give a modern, technical edge.

    Strategies tried (in order):
      - prepend 'x' (xcloud, xcore)
      - append 'x' (corex, datax) — on base without trailing vowels
      - replace last vowel with 'z' (nova → novz)
    """
    out: list[MutatedCandidate] = []

    # xPREFIX variant
    mutant = "x" + seed
    c = _make(mutant, MUT_X_INFUSION, seed, min_l, max_l)
    if c:
        out.append(c)

    # SUFFIX x variant
    base = seed.rstrip("aeiou") or seed
    mutant = base + "x"
    c = _make(mutant, MUT_X_INFUSION, seed, min_l, max_l)
    if c and mutant not in {mc.name for mc in out}:
        out.append(c)

    # Replace last vowel with z
    for i in range(len(seed) - 1, 0, -1):
        if seed[i] in VOWELS:
            mutant = seed[:i] + "z" + seed[i + 1:]
            c = _make(mutant, MUT_X_INFUSION, seed, min_l, max_l)
            if c:
                out.append(c)
            break

    return out


def _mut_reverse_blend(seed_a: str, seed_b: str,
                       min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Blend end of seed_a with start of seed_b.

    "data" + "flow"  → "taflow"
    "cloud"+ "spark" → "udspark"

    Yields 1–2 candidates per pair depending on split points.
    """
    out: list[MutatedCandidate] = []
    if len(seed_a) < 3 or len(seed_b) < 3:
        return out

    # Split A at its last vowel, keep only the tail
    tail_a = ""
    for i in range(len(seed_a) - 1, 0, -1):
        if seed_a[i] in VOWELS:
            tail_a = seed_a[i:]
            break
    if not tail_a:
        tail_a = seed_a[-2:]

    # Split B at its first vowel, keep from start
    head_b = seed_b
    for i, ch in enumerate(seed_b):
        if ch in VOWELS and i > 0:
            head_b = seed_b[:i + 2]
            break

    mutant = tail_a + seed_b
    c = _make(mutant, MUT_REVERSE_BLEND, seed_a, min_l, max_l, source_b=seed_b)
    if c:
        out.append(c)

    mutant2 = seed_a[-2:] + head_b
    c2 = _make(mutant2, MUT_REVERSE_BLEND, seed_a, min_l, max_l, source_b=seed_b)
    if c2 and mutant2 != mutant:
        out.append(c2)

    return out


def _mut_compress(seed: str, min_l: int, max_l: int) -> list[MutatedCandidate]:
    """
    Compress a word by removing duplicate consonant patterns and weak fillers.

    "cloud"   → "clud"   (remove interior o)
    "stream"  → "strem"  (remove a)
    "platform"→ "pltfrm" (heavy compression)
    """
    out: list[MutatedCandidate] = []
    if len(seed) < 6:
        return out

    # Remove all interior vowels except the first (aggressive compression)
    first_vowel_seen = False
    compressed = ""
    for ch in seed:
        if ch in VOWELS:
            if not first_vowel_seen:
                first_vowel_seen = True
                compressed += ch
            # else: skip subsequent vowels
        else:
            compressed += ch

    if compressed and compressed != seed:
        c = _make(compressed, MUT_COMPRESS, seed, min_l, max_l)
        if c:
            out.append(c)

    # Lighter: remove just the second vowel occurrence
    count = 0
    lighter = ""
    for ch in seed:
        if ch in VOWELS:
            count += 1
            if count == 2:
                continue    # skip second vowel only
        lighter += ch

    if lighter and lighter != seed and lighter != compressed:
        c = _make(lighter, MUT_COMPRESS, seed, min_l, max_l)
        if c:
            out.append(c)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# § 6  MUTATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

#: Maps strategy name → mutation function (single-seed variants)
_SINGLE_SEED_FNS: dict[str, object] = {
    MUT_VOWEL_DROP:    _mut_vowel_drop,
    MUT_VOWEL_REPLACE: _mut_vowel_replace,
    MUT_CONSONANT_SWAP:_mut_consonant_swap,
    MUT_PHONEME_SUB:   _mut_phoneme_sub,
    MUT_POWER_ENDING:  _mut_power_ending,
    MUT_SOFT_ENDING:   _mut_soft_ending,
    MUT_LETTER_DOUBLE: _mut_letter_double,
    MUT_SYLLABLE_DROP: _mut_syllable_drop,
    MUT_INITIAL_SHIFT: _mut_initial_shift,
    MUT_X_INFUSION:    _mut_x_infusion,
    MUT_COMPRESS:      _mut_compress,
}


class MutationEngine:
    """
    Applies 12 linguistic mutation strategies to a seed word pool.

    Usage::

        from nexagen.engine.mutation_engine import MutationEngine
        engine = MutationEngine()
        result = engine.apply(expanded_seeds, cfg)
        extra_names = result.names[:50]

    The engine is stateless — safe to reuse across multiple calls.
    Called by NameGenerator after PatternEngine to supplement the
    candidate pool with character-level variants.
    """

    def apply(
        self,
        seeds:          Sequence[str],
        cfg:            Optional[Settings] = None,
        *,
        max_candidates: int = 300,
    ) -> MutationResult:
        """
        Apply all style-appropriate mutation strategies to the seed pool.

        Args:
            seeds:          Seed words from SynonymEngine or PatternEngine.
            cfg:            Active Settings (controls style, length bounds).
            max_candidates: Hard cap on total unique candidates returned.

        Returns:
            :class:`MutationResult` with candidates sorted quality-DESC.
        """
        if cfg is None:
            cfg = get_settings()

        min_l = max(cfg.min_len, NAME_LENGTH_HARD_MIN)
        max_l = min(cfg.max_len, NAME_LENGTH_HARD_MAX)

        active = _STYLE_MUTATIONS.get(cfg.style_mode, _ALL_MUTATIONS)

        seed_list = [_clean(s) for s in seeds if _clean(s) and len(_clean(s)) >= 2]

        all_candidates: list[MutatedCandidate] = []

        # ── Single-seed mutations ─────────────────────────────────────────────
        for strat in active:
            if strat == MUT_REVERSE_BLEND:
                continue   # handled separately (needs two seeds)
            fn = _SINGLE_SEED_FNS.get(strat)
            if fn is None:
                continue
            for seed in seed_list[:25]:
                batch = fn(seed, min_l, max_l)   # type: ignore[call-arg]
                all_candidates.extend(batch)
            if len(all_candidates) >= max_candidates * 2:
                break

        # ── Two-seed REVERSE_BLEND ────────────────────────────────────────────
        if MUT_REVERSE_BLEND in active:
            for i, a in enumerate(seed_list[:15]):
                for b in seed_list[i + 1: i + 6]:
                    if a == b:
                        continue
                    all_candidates.extend(_mut_reverse_blend(a, b, min_l, max_l))
                    if len(all_candidates) >= max_candidates * 2:
                        break

        # ── Dedup by name (keep highest quality) ──────────────────────────────
        best: dict[str, MutatedCandidate] = {}
        for c in all_candidates:
            if c.name not in best or c.quality > best[c.name].quality:
                best[c.name] = c

        # ── Sort: quality DESC → strategy priority → alpha ─────────────────────
        strat_order = {s: i for i, s in enumerate(active)}
        final = sorted(
            best.values(),
            key=lambda c: (-c.quality, strat_order.get(c.strategy, 99), c.name),
        )[:max_candidates]

        return MutationResult(candidates=final)

    def apply_one(
        self,
        word:       str,
        strategies: Optional[Sequence[str]] = None,
        cfg:        Optional[Settings] = None,
    ) -> list[MutatedCandidate]:
        """
        Apply a specific set of mutations to a single word.

        Args:
            word:       Seed word to mutate.
            strategies: Which MUT_* strategies to run. Defaults to all.
            cfg:        Active Settings for length bounds.

        Returns:
            Sorted list of MutatedCandidate objects.
        """
        if cfg is None:
            cfg = get_settings()
        min_l = max(cfg.min_len, NAME_LENGTH_HARD_MIN)
        max_l = min(cfg.max_len, NAME_LENGTH_HARD_MAX)
        seed  = _clean(word)
        if not seed:
            return []

        active = list(strategies) if strategies else _ALL_MUTATIONS
        out: list[MutatedCandidate] = []
        for strat in active:
            fn = _SINGLE_SEED_FNS.get(strat)
            if fn:
                out.extend(fn(seed, min_l, max_l))   # type: ignore[call-arg]

        seen: set[str] = set()
        deduped: list[MutatedCandidate] = []
        for c in out:
            if c.name not in seen:
                seen.add(c.name)
                deduped.append(c)

        return sorted(deduped, key=lambda c: (-c.quality, c.name))


# ─────────────────────────────────────────────────────────────────────────────
# § 7  SIMPLE FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def apply_mutations(
    seeds: Sequence[str],
    cfg:   Optional[Settings] = None,
    *,
    max_candidates: int = 300,
) -> list[str]:
    """
    Apply mutations to a seed pool and return a plain list of name strings.

    Simple interface for callers that don't need MutatedCandidate metadata.

    Args:
        seeds:          Seed words to mutate.
        cfg:            Active Settings.
        max_candidates: Maximum names returned.

    Returns:
        Deduplicated list of mutated name strings, quality-sorted.
    """
    engine = MutationEngine()
    result = engine.apply(seeds, cfg, max_candidates=max_candidates)
    return result.names
