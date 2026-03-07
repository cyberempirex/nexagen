"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  analysis/phonetic_analysis.py  ·  Deep phonetic quality analysis          ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Deep phonetic quality analysis for brand names.

Goes well beyond the scalar ``pronounceability`` sub-score in brand_score.py
by decomposing phonetic quality into nine independent dimensions and producing
a full diagnostic breakdown with per-dimension scores and actionable notes.

The nine phonetic dimensions
─────────────────────────────
  1. Vowel balance      — ideal vowel ratio 30–55 % of letters
  2. Consonant flow     — no long consonant clusters (run ≤ 2 ideal)
  3. Alternation        — CVCV / VCVC rhythm; penalises same-type clusters
  4. Forbidden bigrams  — hard phonetic blocks (xx, wq, bx, …)
  5. Syllable profile   — 2–3 syllables ideal for brand memorability
  6. Opening strength   — strong start consonant (b d f g k p r s t v z)
  7. Closing quality    — vowel ending is softer; harsh consonant endings
  8. Rare-consonant load — excessive q x z j v makes names unreadable
  9. Phonetic uniqueness — Soundex / Metaphone keys confirm distinctiveness

Each dimension is scored 0–100.  A composite score is computed as a weighted
average using the weights defined in ``_DIMENSION_WEIGHTS``.

Public API
──────────
  analyse_phonetics(name)          → PhoneticReport
  batch_analyse(names)             → list[PhoneticReport]
  phonetic_score(name)             → int   (0–100 composite)
  phonetic_grade(name)             → str   "A" | "B" | "C" | "D" | "F"

Data structures
───────────────
  PhoneticDimension    — score + label + explanation for one dimension
  PhoneticReport       — all nine dimensions + composite + keys + notes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from ..config.constants import (
    CONSONANTS,
    FORBIDDEN_SEQUENCES,
    RARE_CONSONANTS,
    STRONG_START_CONSONANTS,
    VOWELS,
)
from ..utils.text_utils import (
    alternation_score,
    ends_with_vowel,
    forbidden_sequence_count,
    has_forbidden_sequence,
    has_rare_consonants,
    is_pronounceable,
    max_consonant_run,
    metaphone,
    rare_consonant_count,
    soundex,
    starts_with_strong_consonant,
    syllable_count,
    vowel_ratio,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DIMENSION WEIGHTS  (must sum to 1.0)
# ─────────────────────────────────────────────────────────────────────────────

_DIMENSION_WEIGHTS: dict[str, float] = {
    "vowel_balance":      0.16,
    "consonant_flow":     0.15,
    "alternation":        0.14,
    "forbidden_bigrams":  0.14,
    "syllable_profile":   0.12,
    "opening_strength":   0.10,
    "closing_quality":    0.09,
    "rare_consonants":    0.08,
    "phonetic_uniqueness":0.02,
}

# Grades by composite score
_GRADE_THRESHOLDS: list[tuple[int, str]] = [
    (88, "A"),
    (75, "B"),
    (60, "C"),
    (45, "D"),
    (0,  "F"),
]


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PhoneticDimension:
    """
    Score and explanation for a single phonetic quality dimension.

    Attributes:
        key:         Machine-readable dimension identifier.
        label:       Human-readable dimension name.
        score:       Dimension score 0–100 (higher = better).
        weight:      This dimension's fractional weight in the composite.
        passed:      True if the score is above the passing threshold (≥ 60).
        note:        Short description of the result for this dimension.
    """
    key:    str
    label:  str
    score:  int
    weight: float
    passed: bool  = True
    note:   str   = ""

    @property
    def weighted_contribution(self) -> float:
        """Contribution of this dimension to the composite score."""
        return self.score * self.weight

    def __str__(self) -> str:
        tick = "✔" if self.passed else "✘"
        return f"{tick} {self.label:<22} {self.score:>3}/100  {self.note}"


@dataclass
class PhoneticReport:
    """
    Full phonetic analysis for a single brand name.

    Attributes:
        name:         The candidate brand name (lowercased).
        composite:    Weighted composite phonetic score 0–100.
        grade:        Letter grade ``"A"``–``"F"``.
        dimensions:   List of all nine :class:`PhoneticDimension` objects.
        soundex_key:  Soundex phonetic encoding.
        metaphone_key:Metaphone phonetic encoding.
        syllables:    Estimated syllable count.
        vowel_r:      Vowel ratio (0.0–1.0).
        is_pronounceable: Whether the name clears the basic pronounceability
                      threshold from :func:`text_utils.is_pronounceable`.
        notes:        Human-readable diagnostic strings.
    """
    name:             str
    composite:        int
    grade:            str
    dimensions:       list[PhoneticDimension] = field(default_factory=list)
    soundex_key:      str = ""
    metaphone_key:    str = ""
    syllables:        int = 0
    vowel_r:          float = 0.0
    is_pronounceable: bool  = True
    notes:            list[str] = field(default_factory=list)

    def dimension(self, key: str) -> PhoneticDimension | None:
        """Return a dimension by its key, or None."""
        for d in self.dimensions:
            if d.key == key:
                return d
        return None

    def failing_dimensions(self) -> list[PhoneticDimension]:
        """Return dimensions with score < 60."""
        return [d for d in self.dimensions if not d.passed]

    def __str__(self) -> str:
        return (
            f"PhoneticReport({self.name!r}  "
            f"score={self.composite}/100  grade={self.grade}  "
            f"sx={self.soundex_key}  mp={self.metaphone_key})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  DIMENSION SCORERS
# ─────────────────────────────────────────────────────────────────────────────

def _score_vowel_balance(word: str) -> tuple[int, str]:
    """
    Vowel balance: ideal range 0.30–0.55.

    Too few vowels → unpronounceable consonant clusters.
    Too many vowels → soft, forgettable names.
    """
    vr = vowel_ratio(word)
    if 0.30 <= vr <= 0.55:
        score = 100
    elif 0.22 <= vr < 0.30:
        score = max(50, 100 - int((0.30 - vr) * 350))
    elif 0.55 < vr <= 0.65:
        score = max(55, 100 - int((vr - 0.55) * 300))
    elif vr < 0.22:
        score = max(0, 30 - int((0.22 - vr) * 200))
    else:
        score = max(20, 55 - int((vr - 0.65) * 200))

    pct  = f"{vr*100:.0f}% vowels"
    note = pct + ("  ✔ ideal" if 0.30 <= vr <= 0.55 else
                  "  ↑ too many vowels" if vr > 0.65 else
                  "  ↓ too few vowels")
    return score, note


def _score_consonant_flow(word: str) -> tuple[int, str]:
    """
    Consonant flow: penalises long consonant runs.

    run ≤ 1  → 100  (perfect alternation)
    run == 2 → 85   (acceptable cluster)
    run == 3 → 55   (hard to say)
    run >  3 → 0–25 (unpronounceable)
    """
    run = max_consonant_run(word)
    if run <= 1:
        score, note = 100, "no consonant clusters"
    elif run == 2:
        score, note = 85, "max cluster=2 (acceptable)"
    elif run == 3:
        score, note = 55, "max cluster=3 (awkward)"
    elif run == 4:
        score, note = 25, "max cluster=4 (hard to say)"
    else:
        score, note = 0, f"max cluster={run} (unpronounceable)"
    return score, note


def _score_alternation(word: str) -> tuple[int, str]:
    """
    CV alternation rhythm: CVCV / VCVC scores highest.

    Uses :func:`text_utils.alternation_score` and maps 0.0–1.0 → 0–100.
    """
    alt = alternation_score(word)
    score = round(alt * 100)
    if score >= 80:
        note = "good consonant-vowel rhythm"
    elif score >= 60:
        note = "moderate rhythm"
    else:
        note = "poor alternation — consider restructuring"
    return score, note


def _score_forbidden_bigrams(word: str) -> tuple[int, str]:
    """
    Forbidden sequence check.

    Any forbidden bigram (from FORBIDDEN_SEQUENCES) is a hard phonetic
    failure.  Multiple forbidden sequences compound the penalty.
    """
    if not has_forbidden_sequence(word):
        return 100, "no forbidden sequences"
    count = forbidden_sequence_count(word)
    # Each forbidden sequence removes 35 pts; minimum 0
    score = max(0, 100 - count * 35)
    seqs  = [s for s in FORBIDDEN_SEQUENCES if s in word.lower()][:4]
    note  = f"contains: {', '.join(seqs)}"
    return score, note


def _score_syllable_profile(word: str) -> tuple[int, str]:
    """
    Syllable count: 2–3 syllables are ideal for brand recall.

    1 syllable  → good if name is ≤ 5 chars, mediocre otherwise
    2–3 syllables → best
    4+ syllables → progressive penalty
    """
    syl = syllable_count(word)
    if syl == 2 or syl == 3:
        score = 100
        note  = f"{syl} syllables — ideal"
    elif syl == 1:
        score = 70 if len(word) <= 5 else 55
        note  = "1 syllable — concise but may lack character"
    elif syl == 4:
        score = 65
        note  = "4 syllables — slightly long"
    elif syl == 5:
        score = 40
        note  = "5 syllables — too long for a brand"
    else:
        score = max(0, 40 - (syl - 5) * 12)
        note  = f"{syl} syllables — too long"
    return score, note


def _score_opening_strength(word: str) -> tuple[int, str]:
    """
    Opening character quality.

    Strong start consonants (b d f g k p r s t v z) signal energy and
    memorability.  Vowel starts are neutral.  Rare consonants (q x z j v)
    at the start score lower.
    """
    if not word:
        return 50, "empty name"
    first = word[0].lower()
    if first in STRONG_START_CONSONANTS:
        return 100, f"strong opening consonant '{first}'"
    if first in VOWELS:
        return 72, f"vowel opening '{first}' — neutral"
    if first in RARE_CONSONANTS:
        return 45, f"rare/weak opening consonant '{first}'"
    # Other consonants (h, l, m, n, w, y)
    return 62, f"moderate opening consonant '{first}'"


def _score_closing_quality(word: str) -> tuple[int, str]:
    """
    Final character quality.

    Vowel endings are warm and memorable (e.g. "nexage-a").
    Strong consonant endings (r, n, x, k) are punchy.
    Double consonant endings are harsh.
    """
    if not word:
        return 50, "empty name"
    last   = word[-1].lower()
    second = word[-2].lower() if len(word) > 1 else ""

    if last in VOWELS:
        return 92, f"vowel ending '{last}' — warm and approachable"

    # Check for harsh double consonant at end
    if second and second in CONSONANTS and last in CONSONANTS:
        if second == last:
            return 40, f"double consonant ending '…{second}{last}' — harsh"
        # Mixed consonant pair
        strong_enders = frozenset("rnxtks")
        if last in strong_enders:
            return 80, f"strong consonant ending '…{last}'"
        return 62, f"consonant ending '…{last}'"

    # Single consonant
    strong_enders = frozenset("rnxtks")
    if last in strong_enders:
        return 84, f"strong consonant ending '{last}'"
    if last in RARE_CONSONANTS:
        return 52, f"rare consonant ending '{last}'"
    return 68, f"consonant ending '{last}'"


def _score_rare_consonants(word: str) -> tuple[int, str]:
    """
    Rare-consonant load: q x z j v.

    One rare consonant in the middle can add distinctiveness.
    Two or more rare consonants make the name hard to type / remember.
    """
    if not has_rare_consonants(word):
        return 100, "no rare consonants"
    count = rare_consonant_count(word)
    if count == 1:
        score = 75
        note  = "1 rare consonant — adds distinctiveness"
    elif count == 2:
        score = 45
        note  = "2 rare consonants — reduces readability"
    else:
        score = max(10, 45 - (count - 2) * 15)
        note  = f"{count} rare consonants — hard to type/remember"
    return score, note


def _score_phonetic_uniqueness(word: str) -> tuple[int, str]:
    """
    Phonetic encoding quality check.

    Ensures the Soundex and Metaphone codes are non-degenerate (i.e. they
    don't collapse to all-zeros or empty strings, which indicates the
    encoding failed on a junk input).  Always scores HIGH for real words.
    """
    sx = soundex(word)
    mp = metaphone(word)
    if sx and sx != "0000" and mp:
        return 100, f"soundex={sx}  metaphone={mp}"
    if sx and sx != "0000":
        return 75, f"soundex={sx}  (no metaphone key)"
    return 40, "degenerate phonetic encoding — check for unusual characters"


# ─────────────────────────────────────────────────────────────────────────────
# § 4  COMPOSITE SCORER
# ─────────────────────────────────────────────────────────────────────────────

def analyse_phonetics(name: str) -> PhoneticReport:
    """
    Run the full nine-dimension phonetic analysis on a brand name.

    Args:
        name: Candidate brand name (any casing — lowercased internally).

    Returns:
        :class:`PhoneticReport` with per-dimension scores, composite,
        phonetic keys, syllable count, and diagnostic notes.
    """
    word = name.lower().strip()

    # Compute all nine dimensions
    dim_specs = [
        ("vowel_balance",       "Vowel Balance",        _score_vowel_balance),
        ("consonant_flow",      "Consonant Flow",        _score_consonant_flow),
        ("alternation",         "CV Alternation",        _score_alternation),
        ("forbidden_bigrams",   "Forbidden Bigrams",     _score_forbidden_bigrams),
        ("syllable_profile",    "Syllable Profile",      _score_syllable_profile),
        ("opening_strength",    "Opening Strength",      _score_opening_strength),
        ("closing_quality",     "Closing Quality",       _score_closing_quality),
        ("rare_consonants",     "Rare Consonants",       _score_rare_consonants),
        ("phonetic_uniqueness", "Phonetic Uniqueness",   _score_phonetic_uniqueness),
    ]

    dimensions: list[PhoneticDimension] = []
    composite_float = 0.0

    for key, label, scorer in dim_specs:
        score, note = scorer(word)
        weight       = _DIMENSION_WEIGHTS[key]
        passed       = score >= 60
        dim          = PhoneticDimension(
            key=key, label=label, score=score,
            weight=weight, passed=passed, note=note,
        )
        dimensions.append(dim)
        composite_float += score * weight

    composite = max(0, min(100, round(composite_float)))
    grade     = next(g for threshold, g in _GRADE_THRESHOLDS if composite >= threshold)

    # Collect keys and raw stats
    sx        = soundex(word)
    mp        = metaphone(word)
    syl       = syllable_count(word)
    vr        = vowel_ratio(word)
    pronounce = is_pronounceable(word)

    # Build diagnostic notes
    notes: list[str] = []
    failing = [d for d in dimensions if not d.passed]
    if failing:
        notes.append(
            "Weak dimensions: " + ", ".join(d.label for d in failing)
        )
    if composite >= 88:
        notes.append("Excellent phonetic profile — highly pronounceable and memorable.")
    elif composite >= 75:
        notes.append("Good phonetic profile — clear and easy to say.")
    elif composite >= 60:
        notes.append("Adequate — minor phonetic issues present.")
    else:
        notes.append("Phonetic quality is low — consider restructuring the name.")

    if not pronounce:
        notes.append("⚠ Basic pronounceability check failed.")
    if has_forbidden_sequence(word):
        notes.append("⚠ Contains a forbidden phonetic sequence.")
    if syl >= 5:
        notes.append("⚠ Name is too long to be easily memorable.")

    return PhoneticReport(
        name             = word,
        composite        = composite,
        grade            = grade,
        dimensions       = dimensions,
        soundex_key      = sx,
        metaphone_key    = mp,
        syllables        = syl,
        vowel_r          = round(vr, 3),
        is_pronounceable = pronounce,
        notes            = notes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  BATCH AND CONVENIENCE INTERFACES
# ─────────────────────────────────────────────────────────────────────────────

def batch_analyse(names: Sequence[str]) -> list[PhoneticReport]:
    """
    Analyse phonetic quality for a list of brand names.

    Args:
        names: Candidate brand names.

    Returns:
        List of :class:`PhoneticReport` in input order.
    """
    return [analyse_phonetics(n) for n in names]


def phonetic_score(name: str) -> int:
    """
    Return the composite phonetic score (0–100) for a single name.

    Convenience wrapper around :func:`analyse_phonetics`.

    Args:
        name: Brand name string.

    Returns:
        Integer composite score 0–100.
    """
    return analyse_phonetics(name).composite


def phonetic_grade(name: str) -> str:
    """
    Return the letter grade (\"A\"–\"F\") for a single name's phonetic quality.

    Args:
        name: Brand name string.

    Returns:
        Grade string.
    """
    return analyse_phonetics(name).grade


def group_by_phonetic_key(
    names:     Sequence[str],
    *,
    algorithm: str = "soundex",
) -> dict[str, list[str]]:
    """
    Group names by their Soundex or Metaphone phonetic key.

    Names in the same group sound alike and may need collision review.

    Args:
        names:     Brand name candidates.
        algorithm: ``"soundex"`` (default) or ``"metaphone"``.

    Returns:
        Dict mapping phonetic key → list of names.  Groups with only
        one member are included (use the value's length to filter).
    """
    encode = soundex if algorithm == "soundex" else metaphone
    groups: dict[str, list[str]] = {}
    for n in names:
        key = encode(n.lower())
        groups.setdefault(key, []).append(n)
    return groups


def top_phonetic_names(
    names:  Sequence[str],
    n:      int = 10,
) -> list[tuple[str, int]]:
    """
    Return the top-N names by composite phonetic score.

    Args:
        names: Candidate names.
        n:     Maximum results.

    Returns:
        List of ``(name, score)`` tuples, sorted score descending.
    """
    scored = [(name, phonetic_score(name)) for name in names]
    scored.sort(key=lambda x: -x[1])
    return scored[:n]
