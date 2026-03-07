"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  analysis/uniqueness_score.py  ·  Multi-axis uniqueness scoring            ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Multi-axis uniqueness scoring engine.

brand_score.py contains a scalar ``score_uniqueness()`` function used inside
the composite brand scorer.  This module is the full-depth expansion of that
single function — it decomposes uniqueness into five independent axes, each
scored 0–100, and aggregates them into a weighted composite with a full
diagnostic report.

The five uniqueness axes
─────────────────────────
  1. Common-word penalty   — dictionary words are not unique brand names
  2. Blacklist proximity   — closeness to known protected brands (Levenshtein)
  3. Pool distance         — similarity to other names in the current session
  4. Phonetic distance     — Soundex / Metaphone overlap with pool + blacklist
  5. Visual distinctiveness — character-level trigram novelty vs pool

Relationship to brand_score.score_uniqueness()
────────────────────────────────────────────────
  The scalar function in brand_score.py uses axes 1–3 only (matching the
  original NEXAGEN v1 logic).  This module uses all five axes and produces a
  richer result.  The composite from :func:`score_uniqueness_full` can be
  used as a drop-in replacement for the scalar function.

Public API
──────────
  score_uniqueness_full(name, pool, common, blacklist) → UniquenessReport
  score_uniqueness_scalar(name, pool, common, blacklist) → int   (0–100)
  batch_score_uniqueness(names, common, blacklist)      → list[UniquenessReport]
  rank_by_uniqueness(names, common, blacklist, n)       → list[(str, int)]

Data structures
───────────────
  UniquenessAxis    — score + label + weight + note for one axis
  UniquenessReport  — five axes + composite + verdict + diagnostic notes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..config.constants import (
    TM_LOW_RISK_DISTANCE,
    TM_MEDIUM_RISK_DISTANCE,
    UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE,
)
from ..utils.dataset_loader import blacklist as _load_blacklist
from ..utils.dataset_loader import common_words as _load_common_words
from ..utils.levenshtein import levenshtein, similarity
from ..utils.text_utils import metaphone, soundex

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  AXIS WEIGHTS  (must sum to 1.0)
# ─────────────────────────────────────────────────────────────────────────────

_AXIS_WEIGHTS: dict[str, float] = {
    "common_word":        0.22,
    "blacklist_proximity":0.28,
    "pool_distance":      0.24,
    "phonetic_distance":  0.15,
    "visual_novelty":     0.11,
}

# Baseline uniqueness score before penalties
_BASELINE = 80


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UniquenessAxis:
    """
    Score and explanation for a single uniqueness axis.

    Attributes:
        key:     Machine-readable axis identifier.
        label:   Human-readable axis name.
        score:   Axis score 0–100.
        weight:  Fractional weight in the composite.
        passed:  True if score ≥ 60.
        note:    Short diagnostic message.
    """
    key:    str
    label:  str
    score:  int
    weight: float
    passed: bool  = True
    note:   str   = ""

    @property
    def weighted_contribution(self) -> float:
        return self.score * self.weight

    def __str__(self) -> str:
        tick = "✔" if self.passed else "✘"
        return f"{tick} {self.label:<28} {self.score:>3}/100  {self.note}"


@dataclass
class UniquenessReport:
    """
    Full uniqueness analysis for a single brand name.

    Attributes:
        name:       The candidate name (lowercased).
        composite:  Weighted composite uniqueness score 0–100.
        verdict:    One-word verdict: ``"unique"`` | ``"borderline"`` | ``"common"`` |
                    ``"collision"``
        axes:       List of five :class:`UniquenessAxis` objects.
        is_common_word:     True if name is a plain English dictionary word.
        nearest_blacklist:  Closest protected brand name (empty if none close).
        blacklist_distance: Levenshtein distance to nearest blacklist entry.
        nearest_pool:       Closest name in the current pool (empty if pool empty).
        pool_distance:      Levenshtein distance to nearest pool name.
        notes:      Human-readable diagnostic strings.
    """
    name:               str
    composite:          int
    verdict:            str
    axes:               list[UniquenessAxis]  = field(default_factory=list)
    is_common_word:     bool                  = False
    nearest_blacklist:  str                   = ""
    blacklist_distance: int                   = 99
    nearest_pool:       str                   = ""
    pool_distance:      int                   = 99
    notes:              list[str]             = field(default_factory=list)

    def axis(self, key: str) -> UniquenessAxis | None:
        """Return the axis with the given key, or None."""
        for a in self.axes:
            if a.key == key:
                return a
        return None

    def failing_axes(self) -> list[UniquenessAxis]:
        """Return axes with score < 60."""
        return [a for a in self.axes if not a.passed]

    def __str__(self) -> str:
        return (
            f"UniquenessReport({self.name!r}  "
            f"score={self.composite}/100  verdict={self.verdict})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  AXIS SCORERS
# ─────────────────────────────────────────────────────────────────────────────

def _axis_common_word(
    name:   str,
    common: frozenset[str],
) -> tuple[int, str, bool, str]:
    """
    Common-word penalty axis.

    Returns (score, note, is_common_word, verdict_token).

    A name that IS a common English word scores 30 (heavy penalty).
    A name that STARTS WITH a common word (≥ 4 chars) scores 70.
    Otherwise 100.
    """
    if name in common:
        return 30, f"'{name}' is a plain English dictionary word", True, "common"

    # Partial match: name begins with a meaningful common word
    for w in common:
        if len(w) >= 4 and name.startswith(w) and name != w:
            return 70, f"starts with common word '{w}'", False, "borderline"

    return 100, "not a common word", False, "unique"


def _axis_blacklist_proximity(
    name:      str,
    blacklist: Sequence[str],
) -> tuple[int, str, str, int]:
    """
    Blacklist proximity axis.

    Returns (score, note, nearest_brand, min_distance).

    distance == 0             → 0 (hard zero — exact match)
    distance ≤ TM_MEDIUM      → 20
    distance ≤ TM_LOW         → 55
    distance ≤ TM_LOW + 1     → 75
    else                      → 100
    """
    if not blacklist:
        return 100, "no blacklist provided", "", 99

    min_dist  = 99
    nearest   = ""

    for brand in blacklist:
        d = levenshtein(name, brand.lower())
        if d < min_dist:
            min_dist = d
            nearest  = brand
        if d == 0:
            break

    if min_dist == 0:
        return 0, f"exact match with protected brand '{nearest}'", nearest, 0
    if min_dist <= TM_MEDIUM_RISK_DISTANCE:
        return 20, f"very close to '{nearest}' (dist={min_dist})", nearest, min_dist
    if min_dist <= TM_LOW_RISK_DISTANCE:
        return 55, f"close to '{nearest}' (dist={min_dist})", nearest, min_dist
    if min_dist <= TM_LOW_RISK_DISTANCE + 1:
        return 75, f"near '{nearest}' (dist={min_dist})", nearest, min_dist
    return 100, f"clear of blacklist (nearest: '{nearest}' dist={min_dist})", nearest, min_dist


def _axis_pool_distance(
    name: str,
    pool: Sequence[str],
) -> tuple[int, str, str, int]:
    """
    Pool distance axis — intra-session near-duplicate detection.

    Returns (score, note, nearest_name, min_distance).

    Pool is capped at 80 names to keep per-name cost manageable.
    """
    if not pool:
        return 100, "pool is empty", "", 99

    sample    = [p.lower() for p in pool[:80] if p.lower() != name]
    if not sample:
        return 100, "no other names in pool", "", 99

    min_dist  = min(levenshtein(name, p) for p in sample)
    nearest   = min(sample, key=lambda p: levenshtein(name, p))

    if min_dist <= UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE - 1:  # ≤ 1
        score = 20
        note  = f"near-duplicate of '{nearest}' (dist={min_dist})"
    elif min_dist == UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE:    # == 2
        score = 55
        note  = f"similar to '{nearest}' (dist={min_dist})"
    elif min_dist == UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE + 1: # == 3
        score = 80
        note  = f"somewhat similar to '{nearest}' (dist={min_dist})"
    else:
        score = 100
        note  = f"sufficiently distinct (nearest: '{nearest}' dist={min_dist})"

    return score, note, nearest, min_dist


def _axis_phonetic_distance(
    name:      str,
    pool:      Sequence[str],
    blacklist: Sequence[str],
) -> tuple[int, str]:
    """
    Phonetic distance axis — Soundex / Metaphone collision in pool + blacklist.

    Scores 0 if any pool name or blacklist entry shares BOTH phonetic keys.
    Scores 50 if any entry shares just one key.
    Otherwise 100.
    """
    sx_name = soundex(name)
    mp_name = metaphone(name)

    combined = [p.lower() for p in list(pool)[:50]] + [b.lower() for b in list(blacklist)[:100]]

    for other in combined:
        sx_o = soundex(other)
        mp_o = metaphone(other)
        both_match = (sx_name == sx_o) and (mp_name == mp_o) and bool(mp_name)
        one_match  = (sx_name == sx_o) or ((mp_name == mp_o) and bool(mp_name))

        if both_match:
            return 0, f"sounds identical to '{other}' (sx={sx_name} mp={mp_name})"
        if one_match:
            key = sx_name if sx_name == sx_o else mp_name
            return 50, f"sounds similar to '{other}' (shared key={key})"

    return 100, f"phonetically distinct (sx={sx_name} mp={mp_name})"


def _trigrams(word: str) -> set[str]:
    """Return the set of all 3-character n-grams in *word*."""
    if len(word) < 3:
        return set()
    return {word[i:i+3] for i in range(len(word) - 2)}


def _axis_visual_novelty(
    name: str,
    pool: Sequence[str],
) -> tuple[int, str]:
    """
    Visual novelty axis — trigram overlap with pool names.

    A name is visually novel if it doesn't share many character sequences
    with other names in the pool.  Scores based on the maximum Jaccard
    trigram overlap with any pool member.
    """
    if not pool:
        return 100, "no pool comparison possible"

    name_tg = _trigrams(name)
    if not name_tg:
        return 80, "name too short for trigram comparison"

    max_overlap = 0.0
    most_similar = ""

    for other in [p.lower() for p in pool[:60] if p.lower() != name]:
        other_tg = _trigrams(other)
        if not other_tg:
            continue
        intersection = len(name_tg & other_tg)
        union        = len(name_tg | other_tg)
        overlap      = intersection / union if union else 0.0
        if overlap > max_overlap:
            max_overlap  = overlap
            most_similar = other

    if max_overlap >= 0.75:
        score = 25
        note  = f"high trigram overlap ({max_overlap:.0%}) with '{most_similar}'"
    elif max_overlap >= 0.55:
        score = 60
        note  = f"moderate trigram overlap ({max_overlap:.0%}) with '{most_similar}'"
    elif max_overlap >= 0.35:
        score = 80
        note  = f"low trigram overlap ({max_overlap:.0%})"
    else:
        score = 100
        note  = f"visually novel (max overlap {max_overlap:.0%})"

    return score, note


# ─────────────────────────────────────────────────────────────────────────────
# § 4  COMPOSITE SCORER
# ─────────────────────────────────────────────────────────────────────────────

def score_uniqueness_full(
    name:      str,
    pool:      Sequence[str]               = (),
    common:    Optional[frozenset[str]]    = None,
    blacklist: Optional[Sequence[str]]     = None,
) -> UniquenessReport:
    """
    Run the full five-axis uniqueness analysis.

    The *pool* should contain ALL other candidate names generated in the
    current session — not just the already-scored ones.  This ensures
    intra-pool deduplication catches siblings generated from the same
    keyword seeds.

    Args:
        name:      Candidate brand name (lowercased internally).
        pool:      All other candidate names in the session.
        common:    Frozenset of common English words. Auto-loaded if None.
        blacklist: Sequence of protected brand names. Auto-loaded if None.

    Returns:
        :class:`UniquenessReport`
    """
    if common is None:
        common = _load_common_words()
    if blacklist is None:
        blacklist = list(_load_blacklist())

    word = name.lower().strip()
    pool_lower = [p.lower() for p in pool if p.lower() != word]

    # ── Run all five axes ─────────────────────────────────────────────────────
    cw_score, cw_note, is_common, _   = _axis_common_word(word, common)
    bl_score, bl_note, nearest_bl, bl_dist = _axis_blacklist_proximity(word, blacklist)
    pd_score, pd_note, nearest_pl, pl_dist = _axis_pool_distance(word, pool_lower)
    ph_score, ph_note = _axis_phonetic_distance(word, pool_lower, blacklist)
    vn_score, vn_note = _axis_visual_novelty(word, pool_lower)

    axes = [
        UniquenessAxis("common_word",         "Common Word",        cw_score, _AXIS_WEIGHTS["common_word"],         cw_score >= 60, cw_note),
        UniquenessAxis("blacklist_proximity",  "Blacklist Proximity",bl_score, _AXIS_WEIGHTS["blacklist_proximity"], bl_score >= 60, bl_note),
        UniquenessAxis("pool_distance",        "Pool Distance",      pd_score, _AXIS_WEIGHTS["pool_distance"],       pd_score >= 60, pd_note),
        UniquenessAxis("phonetic_distance",    "Phonetic Distance",  ph_score, _AXIS_WEIGHTS["phonetic_distance"],   ph_score >= 60, ph_note),
        UniquenessAxis("visual_novelty",       "Visual Novelty",     vn_score, _AXIS_WEIGHTS["visual_novelty"],      vn_score >= 60, vn_note),
    ]

    # ── Composite ─────────────────────────────────────────────────────────────
    composite = max(0, min(100, round(sum(a.weighted_contribution for a in axes))))

    # Exact blacklist match → composite floor of 0
    if bl_dist == 0:
        composite = 0

    # ── Verdict ───────────────────────────────────────────────────────────────
    if composite >= 75 and bl_dist >= 4:
        verdict = "unique"
    elif composite >= 55:
        verdict = "borderline"
    elif is_common or bl_dist <= TM_LOW_RISK_DISTANCE:
        verdict = "collision" if bl_dist <= TM_MEDIUM_RISK_DISTANCE else "common"
    else:
        verdict = "common"

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes: list[str] = []
    failing = [a for a in axes if not a.passed]
    if failing:
        notes.append("Weak axes: " + ", ".join(a.label for a in failing))
    if is_common:
        notes.append(f"⚠ '{word}' is a common English word — not brandable on its own.")
    if bl_dist <= TM_MEDIUM_RISK_DISTANCE and nearest_bl:
        notes.append(f"⚠ Too close to protected brand '{nearest_bl}' (dist={bl_dist}).")
    if pl_dist <= UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE and nearest_pl:
        notes.append(f"⚠ Near-duplicate of pool member '{nearest_pl}' (dist={pl_dist}).")
    if composite >= 75:
        notes.append("Uniqueness is strong — name is clearly distinct.")
    elif composite >= 55:
        notes.append("Uniqueness is borderline — consider minor variations.")

    return UniquenessReport(
        name               = word,
        composite          = composite,
        verdict            = verdict,
        axes               = axes,
        is_common_word     = is_common,
        nearest_blacklist  = nearest_bl,
        blacklist_distance = bl_dist,
        nearest_pool       = nearest_pl,
        pool_distance      = pl_dist,
        notes              = notes,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SCALAR DROP-IN  (matches brand_score.score_uniqueness signature)
# ─────────────────────────────────────────────────────────────────────────────

def score_uniqueness_scalar(
    name:      str,
    pool:      Sequence[str]               = (),
    common:    Optional[frozenset[str]]    = None,
    blacklist: Optional[Sequence[str]]     = None,
) -> int:
    """
    Return a single composite uniqueness score 0–100.

    Drop-in replacement for :func:`brand_score.score_uniqueness` that uses
    the five-axis model instead of three axes.

    Args:
        name:      Candidate brand name.
        pool:      Other candidate names in the session.
        common:    Common English words. Auto-loaded if None.
        blacklist: Protected brand names. Auto-loaded if None.

    Returns:
        Integer score 0–100.
    """
    return score_uniqueness_full(name, pool, common, blacklist).composite


# ─────────────────────────────────────────────────────────────────────────────
# § 6  BATCH SCORING
# ─────────────────────────────────────────────────────────────────────────────

def batch_score_uniqueness(
    names:     Sequence[str],
    common:    Optional[frozenset[str]] = None,
    blacklist: Optional[Sequence[str]]  = None,
) -> list[UniquenessReport]:
    """
    Score uniqueness for every name in *names*, treating the full list as
    the pool for intra-session comparison.

    Each name is scored against all OTHER names in the list.

    Args:
        names:     All candidate names.
        common:    Common words. Auto-loaded if None.
        blacklist: Protected brand names. Auto-loaded if None.

    Returns:
        List of :class:`UniquenessReport` in input order.
    """
    if common is None:
        common = _load_common_words()
    if blacklist is None:
        blacklist = list(_load_blacklist())

    names_list = list(names)
    reports: list[UniquenessReport] = []

    for i, name in enumerate(names_list):
        pool = names_list[:i] + names_list[i+1:]
        report = score_uniqueness_full(name, pool, common, blacklist)
        reports.append(report)

    return reports


def rank_by_uniqueness(
    names:     Sequence[str],
    common:    Optional[frozenset[str]] = None,
    blacklist: Optional[Sequence[str]]  = None,
    *,
    n:         int = 0,
) -> list[tuple[str, int]]:
    """
    Rank names by uniqueness score, highest first.

    Args:
        names:     Candidate names.
        common:    Common words. Auto-loaded if None.
        blacklist: Protected brand names. Auto-loaded if None.
        n:         Return at most *n* results (0 = all).

    Returns:
        List of ``(name, score)`` tuples sorted by score descending.
    """
    reports = batch_score_uniqueness(names, common, blacklist)
    ranked  = [(r.name, r.composite) for r in reports]
    ranked.sort(key=lambda x: -x[1])
    return ranked[:n] if n > 0 else ranked


def filter_unique(
    names:     Sequence[str],
    threshold: int                      = 60,
    common:    Optional[frozenset[str]] = None,
    blacklist: Optional[Sequence[str]]  = None,
) -> list[str]:
    """
    Return only names whose uniqueness score meets *threshold*.

    Args:
        names:     Candidate names.
        threshold: Minimum composite uniqueness score to keep (default 60).
        common:    Common words. Auto-loaded if None.
        blacklist: Protected brand names. Auto-loaded if None.

    Returns:
        Filtered list preserving original order.
    """
    reports = batch_score_uniqueness(names, common, blacklist)
    return [r.name for r in reports if r.composite >= threshold]
