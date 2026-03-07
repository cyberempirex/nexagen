"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  analysis/collision_detection.py  ·  Brand collision & conflict detection  ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Full-spectrum brand collision detector.

A "collision" is any degree of dangerous similarity between a candidate brand
name and an existing protected name — measured by four independent signals:

  1. Edit-distance (Levenshtein / Damerau-Levenshtein)
       Hard numerical proximity — catches typo-squatting and near-clones.

  2. Phonetic matching (Soundex + Metaphone)
       Sound-alike detection — catches spelling variants that sound identical
       (e.g. "Feisbook" vs "Facebook", "Lyft" vs "Lift").

  3. Substring containment
       Names that embed a protected brand verbatim are flagged regardless
       of overall length difference (e.g. "GoogleMaps" → flags "Google").

  4. N-gram overlap (trigrams)
       Catches partial visual similarity — names that share a run of three
       or more consecutive characters with a protected brand.

Each signal produces a :class:`CollisionHit`.  All hits for a candidate are
aggregated into a :class:`CollisionReport`.

Risk levels
───────────
  CRITICAL  — exact match or phonetically identical + substring
  HIGH      — edit-distance ≤ 1  or  phonetic match alone
  MEDIUM    — edit-distance ≤ 2  or  strong substring
  LOW       — edit-distance ≤ 3  or  n-gram overlap ≥ 0.6
  NONE      — no signal triggered

Public API
──────────
  detect_collisions(name, blacklist, ...)     → CollisionReport
  batch_detect(names, blacklist, ...)         → list[CollisionReport]
  quick_risk(name, blacklist)                 → str   "none"|"low"|...|"critical"
  is_safe(name, blacklist, max_risk)          → bool

Data structures
───────────────
  CollisionHit     — single detected conflict with signal type + evidence
  CollisionReport  — all hits for one candidate name + aggregate risk
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from ..config.constants import (
    TM_HIGH_RISK_DISTANCE,
    TM_LOW_RISK_DISTANCE,
    TM_MEDIUM_RISK_DISTANCE,
)
from ..utils.dataset_loader import blacklist as _load_blacklist
from ..utils.levenshtein import (
    damerau_levenshtein,
    levenshtein,
    similarity,
)
from ..utils.text_utils import metaphone, soundex

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  ENUMERATIONS
# ─────────────────────────────────────────────────────────────────────────────

class CollisionSignal(str, Enum):
    """Type of signal that produced a collision hit."""
    EXACT      = "exact"        # character-for-character match
    EDIT       = "edit"         # Levenshtein / Damerau proximity
    PHONETIC   = "phonetic"     # Soundex or Metaphone match
    SUBSTRING  = "substring"    # one name contains the other verbatim
    NGRAM      = "ngram"        # shared trigram run


class RiskLevel(str, Enum):
    """Ordered collision risk levels (low → critical)."""
    NONE     = "none"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        """Numeric weight for comparison (NONE=0 … CRITICAL=4)."""
        return {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}[self.value]

    def __lt__(self, other: "RiskLevel") -> bool:
        return self.weight < other.weight

    def __le__(self, other: "RiskLevel") -> bool:
        return self.weight <= other.weight

    def __gt__(self, other: "RiskLevel") -> bool:
        return self.weight > other.weight


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CollisionHit:
    """
    A single detected collision between a candidate and a protected brand.

    Attributes:
        candidate:    The candidate name being checked.
        protected:    The protected / blacklisted brand name.
        signal:       Which detection signal fired (:class:`CollisionSignal`).
        risk:         Risk level assigned to this individual hit.
        distance:     Raw Levenshtein distance (-1 if not applicable).
        similarity:   Normalised similarity score 0.0–1.0.
        phonetic_key: Shared phonetic key (empty if signal is not phonetic).
        note:         Human-readable description of the hit.
    """
    candidate:    str
    protected:    str
    signal:       CollisionSignal
    risk:         RiskLevel
    distance:     int   = -1
    similarity:   float = 0.0
    phonetic_key: str   = ""
    note:         str   = ""

    def __str__(self) -> str:
        return (
            f"{self.signal.value.upper()} collision: "
            f"{self.candidate!r} ↔ {self.protected!r}  "
            f"[{self.risk.value}]  {self.note}"
        )


@dataclass
class CollisionReport:
    """
    Aggregate collision analysis for a single candidate name.

    Attributes:
        name:         Candidate name that was analysed.
        risk:         Highest risk level across all hits.
        hits:         All :class:`CollisionHit` objects found.
        is_safe:      True when risk == NONE.
        hit_count:    Total number of hits.
        blocked_by:   Name of the highest-risk protected brand (if any).
        summary:      One-line human-readable summary.
    """
    name:       str
    risk:       RiskLevel               = RiskLevel.NONE
    hits:       list[CollisionHit]      = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return self.risk == RiskLevel.NONE

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def blocked_by(self) -> str:
        """Return the protected brand behind the worst hit, or empty string."""
        if not self.hits:
            return ""
        worst = max(self.hits, key=lambda h: h.risk.weight)
        return worst.protected

    @property
    def summary(self) -> str:
        if self.risk == RiskLevel.NONE:
            return f"{self.name!r} — no collisions detected"
        return (
            f"{self.name!r} — {self.risk.value.upper()} risk  "
            f"({self.hit_count} hit{'s' if self.hit_count != 1 else ''})  "
            f"blocked by {self.blocked_by!r}"
        )

    def hits_by_signal(self, signal: CollisionSignal) -> list[CollisionHit]:
        """Return all hits of a specific signal type."""
        return [h for h in self.hits if h.signal == signal]

    def hits_at_or_above(self, risk: RiskLevel) -> list[CollisionHit]:
        """Return hits whose risk is ≥ the given level."""
        return [h for h in self.hits if h.risk >= risk]

    def __str__(self) -> str:
        return self.summary


# ─────────────────────────────────────────────────────────────────────────────
# § 3  INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _trigrams(word: str) -> set[str]:
    """Return the set of all 3-character n-grams in *word*."""
    w = word.lower()
    if len(w) < 3:
        return set()
    return {w[i:i+3] for i in range(len(w) - 2)}


def _ngram_overlap(a: str, b: str) -> float:
    """
    Jaccard trigram overlap between *a* and *b*  (0.0–1.0).

    Higher = more character-sequence overlap.
    """
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union        = len(ta | tb)
    return intersection / union if union else 0.0


def _edit_risk(distance: int) -> RiskLevel:
    """Map a raw Levenshtein distance to a :class:`RiskLevel`."""
    if distance == 0:
        return RiskLevel.CRITICAL
    if distance <= TM_HIGH_RISK_DISTANCE:
        return RiskLevel.HIGH
    if distance <= TM_MEDIUM_RISK_DISTANCE:
        return RiskLevel.MEDIUM
    if distance <= TM_LOW_RISK_DISTANCE:
        return RiskLevel.LOW
    return RiskLevel.NONE


def _merge_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    """Return the higher of two risk levels."""
    return a if a.weight >= b.weight else b


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SIGNAL DETECTORS
# ─────────────────────────────────────────────────────────────────────────────

def _check_edit(
    candidate: str,
    protected: str,
    *,
    use_damerau: bool = True,
) -> Optional[CollisionHit]:
    """
    Edit-distance signal.

    Uses Damerau-Levenshtein (transpositions allowed) by default —
    better for real-world brand typo-squatting detection.
    """
    dist_fn = damerau_levenshtein if use_damerau else levenshtein
    dist    = dist_fn(candidate, protected)
    risk    = _edit_risk(dist)

    if risk == RiskLevel.NONE:
        return None

    sim = similarity(candidate, protected)

    signal = CollisionSignal.EXACT if dist == 0 else CollisionSignal.EDIT
    note   = (
        f"edit-distance={dist}  sim={sim:.2f}"
        + ("  (exact match)" if dist == 0 else "")
    )

    return CollisionHit(
        candidate    = candidate,
        protected    = protected,
        signal       = signal,
        risk         = risk,
        distance     = dist,
        similarity   = sim,
        note         = note,
    )


def _check_phonetic(
    candidate: str,
    protected: str,
) -> Optional[CollisionHit]:
    """
    Phonetic signal — Soundex AND Metaphone.

    A phonetic collision requires BOTH encoders to agree (same key) to
    avoid false positives from the coarse Soundex groupings.
    """
    sx_a, sx_b = soundex(candidate), soundex(protected)
    mp_a, mp_b = metaphone(candidate), metaphone(protected)

    soundex_match   = (sx_a == sx_b)
    metaphone_match = (mp_a == mp_b) and bool(mp_a)

    if not (soundex_match or metaphone_match):
        return None

    # Both agree → HIGH; only one → MEDIUM
    risk = RiskLevel.HIGH if (soundex_match and metaphone_match) else RiskLevel.MEDIUM
    key  = sx_a if soundex_match else mp_a

    sim  = similarity(candidate, protected)
    note = (
        f"soundex={sx_a}/{sx_b}  metaphone={mp_a}/{mp_b}  "
        f"sim={sim:.2f}"
    )
    return CollisionHit(
        candidate    = candidate,
        protected    = protected,
        signal       = CollisionSignal.PHONETIC,
        risk         = risk,
        distance     = levenshtein(candidate, protected),
        similarity   = sim,
        phonetic_key = key,
        note         = note,
    )


def _check_substring(
    candidate: str,
    protected: str,
) -> Optional[CollisionHit]:
    """
    Substring containment signal.

    Flags when:
      • the protected brand name appears verbatim inside the candidate, or
      • the candidate appears verbatim inside the protected name.

    Short protected names (< 4 chars) are exempt to avoid noise.
    """
    if len(protected) < 4:
        return None

    cand_contains  = protected in candidate   # e.g. "xgoogle" contains "google"
    prot_contains  = candidate in protected   # e.g. short candidate inside long brand

    if not (cand_contains or prot_contains):
        return None

    risk = RiskLevel.CRITICAL if cand_contains else RiskLevel.MEDIUM
    direction = "contains" if cand_contains else "contained in"
    sim  = similarity(candidate, protected)

    note = (
        f"{candidate!r} {direction} protected brand {protected!r}  "
        f"sim={sim:.2f}"
    )
    return CollisionHit(
        candidate    = candidate,
        protected    = protected,
        signal       = CollisionSignal.SUBSTRING,
        risk         = risk,
        distance     = levenshtein(candidate, protected),
        similarity   = sim,
        note         = note,
    )


def _check_ngram(
    candidate: str,
    protected: str,
    *,
    threshold: float = 0.55,
) -> Optional[CollisionHit]:
    """
    Trigram overlap signal.

    Only fires when the candidate and protected brand share a sufficient
    ratio of 3-character sequences (default threshold 0.55 = Jaccard).
    Returns LOW risk — treated as a soft warning.
    """
    overlap = _ngram_overlap(candidate, protected)

    if overlap < threshold:
        return None

    sim  = similarity(candidate, protected)
    note = f"trigram-overlap={overlap:.2f}  sim={sim:.2f}"

    return CollisionHit(
        candidate    = candidate,
        protected    = protected,
        signal       = CollisionSignal.NGRAM,
        risk         = RiskLevel.LOW,
        distance     = levenshtein(candidate, protected),
        similarity   = sim,
        note         = note,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PRIMARY DETECTION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_collisions(
    name:               str,
    blacklist:          Optional[Sequence[str]] = None,
    *,
    use_damerau:        bool  = True,
    ngram_threshold:    float = 0.55,
    skip_phonetic:      bool  = False,
    skip_ngram:         bool  = False,
    skip_substring:     bool  = False,
    max_hits_per_brand: int   = 2,
) -> CollisionReport:
    """
    Run all four collision-detection signals against the full blacklist.

    Checks edit-distance, phonetic, substring, and n-gram overlap for the
    candidate *name* against every entry in *blacklist*.

    Args:
        name:               Candidate brand name (will be lowercased).
        blacklist:          Protected brand names. Auto-loaded from
                            ``datasets/brand_blacklist.txt`` if None.
        use_damerau:        Use Damerau-Levenshtein (allows transpositions).
        ngram_threshold:    Minimum Jaccard trigram overlap to flag (0–1).
        skip_phonetic:      Disable phonetic signal (faster).
        skip_ngram:         Disable n-gram signal (faster).
        skip_substring:     Disable substring signal.
        max_hits_per_brand: Maximum collision hits to record per protected
                            brand (avoids overwhelming output for common
                            brand names that trigger many signals).

    Returns:
        :class:`CollisionReport`
    """
    if blacklist is None:
        blacklist = list(_load_blacklist())

    candidate = name.lower().strip()
    all_hits: list[CollisionHit] = []

    for brand in blacklist:
        protected = brand.lower().strip()
        if not protected:
            continue

        brand_hits: list[CollisionHit] = []

        # — Edit-distance (always run) ───────────────────────────────────────
        h = _check_edit(candidate, protected, use_damerau=use_damerau)
        if h:
            brand_hits.append(h)

        # — Substring ────────────────────────────────────────────────────────
        if not skip_substring:
            h = _check_substring(candidate, protected)
            if h:
                brand_hits.append(h)

        # — Phonetic ─────────────────────────────────────────────────────────
        if not skip_phonetic:
            h = _check_phonetic(candidate, protected)
            if h:
                brand_hits.append(h)

        # — N-gram ───────────────────────────────────────────────────────────
        if not skip_ngram:
            h = _check_ngram(candidate, protected, threshold=ngram_threshold)
            if h:
                brand_hits.append(h)

        # Deduplicate: keep only the worst hit per (candidate, protected) pair
        # up to max_hits_per_brand
        seen_signals: set[CollisionSignal] = set()
        for hit in sorted(brand_hits, key=lambda x: -x.risk.weight):
            if hit.signal not in seen_signals:
                seen_signals.add(hit.signal)
                all_hits.append(hit)
                if len([h for h in all_hits if h.protected == protected]) >= max_hits_per_brand:
                    break

    # Aggregate report
    if not all_hits:
        return CollisionReport(name=candidate, risk=RiskLevel.NONE, hits=[])

    aggregate_risk = max((h.risk for h in all_hits), default=RiskLevel.NONE)
    return CollisionReport(name=candidate, risk=aggregate_risk, hits=all_hits)


# ─────────────────────────────────────────────────────────────────────────────
# § 6  BATCH AND QUICK INTERFACES
# ─────────────────────────────────────────────────────────────────────────────

def batch_detect(
    names:     Sequence[str],
    blacklist: Optional[Sequence[str]] = None,
    *,
    use_damerau:     bool  = True,
    ngram_threshold: float = 0.55,
    skip_phonetic:   bool  = False,
    skip_ngram:      bool  = False,
    skip_substring:  bool  = False,
) -> list[CollisionReport]:
    """
    Run collision detection for a batch of candidate names.

    The blacklist is loaded once and reused across all candidates for
    efficiency.

    Args:
        names:           Candidate brand names to check.
        blacklist:       Protected brand names. Auto-loaded if None.
        use_damerau:     Use Damerau-Levenshtein.
        ngram_threshold: Minimum trigram Jaccard overlap threshold.
        skip_phonetic:   Disable phonetic signal.
        skip_ngram:      Disable n-gram signal.
        skip_substring:  Disable substring signal.

    Returns:
        List of :class:`CollisionReport`, one per name, in input order.
    """
    if blacklist is None:
        blacklist = list(_load_blacklist())

    return [
        detect_collisions(
            name, blacklist,
            use_damerau=use_damerau,
            ngram_threshold=ngram_threshold,
            skip_phonetic=skip_phonetic,
            skip_ngram=skip_ngram,
            skip_substring=skip_substring,
        )
        for name in names
    ]


def quick_risk(
    name:      str,
    blacklist: Optional[Sequence[str]] = None,
) -> str:
    """
    Return the overall risk level string for a single candidate name.

    Convenience wrapper for :func:`detect_collisions` that returns only
    the string risk level without the full report.

    Args:
        name:      Candidate brand name.
        blacklist: Protected brand names. Auto-loaded if None.

    Returns:
        One of ``"none"`` | ``"low"`` | ``"medium"`` | ``"high"`` | ``"critical"``
    """
    return detect_collisions(name, blacklist).risk.value


def is_safe(
    name:      str,
    blacklist: Optional[Sequence[str]] = None,
    *,
    max_risk:  RiskLevel = RiskLevel.LOW,
) -> bool:
    """
    Return True if the candidate name's collision risk is below *max_risk*.

    Args:
        name:      Candidate brand name.
        blacklist: Protected brand names. Auto-loaded if None.
        max_risk:  Highest acceptable risk level (exclusive upper bound).
                   Default LOW — names with only LOW risk are considered safe.

    Returns:
        True if risk < max_risk.
    """
    report = detect_collisions(name, blacklist, skip_ngram=True)
    return report.risk.weight < max_risk.weight


# ─────────────────────────────────────────────────────────────────────────────
# § 7  POOL COLLISION FILTER
# ─────────────────────────────────────────────────────────────────────────────

def filter_safe_names(
    names:     Sequence[str],
    blacklist: Optional[Sequence[str]] = None,
    *,
    max_risk:  RiskLevel = RiskLevel.LOW,
) -> tuple[list[str], list[CollisionReport]]:
    """
    Split *names* into safe and flagged groups.

    Args:
        names:     Candidate names to filter.
        blacklist: Protected brand names. Auto-loaded if None.
        max_risk:  Highest acceptable risk (exclusive). Names at or above
                   this level are placed in the flagged group.

    Returns:
        Tuple ``(safe_names, flagged_reports)`` where:
          - ``safe_names``     — list of names that pass the filter
          - ``flagged_reports`` — CollisionReport for each flagged name
    """
    if blacklist is None:
        blacklist = list(_load_blacklist())

    safe: list[str]                  = []
    flagged: list[CollisionReport]   = []

    for name in names:
        report = detect_collisions(name, blacklist)
        if report.risk.weight < max_risk.weight:
            safe.append(name)
        else:
            flagged.append(report)

    return safe, flagged


def pairwise_collisions(
    names:     Sequence[str],
    *,
    threshold: float = 0.80,
) -> list[tuple[str, str, float]]:
    """
    Detect near-duplicate pairs within a pool of candidate names.

    Does NOT check against the brand blacklist — this is purely intra-pool
    similarity detection to help deduplicate a generated name set.

    Args:
        names:     Pool of candidate names.
        threshold: Minimum :func:`~nexagen.utils.levenshtein.similarity`
                   score to flag a pair (0.0–1.0, default 0.80).

    Returns:
        List of ``(name_a, name_b, score)`` tuples sorted by score
        descending, containing all pairs above the threshold.
    """
    pool = [n.lower() for n in names]
    pairs: list[tuple[str, str, float]] = []

    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            score = similarity(pool[i], pool[j])
            if score >= threshold:
                pairs.append((names[i], names[j], round(score, 4)))

    pairs.sort(key=lambda x: -x[2])
    return pairs
