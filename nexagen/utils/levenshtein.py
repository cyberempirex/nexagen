"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  utils/levenshtein.py  ·  Edit-distance & fuzzy similarity engine           ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Implements multiple string-distance algorithms used throughout NEXAGEN for:

  • Trademark collision detection
  • Near-duplicate name filtering
  • Fuzzy brand-blacklist matching
  • Domain availability scoring
  • Uniqueness scoring

All algorithms are pure Python — no external dependencies required.
The module auto-promotes to the C-extension ``rapidfuzz`` library when
available for a 10–50× speed boost on batch operations.

Public API:
  levenshtein(a, b)              → int
  damerau_levenshtein(a, b)      → int
  jaro(a, b)                     → float  (0.0–1.0)
  jaro_winkler(a, b)             → float  (0.0–1.0)
  similarity(a, b)               → float  (0.0–1.0)
  is_similar(a, b, threshold)    → bool
  closest_match(query, pool)     → (str, float)
  find_duplicates(names, thresh) → list[(str, str, float)]
  batch_similarity(a, many)      → list[(str, float)]
  deduplicate(names, threshold)  → list[str]
  trademark_risk(name, blacklist) → (str|None, int|None)
"""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import NamedTuple, Sequence

# ─────────────────────────────────────────────────────────────────────────────
# § 1  BACKEND SELECTION  (rapidfuzz → pure Python fallback)
# ─────────────────────────────────────────────────────────────────────────────

_USE_RAPIDFUZZ = False

try:
    import rapidfuzz.distance as _rf_dist          # type: ignore[import]
    import rapidfuzz.fuzz    as _rf_fuzz           # type: ignore[import]
    _USE_RAPIDFUZZ = True
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# § 2  CORE DISTANCE ALGORITHMS  (pure Python implementations)
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=16384)
def levenshtein(a: str, b: str) -> int:
    """
    Classic Wagner-Fischer Levenshtein edit distance.

    Operations allowed: insertion, deletion, substitution.
    Complexity: O(|a| × |b|) time, O(min(|a|, |b|)) space.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Minimum number of single-character edits to transform a → b.

    Examples:
        >>> levenshtein("nexagen", "nexagen")  → 0
        >>> levenshtein("google",  "googel")   → 1   (transposition)
        >>> levenshtein("kitten",  "sitting")  → 3
    """
    if _USE_RAPIDFUZZ:
        return _rf_dist.Levenshtein.distance(a, b)  # type: ignore[union-attr]

    # Early exits
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Ensure a is the shorter string for O(min) space
    if len(a) > len(b):
        a, b = b, a

    la, lb = len(a), len(b)
    previous = list(range(lb + 1))
    current  = [0] * (lb + 1)

    for i in range(1, la + 1):
        current[0] = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(
                previous[j] + 1,           # deletion
                current[j - 1] + 1,        # insertion
                previous[j - 1] + cost,    # substitution
            )
        previous, current = current, previous

    return previous[lb]


@lru_cache(maxsize=8192)
def damerau_levenshtein(a: str, b: str) -> int:
    """
    Damerau-Levenshtein distance — like Levenshtein but also allows
    transpositions of two adjacent characters.

    This is better for brand name comparison because human typos frequently
    involve transpositions (e.g., "googel" → "google").

    Complexity: O(|a| × |b|) time and space.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    la, lb = len(a), len(b)
    # Full matrix — needed for transposition tracking
    d: list[list[int]] = [[0] * (lb + 1) for _ in range(la + 1)]

    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j

    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,           # deletion
                d[i][j - 1] + 1,           # insertion
                d[i - 1][j - 1] + cost,    # substitution
            )
            # Transposition
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + cost)

    return d[la][lb]


@lru_cache(maxsize=8192)
def jaro(a: str, b: str) -> float:
    """
    Jaro similarity score (0.0–1.0, where 1.0 = identical).

    Particularly useful for short strings like brand names.
    More tolerant of character transpositions than plain edit distance.

    Examples:
        >>> jaro("nexagen", "nexagen")  → 1.0
        >>> jaro("martha",  "marhta")   → 0.944
        >>> jaro("abc",     "xyz")      → 0.0
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    match_window = max(len(a), len(b)) // 2 - 1
    if match_window < 0:
        match_window = 0

    a_matched = [False] * len(a)
    b_matched = [False] * len(b)
    matches = 0
    transpositions = 0

    for i, ca in enumerate(a):
        start = max(0, i - match_window)
        end   = min(i + match_window + 1, len(b))
        for j in range(start, end):
            if b_matched[j] or ca != b[j]:
                continue
            a_matched[i] = True
            b_matched[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i, matched in enumerate(a_matched):
        if not matched:
            continue
        while not b_matched[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1

    return (
        matches / len(a)
        + matches / len(b)
        + (matches - transpositions / 2) / matches
    ) / 3.0


@lru_cache(maxsize=8192)
def jaro_winkler(
    a: str,
    b: str,
    prefix_weight: float = 0.1,
    max_prefix: int = 4,
) -> float:
    """
    Jaro-Winkler similarity — extends Jaro by boosting pairs that share
    a common prefix (up to 4 characters).

    Prefix boost reflects the intuition that brand names sharing a start
    are very likely related (e.g., "nexagen" / "nexaflow").

    Args:
        a, b:           Strings to compare.
        prefix_weight:  How much to boost for each matching prefix char (max 0.25).
        max_prefix:     Maximum prefix length considered (standard: 4).

    Returns:
        Similarity score 0.0–1.0.
    """
    base = jaro(a, b)
    if base < 0.7:
        return base

    prefix_len = 0
    for i in range(min(len(a), len(b), max_prefix)):
        if a[i] == b[i]:
            prefix_len += 1
        else:
            break

    boost = min(prefix_len * prefix_weight, 0.25)
    return base + boost * (1.0 - base)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  NORMALISED SIMILARITY SCORES
# ─────────────────────────────────────────────────────────────────────────────

def similarity(a: str, b: str) -> float:
    """
    Normalised similarity score between 0.0 (completely different) and
    1.0 (identical), combining Levenshtein distance and Jaro-Winkler.

    This is the primary similarity function used in deduplication and
    trademark risk assessment throughout NEXAGEN.

    Formula: weighted average of:
      - Normalised Levenshtein  (60 %)
      - Jaro-Winkler            (40 %)
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    a_norm = a.lower()
    b_norm = b.lower()

    # Normalised Levenshtein: 1 - dist / max_len
    dist = levenshtein(a_norm, b_norm)
    max_len = max(len(a_norm), len(b_norm))
    norm_lev = 1.0 - (dist / max_len)

    # Jaro-Winkler
    jw = jaro_winkler(a_norm, b_norm)

    return 0.60 * norm_lev + 0.40 * jw


def normalized_levenshtein(a: str, b: str) -> float:
    """
    Levenshtein distance normalised to [0.0, 1.0].
    0.0 = identical, 1.0 = completely different.
    """
    if a == b:
        return 0.0
    if not a or not b:
        return 1.0
    dist = levenshtein(a.lower(), b.lower())
    return dist / max(len(a), len(b))


def normalized_similarity(a: str, b: str) -> float:
    """Alias: 1.0 – normalised_levenshtein. Identical strings → 1.0."""
    return 1.0 - normalized_levenshtein(a, b)


# ─────────────────────────────────────────────────────────────────────────────
# § 4  THRESHOLD-BASED CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def is_similar(
    a: str,
    b: str,
    threshold: float = 0.80,
) -> bool:
    """
    Return True if the similarity score between a and b is ≥ threshold.

    Default threshold of 0.80 catches most brand-level lookalikes while
    avoiding false positives on genuinely different names.
    """
    return similarity(a, b) >= threshold


def is_near_duplicate(
    a: str,
    b: str,
    max_distance: int = 2,
) -> bool:
    """
    Return True if the Levenshtein distance is ≤ max_distance.
    Used in the deduplication filter during name generation.
    """
    return levenshtein(a.lower(), b.lower()) <= max_distance


def is_substring_match(query: str, target: str) -> bool:
    """Return True if query is a substring of target (case-insensitive)."""
    return query.lower() in target.lower()


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SEARCH / LOOKUP
# ─────────────────────────────────────────────────────────────────────────────

class MatchResult(NamedTuple):
    """Result of a closest-match search."""
    match:      str
    score:      float   # 0.0–1.0, higher = more similar
    distance:   int     # raw Levenshtein distance

    def __repr__(self) -> str:
        return f"MatchResult(match={self.match!r}, score={self.score:.3f}, dist={self.distance})"


def closest_match(
    query: str,
    pool: Sequence[str],
    *,
    use_jaro_winkler: bool = True,
) -> MatchResult | None:
    """
    Find the most similar string to ``query`` in ``pool``.

    Args:
        query:            The string to find a match for.
        pool:             Collection of candidate strings.
        use_jaro_winkler: If True, use combined score; else pure Levenshtein.

    Returns:
        MatchResult with the best match, or None if pool is empty.
    """
    if not pool:
        return None

    q = query.lower()
    best_match  = ""
    best_score  = -1.0
    best_dist   = sys.maxsize

    for candidate in pool:
        c = candidate.lower()
        dist = levenshtein(q, c)
        score = similarity(q, c) if use_jaro_winkler else (
            1.0 - dist / max(len(q), len(c), 1)
        )
        if score > best_score or (score == best_score and dist < best_dist):
            best_score = score
            best_match = candidate
            best_dist  = dist

    return MatchResult(match=best_match, score=best_score, distance=best_dist)


def top_matches(
    query: str,
    pool: Sequence[str],
    n: int = 5,
    min_score: float = 0.5,
) -> list[MatchResult]:
    """
    Return the top-n most similar strings from pool, sorted by score descending.

    Args:
        query:     Query string.
        pool:      Candidate pool.
        n:         Maximum number of results to return.
        min_score: Minimum similarity score to include in results.
    """
    q = query.lower()
    results: list[MatchResult] = []

    for candidate in pool:
        c    = candidate.lower()
        dist  = levenshtein(q, c)
        score = similarity(q, c)
        if score >= min_score:
            results.append(MatchResult(candidate, score, dist))

    results.sort(key=lambda r: (-r.score, r.distance))
    return results[:n]


def batch_similarity(
    query: str,
    targets: Sequence[str],
) -> list[tuple[str, float]]:
    """
    Compute similarity between query and each target string.

    Returns:
        List of (target, score) tuples, unsorted.
    """
    q = query.lower()
    return [(t, similarity(q, t.lower())) for t in targets]


# ─────────────────────────────────────────────────────────────────────────────
# § 6  DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def find_duplicates(
    names: Sequence[str],
    threshold: float = 0.85,
) -> list[tuple[str, str, float]]:
    """
    Find all pairs in names that are more similar than threshold.

    Returns:
        List of (name_a, name_b, score) tuples, sorted by score desc.
    """
    results: list[tuple[str, str, float]] = []
    names_list = list(names)

    for i in range(len(names_list)):
        for j in range(i + 1, len(names_list)):
            score = similarity(names_list[i].lower(), names_list[j].lower())
            if score >= threshold:
                results.append((names_list[i], names_list[j], score))

    results.sort(key=lambda x: -x[2])
    return results


def deduplicate(
    names: Sequence[str],
    threshold: float = 0.85,
    *,
    keep_first: bool = True,
) -> list[str]:
    """
    Remove near-duplicate names from a list using pairwise similarity.

    Algorithm: greedy — iterate names in order, mark each new name as
    'kept'; skip subsequent names that are too similar to any kept name.

    Args:
        names:      Input list (order is preserved for kept names).
        threshold:  Similarity score above which two names are considered
                    duplicates (default 0.85 = very similar).
        keep_first: If True, keep the first of each duplicate cluster.
                    If False, keep the last (useful when list is scored and
                    sorted with best names last).

    Returns:
        Deduplicated list in original order.

    Examples:
        >>> deduplicate(["nexagen", "nexagin", "dataflow", "datflow"])
        ['nexagen', 'dataflow']
    """
    if not names:
        return []

    kept: list[str] = []

    for candidate in names:
        c_lower = candidate.lower()
        is_dup = any(
            similarity(c_lower, k.lower()) >= threshold
            for k in kept
        )
        if not is_dup:
            kept.append(candidate)

    return kept


def deduplicate_by_distance(
    names: Sequence[str],
    max_distance: int = 2,
) -> list[str]:
    """
    Remove near-duplicate names using raw Levenshtein distance threshold.
    Faster than similarity-based dedup for large candidate pools.
    """
    if not names:
        return []

    kept: list[str] = []
    for candidate in names:
        c_lower = candidate.lower()
        is_dup = any(
            levenshtein(c_lower, k.lower()) <= max_distance
            for k in kept
        )
        if not is_dup:
            kept.append(candidate)

    return kept


# ─────────────────────────────────────────────────────────────────────────────
# § 7  TRADEMARK / BRAND COLLISION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class TrademarkHit(NamedTuple):
    """Result of a trademark risk check."""
    matched_brand: str
    distance:      int
    risk_level:    str   # 'high' | 'medium' | 'low' | 'none'
    similarity:    float

    def __repr__(self) -> str:
        return (
            f"TrademarkHit(brand={self.matched_brand!r}, "
            f"dist={self.distance}, risk={self.risk_level}, "
            f"sim={self.similarity:.3f})"
        )


def trademark_risk(
    name: str,
    blacklist: Sequence[str],
    *,
    high_threshold:   int = 1,
    medium_threshold: int = 2,
    low_threshold:    int = 3,
) -> TrademarkHit:
    """
    Check a name against a blacklist and return a TrademarkHit.

    Risk classification by Levenshtein distance:
      distance == 0          → HIGH (exact match)
      distance <= high_th    → HIGH
      distance <= medium_th  → MEDIUM
      distance <= low_th     → LOW
      distance  > low_th     → NONE (no hit)

    Also checks if the name is a substring of any blacklisted brand
    or vice versa (important: "googlemaps" should still flag "google").

    Args:
        name:             The candidate brand name to check.
        blacklist:        Known brands / protected names.
        high_threshold:   Max distance for HIGH risk.
        medium_threshold: Max distance for MEDIUM risk.
        low_threshold:    Max distance for LOW risk.

    Returns:
        TrademarkHit with the closest match and risk level.
    """
    name_lower = name.lower()
    closest_brand = ""
    closest_dist  = sys.maxsize
    closest_sim   = 0.0

    for brand in blacklist:
        b = brand.lower()

        # Exact match or substring
        if name_lower == b:
            return TrademarkHit(brand, 0, "high", 1.0)
        if name_lower in b or b in name_lower:
            dist = abs(len(name_lower) - len(b))
            if dist < closest_dist:
                closest_dist  = dist
                closest_brand = brand
                closest_sim   = similarity(name_lower, b)
            continue

        dist = levenshtein(name_lower, b)
        if dist < closest_dist:
            closest_dist  = dist
            closest_brand = brand
            closest_sim   = similarity(name_lower, b)

    if closest_dist > low_threshold:
        return TrademarkHit("", sys.maxsize, "none", 0.0)

    if closest_dist <= high_threshold:
        risk = "high"
    elif closest_dist <= medium_threshold:
        risk = "medium"
    else:
        risk = "low"

    return TrademarkHit(closest_brand, closest_dist, risk, closest_sim)


def has_trademark_conflict(
    name: str,
    blacklist: Sequence[str],
    max_distance: int = 3,
) -> bool:
    """
    Quick boolean check: True if name is within max_distance of any
    blacklisted brand.
    """
    hit = trademark_risk(name, blacklist, low_threshold=max_distance)
    return hit.risk_level != "none"


# ─────────────────────────────────────────────────────────────────────────────
# § 8  PHONETIC DUPLICATE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def phonetic_duplicates(
    names: Sequence[str],
    encode_fn=None,
) -> list[list[str]]:
    """
    Group names that sound alike using a phonetic encoding function.

    Args:
        names:     List of brand name candidates.
        encode_fn: Callable(str) → str phonetic key.
                   Defaults to the Soundex implementation in text_utils.

    Returns:
        List of groups, where each group contains names that sound alike.
        Groups with only one member are excluded.
    """
    if encode_fn is None:
        # Local import to avoid circular dependency
        from .text_utils import soundex as _soundex
        encode_fn = _soundex

    groups: dict[str, list[str]] = {}
    for name in names:
        key = encode_fn(name)
        groups.setdefault(key, []).append(name)

    return [g for g in groups.values() if len(g) > 1]


# ─────────────────────────────────────────────────────────────────────────────
# § 9  UTILITY / DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────

def distance_matrix(names: Sequence[str]) -> list[list[int]]:
    """
    Compute the full n×n Levenshtein distance matrix for a list of names.

    Returns:
        2D list where matrix[i][j] is the distance between names[i] and names[j].
        Symmetric, zeros on the diagonal.
    """
    n = len(names)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = levenshtein(names[i].lower(), names[j].lower())
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix


def backend_info() -> dict[str, str]:
    """Return info about the active distance computation backend."""
    if _USE_RAPIDFUZZ:
        try:
            import rapidfuzz  # type: ignore[import]
            ver = getattr(rapidfuzz, "__version__", "unknown")
        except Exception:
            ver = "unknown"
        return {"backend": "rapidfuzz", "version": ver, "accelerated": "true"}
    return {
        "backend":     "pure-python",
        "version":     "built-in",
        "accelerated": "false",
        "tip":         "pip install rapidfuzz for 10-50× faster distance computation",
    }
