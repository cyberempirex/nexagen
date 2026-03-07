"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  analysis/brand_score.py  ·  Brand name scoring engine                     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

The canonical scoring module for NEXAGEN.  Extracts and formalises all
scoring logic from cli/commands.py into a clean, testable, reusable layer.

Scoring model  (composite 0–100)
─────────────────────────────────
  Dimension        Weight   Evaluates
  ─────────────────────────────────────────────────────────────────────────
  Pronounceability  30 %   Vowel ratio, consonant runs, alternation score,
                           forbidden sequences, syllable count
  Memorability      30 %   Length, opening consonant, vowel ending,
                           alliteration, syllable rhythm
  Uniqueness        20 %   Distance from common words, blacklist proximity,
                           distance from already-scored names in pool
  Length Fitness    20 %   Closeness to ideal length range (cfg.min/max_len)

Tier thresholds (from constants.py):
  PREMIUM ≥ 90 ◆  |  STRONG ≥ 75 ▲  |  DECENT ≥ 60 ●
  WEAK    ≥ 40 ▼  |  POOR    < 40 ✕

Public API
──────────
  BrandScorer.score_name(name, pool, cfg)           → ScoreResult
  BrandScorer.score_batch(names, cfg)               → list[ScoreResult]
  BrandScorer.to_name_result(score_result, kws)     → NameResult
  BrandScorer.to_analysis_data(score_result)        → AnalysisData
  score_pronounceability(name)                      → int
  score_memorability(name)                          → int
  score_uniqueness(name, pool, common, blacklist)   → int
  score_length_fitness(name, min_len, max_len)      → int
  composite_score(p, m, u, lf, weights)             → int
  tm_risk(name, blacklist)                          → str
  generate_notes(name, score_result, cfg)           → list[str]

Data structures
───────────────
  ScoreResult  — all four dimension scores + composite + tm_risk + notes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config.constants import (
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    SCORE_DECENT,
    SCORE_PREMIUM,
    SCORE_STRONG,
    SCORE_WEAK,
    TM_HIGH_RISK_DISTANCE,
    TM_LOW_RISK_DISTANCE,
    TM_MEDIUM_RISK_DISTANCE,
    BrandTier,
    TMRisk,
)
from ..config.settings import Settings, get_settings
from ..ui.tables import AnalysisData, NameResult
from ..utils.dataset_loader import blacklist as load_blacklist
from ..utils.dataset_loader import common_words as load_common_words
from ..utils.levenshtein import levenshtein, trademark_risk as _lev_tm_risk
from ..utils.text_utils import (
    alternation_score,
    ends_with_vowel,
    has_alliteration,
    has_forbidden_sequence,
    max_consonant_run,
    metaphone,
    soundex,
    starts_with_strong_consonant,
    syllable_count,
    vowel_ratio,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  SCORE RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    """
    Full scoring output for a single brand name candidate.

    Attributes:
        name:        The brand name that was scored.
        score:       Composite score 0–100.
        tier:        BrandTier enum value string ("PREMIUM", "STRONG", …).
        pronounce:   Pronounceability sub-score 0–100.
        memorability:Memorability sub-score 0–100.
        uniqueness:  Uniqueness sub-score 0–100.
        length_fit:  Length fitness sub-score 0–100.
        tm_risk:     Trademark risk level ("none"|"low"|"medium"|"high").
        syllables:   Syllable count (from text_utils.syllable_count).
        vowel_r:     Vowel ratio 0.0–1.0.
        is_common:   True if the name appears in the common-words dataset.
        phonetic_key:Soundex code for phonetic deduplication.
        metaphone_key:Metaphone code.
        notes:       Human-readable insight strings.
    """
    name:         str
    score:        int
    tier:         str
    pronounce:    int
    memorability: int
    uniqueness:   int
    length_fit:   int
    tm_risk:      str
    syllables:    int
    vowel_r:      float
    is_common:    bool
    phonetic_key: str         = ""
    metaphone_key:str         = ""
    notes:        list[str]   = field(default_factory=list)

    @property
    def tier_enum(self) -> BrandTier:
        """Return the BrandTier enum member for this result."""
        return BrandTier.from_score(self.score)

    @property
    def tm_risk_enum(self) -> TMRisk:
        """Return the TMRisk enum member for this result."""
        return TMRisk(self.tm_risk)

    def is_usable(self) -> bool:
        """True if the name meets minimum quality bar (DECENT or above)."""
        return self.score >= SCORE_DECENT and self.tm_risk not in ("high",)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DIMENSION SCORERS
# ─────────────────────────────────────────────────────────────────────────────

def score_pronounceability(name: str) -> int:
    """
    Score how easy the name is to say aloud (0–100).

    Factors:
      • Vowel ratio (ideal 30–55%)              ±20 pts
      • Max consecutive consonant run           ±20 pts
      • Vowel-consonant alternation score       +0–15 pts
      • Forbidden phoneme sequences             −20 pts
      • Syllable count (2–3 ideal)              ±10 pts

    Baseline: 60

    Args:
        name: Lowercase alphabetic name string.

    Returns:
        Integer score 0–100.
    """
    score = 60  # baseline

    vr = vowel_ratio(name)
    if 0.30 <= vr <= 0.55:
        score += 20
    elif 0.20 <= vr < 0.30 or 0.55 < vr <= 0.65:
        score += 8
    else:
        score -= 15

    run = max_consonant_run(name)
    if run <= 1:
        score += 15
    elif run == 2:
        score += 8
    elif run == 3:
        score -= 5
    else:
        score -= 20

    alt = alternation_score(name)
    score += int(alt * 15)

    if has_forbidden_sequence(name):
        score -= 20

    syls = syllable_count(name)
    if syls in (2, 3):
        score += 10
    elif syls == 1 and len(name) <= 4:
        score += 5
    elif syls > 4:
        score -= 10

    return max(0, min(100, score))


def score_memorability(name: str) -> int:
    """
    Score how memorable and catchy the name is (0–100).

    Factors:
      • Length (ideal 4–8 chars)                ±20 pts
      • Strong opening consonant (b/d/f/g/k…)  +8 pts
      • Ends on a vowel                         +6 pts
      • Alliteration                            +8 pts
      • Syllable rhythm (2 syllables ideal)     +0–12 pts
      • Long unbroken strings > 10 chars        −N pts

    Baseline: 55

    Args:
        name: Lowercase alphabetic name string.

    Returns:
        Integer score 0–100.
    """
    score = 55
    n     = len(name)

    if NAME_LENGTH_IDEAL_MIN <= n <= NAME_LENGTH_IDEAL_MAX:
        score += 20
    elif n < NAME_LENGTH_IDEAL_MIN:
        score += max(0, 12 - (NAME_LENGTH_IDEAL_MIN - n) * 6)
    else:
        score -= min(20, (n - NAME_LENGTH_IDEAL_MAX) * 4)

    if starts_with_strong_consonant(name):
        score += 8

    if ends_with_vowel(name):
        score += 6

    if has_alliteration(name):
        score += 8

    syls = syllable_count(name)
    if syls == 2:
        score += 12
    elif syls == 3:
        score += 8
    elif syls == 1:
        score += 4
    else:
        score -= (syls - 3) * 6

    if n > 10:
        score -= (n - 10) * 3

    return max(0, min(100, score))


def score_uniqueness(
    name:      str,
    pool:      Sequence[str],
    common:    Optional[frozenset[str]] = None,
    blacklist: Optional[Sequence[str]]  = None,
) -> int:
    """
    Score how distinct the name is from common words and the current pool (0–100).

    Factors:
      • Exact match in common-words dataset      −25 pts
      • Levenshtein proximity to blacklisted brand:
          distance == 0              → 0 (hard zero)
          distance ≤ 2               → −30
          distance ≤ 3               → −10
      • Minimum Levenshtein distance from pool:
          dist ≤ 1                   → −30
          dist == 2                  → −15
          dist == 3                  → −5

    Baseline: 80

    Args:
        name:      Name to score.
        pool:      Already-scored names (used for near-duplicate detection).
        common:    Frozenset of common English words. Auto-loaded if None.
        blacklist: Sequence of protected brand names. Auto-loaded if None.

    Returns:
        Integer score 0–100.
    """
    if common is None:
        common = load_common_words()
    if blacklist is None:
        blacklist = list(load_blacklist())

    score = 80

    if name in common:
        score -= 25

    for brand in blacklist:
        d = levenshtein(name, brand)
        if d == 0:
            return 0
        if d <= TM_MEDIUM_RISK_DISTANCE:
            score -= 30
            break
        if d <= TM_LOW_RISK_DISTANCE:
            score -= 10

    if pool:
        min_dist = min(levenshtein(name, other) for other in pool[:50])
        if min_dist <= 1:
            score -= 30
        elif min_dist == 2:
            score -= 15
        elif min_dist == 3:
            score -= 5

    return max(0, min(100, score))


def score_length_fitness(
    name:    str,
    min_len: int,
    max_len: int,
) -> int:
    """
    Score how well the name length fits the configured ideal range (0–100).

    Computes distance from the midpoint of [min_len, max_len] and applies
    a 12-point-per-char penalty plus a 10-point bonus for being exactly
    within the range.

    Args:
        name:    The brand name to evaluate.
        min_len: Lower bound of ideal length (from Settings.min_len).
        max_len: Upper bound of ideal length (from Settings.max_len).

    Returns:
        Integer score 0–100.
    """
    n     = len(name)
    ideal = (min_len + max_len) / 2
    delta = abs(n - ideal)
    score = max(0, 100 - int(delta * 12))
    if min_len <= n <= max_len:
        score = min(100, score + 10)
    return score


def composite_score(
    pronounce:    int,
    memorability: int,
    uniqueness:   int,
    length_fit:   int,
    weights:      dict[str, float],
) -> int:
    """
    Compute the weighted composite brand score (0–100).

    Args:
        pronounce:    Pronounceability sub-score 0–100.
        memorability: Memorability sub-score 0–100.
        uniqueness:   Uniqueness sub-score 0–100.
        length_fit:   Length fitness sub-score 0–100.
        weights:      Dict with keys "pronounce", "memorability",
                      "uniqueness", "length_fit" → float (must sum to 1.0).

    Returns:
        Rounded integer composite score 0–100.
    """
    raw = (
        pronounce    * weights.get("pronounce",    0.30) +
        memorability * weights.get("memorability", 0.30) +
        uniqueness   * weights.get("uniqueness",   0.20) +
        length_fit   * weights.get("length_fit",   0.20)
    )
    return max(0, min(100, round(raw)))


def tm_risk(
    name:      str,
    blacklist: Optional[Sequence[str]] = None,
) -> str:
    """
    Compute trademark conflict risk level for a name.

    Uses Levenshtein distance against the brand blacklist:
      distance == 0 or ≤ TM_HIGH_RISK_DISTANCE   → "high"
      distance ≤ TM_MEDIUM_RISK_DISTANCE          → "medium"
      distance ≤ TM_LOW_RISK_DISTANCE             → "low"
      otherwise                                   → "none"

    Args:
        name:      The brand name to evaluate.
        blacklist: Sequence of protected brand names. Auto-loaded if None.

    Returns:
        Risk level string: "none" | "low" | "medium" | "high"
    """
    if blacklist is None:
        blacklist = list(load_blacklist())

    for brand in blacklist:
        d = levenshtein(name, brand)
        if d == 0:
            return TMRisk.HIGH.value
        if d <= TM_HIGH_RISK_DISTANCE:
            return TMRisk.HIGH.value
        if d <= TM_MEDIUM_RISK_DISTANCE:
            return TMRisk.MEDIUM.value
        if d <= TM_LOW_RISK_DISTANCE:
            return TMRisk.LOW.value

    return TMRisk.NONE.value


def generate_notes(
    name:   str,
    result: ScoreResult,
    cfg:    Optional[Settings] = None,
) -> list[str]:
    """
    Generate human-readable insight strings for a scored name.

    Args:
        name:   The brand name.
        result: Its ScoreResult.
        cfg:    Active Settings (for length range context).

    Returns:
        List of insight strings (may be empty for clean names).
    """
    if cfg is None:
        cfg = get_settings()

    notes: list[str] = []

    if has_forbidden_sequence(name):
        notes.append("Contains a phonetically awkward character sequence.")

    if result.is_common:
        notes.append("This is a common English word — low brand distinction.")

    if len(name) < NAME_LENGTH_IDEAL_MIN:
        notes.append(
            f"Name is short ({len(name)} chars); "
            f"ideal minimum is {NAME_LENGTH_IDEAL_MIN}."
        )
    elif len(name) > NAME_LENGTH_IDEAL_MAX:
        notes.append(
            f"Name is long ({len(name)} chars); "
            f"may be harder to remember."
        )

    if result.tm_risk in (TMRisk.HIGH.value, TMRisk.MEDIUM.value):
        notes.append(
            f"Trademark risk is {result.tm_risk.upper()} — "
            f"verify before use."
        )

    if result.score >= SCORE_PREMIUM:
        notes.append("Exceptional brand name — all metrics above threshold.")
    elif result.score >= SCORE_STRONG:
        notes.append("Strong brand candidate — good to proceed.")
    elif result.score < SCORE_WEAK:
        notes.append("Below quality threshold — consider alternatives.")

    if result.pronounce < 50:
        notes.append("Phonetic structure may be difficult to say aloud.")

    if result.uniqueness < 50:
        notes.append("Low uniqueness — close to existing brands or common words.")

    return notes


# ─────────────────────────────────────────────────────────────────────────────
# § 3  BRAND SCORER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BrandScorer:
    """
    Stateful scoring context that caches dataset lookups across a batch run.

    Usage::

        from nexagen.analysis.brand_score import BrandScorer
        scorer = BrandScorer(cfg)
        for name in candidates:
            result = scorer.score_name(name, pool=[r.name for r in scored])
            scored.append(result)

    Caching: common_words and blacklist are loaded once at construction
    and reused across all score_name() calls, avoiding repeated I/O.
    """

    def __init__(self, cfg: Optional[Settings] = None) -> None:
        self.cfg       = cfg if cfg is not None else get_settings()
        self._common   = load_common_words()
        self._blacklist= list(load_blacklist())

    # ── Main entry point ──────────────────────────────────────────────────────

    def score_name(
        self,
        name: str,
        pool: Optional[Sequence[str]] = None,
    ) -> ScoreResult:
        """
        Score a single brand name candidate.

        Args:
            name: Lowercase alphabetic brand name.
            pool: Already-scored names in the current batch (for uniqueness).
                  Pass an empty list for the first name, then accumulate.

        Returns:
            :class:`ScoreResult` with all dimensions populated.
        """
        if pool is None:
            pool = []

        p  = score_pronounceability(name)
        m  = score_memorability(name)
        u  = score_uniqueness(name, pool, self._common, self._blacklist)
        lf = score_length_fitness(name, self.cfg.min_len, self.cfg.max_len)
        cs = composite_score(p, m, u, lf, self.cfg.score_weights)
        tr = tm_risk(name, self._blacklist)

        syls    = syllable_count(name)
        vr      = vowel_ratio(name)
        common  = name in self._common
        sdx     = soundex(name)
        mta     = metaphone(name)
        tier    = BrandTier.from_score(cs).value

        result = ScoreResult(
            name=name,
            score=cs,
            tier=tier,
            pronounce=p,
            memorability=m,
            uniqueness=u,
            length_fit=lf,
            tm_risk=tr,
            syllables=syls,
            vowel_r=vr,
            is_common=common,
            phonetic_key=sdx,
            metaphone_key=mta,
        )
        result.notes = generate_notes(name, result, self.cfg)
        return result

    def score_batch(
        self,
        names: Sequence[str],
        *,
        accumulate_pool: bool = True,
    ) -> list[ScoreResult]:
        """
        Score a list of names sequentially, accumulating a uniqueness pool.

        Args:
            names:           Names to score.
            accumulate_pool: If True, each name's score is influenced by
                             all previously scored names in the batch
                             (prevents near-duplicate cluttering).

        Returns:
            List of ScoreResult objects in the same order as input.
        """
        pool:    list[str]        = []
        results: list[ScoreResult] = []

        for name in names:
            result = self.score_name(name, pool=pool)
            results.append(result)
            if accumulate_pool:
                pool.append(name)

        return results

    # ── Conversion helpers ────────────────────────────────────────────────────

    def to_name_result(
        self,
        sr:       ScoreResult,
        keywords: Optional[Sequence[str]] = None,
    ) -> NameResult:
        """
        Convert a :class:`ScoreResult` to a :class:`NameResult` (for UI display).

        NameResult is the dataclass consumed by ui/tables.py for rendering
        the names table and comparison table.

        Args:
            sr:       ScoreResult from score_name().
            keywords: Original user keywords for the keywords field.

        Returns:
            :class:`NameResult` populated from sr.
        """
        return NameResult(
            name         = sr.name,
            score        = sr.score,
            tier         = sr.tier,
            pronounce    = sr.pronounce,
            memorability = sr.memorability,
            uniqueness   = sr.uniqueness,
            length_fit   = sr.length_fit,
            tm_risk      = sr.tm_risk,
            syllables    = sr.syllables,
            profile      = self.cfg.profile,
            style        = self.cfg.style_mode,
            keywords     = list(keywords) if keywords else [],
        )

    def to_analysis_data(self, sr: ScoreResult) -> AnalysisData:
        """
        Convert a :class:`ScoreResult` to :class:`AnalysisData` (for analysis display).

        AnalysisData is the dataclass consumed by ui/tables.py for
        print_score_card() and print_analysis_table().

        Args:
            sr: ScoreResult from score_name().

        Returns:
            :class:`AnalysisData` populated from sr.
        """
        return AnalysisData(
            name         = sr.name,
            score        = sr.score,
            tier         = sr.tier,
            pronounce    = sr.pronounce,
            memorability = sr.memorability,
            uniqueness   = sr.uniqueness,
            length_fit   = sr.length_fit,
            syllables    = sr.syllables,
            vowel_ratio  = sr.vowel_r,
            tm_risk      = sr.tm_risk,
            is_common    = sr.is_common,
            phonetic_key = sr.phonetic_key,
            notes        = list(sr.notes),
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 4  TIER UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def tier_for_score(score: int) -> str:
    """Return the BrandTier value string for a composite score."""
    return BrandTier.from_score(score).value


def tier_colour_for_score(score: int) -> str:
    """
    Return a Rich hex colour string matching the tier band for a score.

    Used by animations.reveal_names() to colour-code the name reveal.
    """
    from ..config.constants import (
        C_AMBER, C_GOLD, C_GREEN, C_RED,
        SCORE_DECENT, SCORE_PREMIUM, SCORE_STRONG, SCORE_WEAK,
        C_ACCENT,
    )
    if score >= SCORE_PREMIUM:
        return C_GOLD
    if score >= SCORE_STRONG:
        return C_GREEN
    if score >= SCORE_DECENT:
        return C_ACCENT
    if score >= SCORE_WEAK:
        return C_AMBER
    return C_RED


def quick_score(name: str, cfg: Optional[Settings] = None) -> int:
    """
    Return just the composite score for a single name without building
    a full ScoreResult.

    Uses auto-loaded datasets (no caching). For batch scoring use
    BrandScorer.score_batch() instead.

    Args:
        name: Lowercase alphabetic brand name.
        cfg:  Active Settings.

    Returns:
        Composite score 0–100.
    """
    if cfg is None:
        cfg = get_settings()
    scorer = BrandScorer(cfg)
    return scorer.score_name(name).score
