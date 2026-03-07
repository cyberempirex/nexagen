"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  engine/synonym_engine.py  ·  Keyword expansion via synonym graph          ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

The SynonymEngine turns a small set of user-supplied seed keywords into a
rich, scored pool of related terms that the PatternEngine uses to generate
brand name candidates.

Expansion model
───────────────
  1. Direct lookup   — look up each seed in synonyms.txt
  2. Proximity match — vocab words that share a prefix or substring with seeds
  3. Phonetic match  — words that sound similar (Soundex)
  4. Profile vocab   — industry-specific vocabulary from the profile dataset
  5. Depth-2 hop     — synonyms of synonyms (configurable, default disabled)

Each expanded word receives a relevance score 0–100.  The engine returns words
sorted by score so the pattern engine uses the strongest seeds first.

Public API
──────────
  SynonymEngine.expand(keywords, cfg)   → ExpansionResult
  expand_keywords(keywords, cfg)        → list[str]   (simple interface)

Data structures
───────────────
  ScoredWord         — word + relevance score + origin tag
  ExpansionResult    — full expansion with stats and easy access helpers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config.constants import (
    GEN_MAX_CANDIDATES,
    Profile,
    StyleMode,
)
from ..config.settings import Settings, get_settings
from ..utils.dataset_loader import (
    SynonymMap,
    ai_terms,
    business_terms,
    prefixes,
    synonyms,
    tech_terms,
    vocab_for_profile,
)
from ..utils.text_utils import (
    extract_keywords,
    normalize,
    soundex,
    strip_non_alpha,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

# Origin tags for scored words — used for debugging and analysis
ORIGIN_SEED        = "seed"         # original keyword from the user
ORIGIN_SYNONYM     = "synonym"      # direct synonym from synonyms.txt
ORIGIN_SYNONYM2    = "synonym2"     # depth-2 synonym
ORIGIN_VOCAB_MATCH = "vocab_match"  # vocabulary word overlapping with seed
ORIGIN_PREFIX_MATCH= "prefix_match" # shares a 3+ char prefix with a seed
ORIGIN_PHONETIC    = "phonetic"     # same Soundex code as a seed
ORIGIN_PROFILE     = "profile"      # sampled from profile vocabulary
ORIGIN_AFFIX       = "affix"        # prefix/suffix expansion of a seed


@dataclass
class ScoredWord:
    """
    A vocabulary word paired with its relevance score and origin tag.

    Attributes:
        word:   Lowercase alphabetic word.
        score:  Relevance score 0–100 (higher = more relevant to seeds).
        origin: How this word was discovered (see ORIGIN_* constants).
        source: The specific seed or group that triggered this word.
    """
    word:   str
    score:  int
    origin: str = ORIGIN_SEED
    source: str = ""

    def __hash__(self) -> int:
        return hash(self.word)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ScoredWord):
            return self.word == other.word
        return False


@dataclass
class ExpansionResult:
    """
    Complete output of a keyword expansion run.

    Attributes:
        seeds:     Original user keywords (cleaned).
        words:     All scored words sorted by score descending.
        synonyms:  Words that came from synonym lookup only.
        vocab:     Words from profile vocabulary.
        stats:     Breakdown counts by origin.
    """
    seeds:       list[str]
    words:       list[ScoredWord]
    synonyms:    list[ScoredWord] = field(default_factory=list)
    vocab:       list[ScoredWord] = field(default_factory=list)
    stats:       dict[str, int]   = field(default_factory=dict)

    # ── Convenience accessors ─────────────────────────────────────────────────

    def word_list(self, max_words: int = 60) -> list[str]:
        """Return top-N words as a plain list of strings."""
        return [sw.word for sw in self.words[:max_words]]

    def top(self, n: int = 20) -> list[ScoredWord]:
        """Return the top-N highest-scored ScoredWords."""
        return self.words[:n]

    @property
    def total(self) -> int:
        return len(self.words)

    def by_origin(self, origin: str) -> list[ScoredWord]:
        """Return all words with a specific origin tag."""
        return [sw for sw in self.words if sw.origin == origin]

    def __len__(self) -> int:
        return len(self.words)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  SCORING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Relevance scores by origin (applied before length/phonetic adjustments)
_ORIGIN_BASE_SCORES: dict[str, int] = {
    ORIGIN_SEED:         100,
    ORIGIN_SYNONYM:       88,
    ORIGIN_VOCAB_MATCH:   75,
    ORIGIN_PREFIX_MATCH:  65,
    ORIGIN_PHONETIC:      55,
    ORIGIN_SYNONYM2:      50,
    ORIGIN_PROFILE:       40,
    ORIGIN_AFFIX:         35,
}


def _length_bonus(word: str) -> int:
    """Bonus for ideal word length (4–8 chars for brand names)."""
    n = len(word)
    if 4 <= n <= 8:
        return 8
    if 3 <= n <= 10:
        return 3
    return 0


def _clean_word(w: str) -> str:
    """Strip non-alpha, lowercase, normalise."""
    return re.sub(r"[^a-z]", "", normalize(w).lower())


def _dedup_scored(words: list[ScoredWord]) -> list[ScoredWord]:
    """
    Deduplicate by word, keeping the instance with the highest score.
    Returns sorted list (score descending).
    """
    best: dict[str, ScoredWord] = {}
    for sw in words:
        if sw.word not in best or sw.score > best[sw.word].score:
            best[sw.word] = sw
    return sorted(best.values(), key=lambda sw: (-sw.score, sw.word))


# ─────────────────────────────────────────────────────────────────────────────
# § 3  SYNONYM ENGINE CLASS
# ─────────────────────────────────────────────────────────────────────────────

class SynonymEngine:
    """
    Multi-strategy keyword expansion engine.

    Usage::

        from nexagen.engine.synonym_engine import SynonymEngine
        engine = SynonymEngine()
        result = engine.expand(["cloud", "data"], cfg)
        seeds_for_generation = result.word_list(40)

    The engine is stateless apart from the shared SynonymMap and dataset
    caches — it is safe to reuse across multiple calls.
    """

    def __init__(self) -> None:
        self._sm: SynonymMap = SynonymMap()

    # ── Public entry point ────────────────────────────────────────────────────

    def expand(
        self,
        keywords:     Sequence[str],
        cfg:          Optional[Settings] = None,
        *,
        depth:        int  = 1,
        max_words:    int  = 80,
        phonetic:     bool = True,
        profile_sample: int = 30,
    ) -> ExpansionResult:
        """
        Expand a list of seed keywords into a scored vocabulary pool.

        Pipeline:
          1. Clean and validate seeds
          2. Direct synonym lookup (depth-1)
          3. Vocabulary proximity match (prefix + substring)
          4. Phonetic similarity match (Soundex)
          5. Profile vocabulary sampling
          6. Optional depth-2 synonym hop
          7. Score, deduplicate, sort

        Args:
            keywords:       User-supplied seed words.
            cfg:            Active Settings (defaults to get_settings()).
            depth:          Synonym expansion depth (1 = direct only,
                            2 = synonyms of synonyms).
            max_words:      Maximum words in the result set.
            phonetic:       Enable Soundex phonetic matching.
            profile_sample: Max words sampled from profile vocabulary.

        Returns:
            :class:`ExpansionResult` with all scored words.
        """
        if cfg is None:
            cfg = get_settings()

        # ── Step 1: Clean seeds ───────────────────────────────────────────────
        seeds_clean: list[str] = []
        for kw in keywords:
            w = _clean_word(kw)
            if w and len(w) >= 2 and w not in seeds_clean:
                seeds_clean.append(w)

        all_words: list[ScoredWord] = []

        # Seeds themselves score 100
        for seed in seeds_clean:
            sw = ScoredWord(
                word=seed,
                score=_ORIGIN_BASE_SCORES[ORIGIN_SEED] + _length_bonus(seed),
                origin=ORIGIN_SEED,
                source=seed,
            )
            all_words.append(sw)

        # ── Step 2: Direct synonym lookup ─────────────────────────────────────
        syn_map = self._sm.groups
        if cfg.use_synonyms:
            frontier = list(seeds_clean)
            for hop in range(depth):
                origin_tag = ORIGIN_SYNONYM if hop == 0 else ORIGIN_SYNONYM2
                base_score = _ORIGIN_BASE_SCORES[origin_tag]
                next_frontier: list[str] = []

                for seed in frontier:
                    for syn in syn_map.get(seed, []):
                        w = _clean_word(syn)
                        if w and len(w) >= 2:
                            score = base_score + _length_bonus(w)
                            # Depth penalty: each hop reduces score
                            score = max(0, score - hop * 15)
                            all_words.append(ScoredWord(
                                word=w, score=score,
                                origin=origin_tag, source=seed,
                            ))
                            next_frontier.append(w)

                frontier = next_frontier
                if not frontier:
                    break

        # ── Step 3: Vocabulary proximity match ────────────────────────────────
        vocab = vocab_for_profile(cfg.profile)
        seed_set = set(seeds_clean)
        seed_soundex = {s: soundex(s) for s in seeds_clean}

        for v in vocab:
            w = _clean_word(v)
            if not w or len(w) < 2:
                continue

            matched_origin = None
            matched_source = ""

            # Exact inclusion: seed in vocab word or vice versa
            for seed in seeds_clean:
                if (seed in w or w in seed) and w != seed:
                    matched_origin = ORIGIN_VOCAB_MATCH
                    matched_source = seed
                    break

            # 3-char common prefix
            if matched_origin is None:
                for seed in seeds_clean:
                    min_len = min(len(seed), len(w))
                    if min_len >= 3 and w[:3] == seed[:3]:
                        matched_origin = ORIGIN_PREFIX_MATCH
                        matched_source = seed
                        break

            if matched_origin:
                score = _ORIGIN_BASE_SCORES[matched_origin] + _length_bonus(w)
                all_words.append(ScoredWord(
                    word=w, score=score,
                    origin=matched_origin, source=matched_source,
                ))

        # ── Step 4: Phonetic matching ─────────────────────────────────────────
        if phonetic:
            for v in vocab:
                w = _clean_word(v)
                if not w or len(w) < 3:
                    continue
                w_soundex = soundex(w)
                for seed, s_sdx in seed_soundex.items():
                    if w_soundex == s_sdx and w != seed:
                        score = _ORIGIN_BASE_SCORES[ORIGIN_PHONETIC] + _length_bonus(w)
                        all_words.append(ScoredWord(
                            word=w, score=score,
                            origin=ORIGIN_PHONETIC, source=seed,
                        ))
                        break

        # ── Step 5: Profile vocabulary sampling ───────────────────────────────
        existing_words = {sw.word for sw in all_words}
        profile_words  = [_clean_word(v) for v in vocab if _clean_word(v)]
        profile_words  = [
            w for w in profile_words
            if w and len(w) >= 3 and w not in existing_words
        ]

        # Take a deterministic slice (sorted, not random — repeatable output)
        for w in sorted(profile_words)[:profile_sample]:
            score = _ORIGIN_BASE_SCORES[ORIGIN_PROFILE] + _length_bonus(w)
            all_words.append(ScoredWord(
                word=w, score=score,
                origin=ORIGIN_PROFILE, source=cfg.profile,
            ))

        # ── Step 6: Affix expansions of seeds ─────────────────────────────────
        pfx_list = prefixes()[:8]
        for seed in seeds_clean:
            for pre in pfx_list:
                combo = pre + seed
                if 4 <= len(combo) <= 10 and combo.isalpha():
                    all_words.append(ScoredWord(
                        word=combo,
                        score=_ORIGIN_BASE_SCORES[ORIGIN_AFFIX] + _length_bonus(combo),
                        origin=ORIGIN_AFFIX,
                        source=seed,
                    ))

        # ── Step 7: Dedup, sort, trim ─────────────────────────────────────────
        deduped = _dedup_scored(all_words)[:max_words]

        # Build origin stats
        stats: dict[str, int] = {}
        for sw in deduped:
            stats[sw.origin] = stats.get(sw.origin, 0) + 1

        # Split into synonym and vocab sub-lists
        synonyms_only = [sw for sw in deduped if sw.origin in (ORIGIN_SYNONYM, ORIGIN_SYNONYM2)]
        vocab_only    = [sw for sw in deduped if sw.origin in (ORIGIN_PROFILE, ORIGIN_VOCAB_MATCH)]

        return ExpansionResult(
            seeds    = seeds_clean,
            words    = deduped,
            synonyms = synonyms_only,
            vocab    = vocab_only,
            stats    = stats,
        )

    # ── Style-aware filtering ─────────────────────────────────────────────────

    def filter_by_style(
        self,
        result: ExpansionResult,
        style:  str,
    ) -> list[ScoredWord]:
        """
        Re-weight words based on the active style mode.

        Style weights applied on top of base relevance scores:
          futuristic  — boost short punchy words (4–5 chars)
          aggressive  — boost words starting with hard consonants
          soft        — boost words ending in vowels
          technical   — boost compound words (8+ chars)
          luxury      — boost words 4–5 chars only
          minimal     — prefer 4–6 char words

        Args:
            result: Expansion result to re-weight.
            style:  StyleMode value string.

        Returns:
            Re-weighted, re-sorted list of ScoredWord.
        """
        style_lower = style.lower()
        adjusted: list[ScoredWord] = []

        for sw in result.words:
            w = sw.word
            bonus = 0

            if style_lower == StyleMode.FUTURISTIC.value:
                if 4 <= len(w) <= 5:
                    bonus += 15

            elif style_lower == StyleMode.AGGRESSIVE.value:
                if w and w[0] in "bdfgkprstvz":
                    bonus += 15
                if len(w) <= 6:
                    bonus += 5

            elif style_lower == StyleMode.SOFT.value:
                if w and w[-1] in "aeiou":
                    bonus += 15
                if w and w[-2:] in ("ly", "fy", "io", "la", "ra"):
                    bonus += 8

            elif style_lower == StyleMode.TECHNICAL.value:
                if len(w) >= 7:
                    bonus += 12

            elif style_lower == StyleMode.LUXURY.value:
                if 4 <= len(w) <= 5:
                    bonus += 20
                elif len(w) > 6:
                    bonus -= 10

            elif style_lower == StyleMode.MINIMAL.value:
                if 4 <= len(w) <= 6:
                    bonus += 10
                elif len(w) > 8:
                    bonus -= 10

            adjusted.append(ScoredWord(
                word=w,
                score=min(100, sw.score + bonus),
                origin=sw.origin,
                source=sw.source,
            ))

        return sorted(adjusted, key=lambda sw: (-sw.score, sw.word))


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SIMPLE FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def expand_keywords(
    keywords: Sequence[str],
    cfg:      Optional[Settings] = None,
    *,
    max_words: int = 60,
    depth:     int = 1,
) -> list[str]:
    """
    Expand seed keywords and return a plain list of words.

    Simple interface for callers that don't need the full ExpansionResult.

    Args:
        keywords:  User-supplied seed words.
        cfg:       Active Settings.
        max_words: Maximum words to return.
        depth:     Synonym expansion depth.

    Returns:
        Deduplicated list of words sorted by relevance (best first).
    """
    engine = SynonymEngine()
    result = engine.expand(keywords, cfg, depth=depth, max_words=max_words)
    return result.word_list(max_words)


def expand_for_style(
    keywords: Sequence[str],
    cfg:      Optional[Settings] = None,
) -> list[str]:
    """
    Expand keywords and re-weight by the active style mode in cfg.

    Convenience wrapper combining SynonymEngine.expand() and
    SynonymEngine.filter_by_style().

    Returns a plain list of words sorted by style-adjusted relevance.
    """
    if cfg is None:
        cfg = get_settings()
    engine  = SynonymEngine()
    result  = engine.expand(keywords, cfg)
    styled  = engine.filter_by_style(result, cfg.style_mode)
    return [sw.word for sw in styled[:60]]
