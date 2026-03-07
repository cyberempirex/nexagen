"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  domains/domain_ranker.py  ·  Domain scoring, ranking, and recommendation  ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Turns a flat list of DomainEntry objects into a ranked, scored, and filtered
recommendation set.  Separate from domain_checker.py so ranking logic can be
tested and tuned without any network I/O.

Scoring model (composite 0–100)
────────────────────────────────
  TLD quality       40%   TLD_SCORES normalised 0–100
  Availability      35%   free=100, unknown=40, taken=0
  Name fitness      15%   length, no numeric, pure alpha label
  Variant bonus     10%   exact bare name (no prefix/suffix) gets bonus

Public API
──────────
  score_domain(entry, brand_name)         → int  (0–100)
  rank_domains(entries, brand_name)       → list[RankedDomain]
  filter_free(entries)                    → list[DomainEntry]
  filter_by_tld(entries, tlds)            → list[DomainEntry]
  top_recommendations(entries, brand, n)  → list[RankedDomain]
  group_by_status(entries)                → DomainGroups
  domain_summary(entries, brand_name)     → DomainSummary

Data structures
───────────────
  RankedDomain   — DomainEntry extended with composite score + rank
  DomainGroups   — entries split by status (free/taken/unknown)
  DomainSummary  — aggregated stats for a batch of entries
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from ..config.constants import (
    SCORE_DECENT,
    SCORE_STRONG,
    TLD_SCORES,
    AvailStatus,
)
from ..ui.tables import DomainEntry

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RankedDomain:
    """
    A DomainEntry enriched with a composite quality score and rank.

    Attributes:
        domain:     Full domain string, e.g. "nexagen.io".
        status:     "free" | "taken" | "unknown".
        tld:        Top-level domain component.
        tld_rank:   Raw TLD score from TLD_SCORES (0–100).
        score:      Composite domain quality score (0–100).
        rank:       Position in sorted recommendation list (1-based).
        is_exact:   True if this is the bare name + TLD (no prefix/suffix).
        label:      The SLD (second-level domain) without the TLD.
        note:       Short human-readable reason string.
    """
    domain:   str
    status:   str
    tld:      str
    tld_rank: int  = 0
    score:    int  = 0
    rank:     int  = 0
    is_exact: bool = False
    label:    str  = ""
    note:     str  = ""

    @classmethod
    def from_entry(cls, entry: DomainEntry, *, score: int = 0, rank: int = 0,
                   is_exact: bool = False, note: str = "") -> "RankedDomain":
        label = entry.domain.split(".")[0] if "." in entry.domain else entry.domain
        return cls(
            domain=entry.domain,
            status=entry.status,
            tld=entry.tld,
            tld_rank=entry.tld_rank,
            score=score,
            rank=rank,
            is_exact=is_exact,
            label=label,
            note=note,
        )

    @property
    def is_free(self) -> bool:
        return self.status == AvailStatus.FREE.value

    @property
    def is_taken(self) -> bool:
        return self.status == AvailStatus.TAKEN.value

    def to_entry(self) -> DomainEntry:
        """Convert back to a plain DomainEntry (drops ranking metadata)."""
        return DomainEntry(
            domain=self.domain,
            status=self.status,
            tld=self.tld,
            tld_rank=self.tld_rank,
        )


@dataclass
class DomainGroups:
    """
    Entries split into three availability buckets.
    All three lists are sorted by composite TLD score descending.
    """
    free:    list[DomainEntry] = field(default_factory=list)
    taken:   list[DomainEntry] = field(default_factory=list)
    unknown: list[DomainEntry] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.free) + len(self.taken) + len(self.unknown)

    @property
    def free_count(self) -> int:
        return len(self.free)


@dataclass
class DomainSummary:
    """High-level statistics for a batch of domain check results."""
    brand_name:    str
    total:         int
    free:          int
    taken:         int
    unknown:       int
    best_domain:   str          # highest-scored free domain, or ""
    best_score:    int          # score of best domain
    free_tlds:     list[str]    # TLDs where brand is available
    tld_coverage:  dict[str, str]  # tld → status
    has_dotcom:    bool
    has_dotio:     bool
    has_dotai:     bool

    @property
    def availability_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.free / self.total


# ─────────────────────────────────────────────────────────────────────────────
# § 2  SCORING
# ─────────────────────────────────────────────────────────────────────────────

# Normalised TLD ceiling for scoring
_TLD_MAX = max(TLD_SCORES.values()) if TLD_SCORES else 100

# Status availability weights
_STATUS_WEIGHT = {
    AvailStatus.FREE.value:    100,
    AvailStatus.UNKNOWN.value: 40,
    AvailStatus.TAKEN.value:   0,
    AvailStatus.SKIP.value:    0,
}

# Dimension weights (must sum to 1.0)
_W_TLD    = 0.40
_W_AVAIL  = 0.35
_W_NAME   = 0.15
_W_EXACT  = 0.10


def _score_tld(tld: str) -> int:
    """Normalised TLD quality score 0–100."""
    raw = TLD_SCORES.get(tld, 10)
    return round(raw / _TLD_MAX * 100)


def _score_name_fitness(label: str) -> int:
    """
    Score how clean the domain label (SLD) is as a brand name.

    Checks:
      - Length (4–12 chars ideal)
      - All alphabetic (no hyphens, digits)
      - Not empty
    """
    if not label or not label.isalpha():
        return 30
    n = len(label)
    if n < 3:
        return 20
    if 4 <= n <= 12:
        base = 100
    elif n <= 15:
        base = max(40, 100 - (n - 12) * 12)
    else:
        base = 20
    return base


def _is_exact(domain: str, brand: str) -> bool:
    """Return True if this is the brand + TLD with no prefix/suffix."""
    label = domain.split(".")[0] if "." in domain else domain
    return label.lower() == brand.lower()


def score_domain(entry: DomainEntry, brand_name: str = "") -> int:
    """
    Compute a composite quality score for a single domain entry.

    Args:
        entry:      The DomainEntry to score.
        brand_name: The target brand name — used to identify exact matches.

    Returns:
        Composite score 0–100.
    """
    label   = entry.domain.split(".")[0] if "." in entry.domain else entry.domain
    tld_s   = _score_tld(entry.tld)
    avail_s = _STATUS_WEIGHT.get(entry.status, 0)
    name_s  = _score_name_fitness(label)
    exact_s = 100 if (brand_name and _is_exact(entry.domain, brand_name)) else 0

    composite = (
        tld_s   * _W_TLD  +
        avail_s * _W_AVAIL +
        name_s  * _W_NAME  +
        exact_s * _W_EXACT
    )
    return max(0, min(100, round(composite)))


def _note_for(entry: DomainEntry, score: int, is_exact: bool) -> str:
    """Generate a short human-readable note for a ranked domain."""
    parts: list[str] = []
    if entry.status == AvailStatus.FREE.value:
        if is_exact:
            parts.append("Exact name available")
        if entry.tld in ("com", "io", "ai", "co", "dev"):
            parts.append(f"Premium TLD (.{entry.tld})")
    elif entry.status == AvailStatus.TAKEN.value:
        parts.append("Registered")
    else:
        parts.append("Check manually")
    if score >= SCORE_STRONG:
        parts.append("Recommended")
    return " · ".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────────────────────
# § 3  RANKING
# ─────────────────────────────────────────────────────────────────────────────

def rank_domains(
    entries:    Sequence[DomainEntry],
    brand_name: str = "",
) -> list[RankedDomain]:
    """
    Score and rank all domain entries by composite quality.

    Entries with the same score are secondarily sorted by TLD rank
    descending, then alphabetically by domain for stability.

    Args:
        entries:    Domain entries (any status mix).
        brand_name: Brand name for exact-match detection.

    Returns:
        List of RankedDomain objects sorted best-first with 1-based ranks.
    """
    scored: list[tuple[int, DomainEntry, bool]] = []

    for entry in entries:
        exact = _is_exact(entry.domain, brand_name) if brand_name else False
        s     = score_domain(entry, brand_name)
        scored.append((s, entry, exact))

    # Sort: composite score DESC, TLD rank DESC, domain ASC
    scored.sort(key=lambda t: (-t[0], -t[1].tld_rank, t[1].domain))

    ranked: list[RankedDomain] = []
    for position, (score, entry, exact) in enumerate(scored, 1):
        note = _note_for(entry, score, exact)
        ranked.append(RankedDomain.from_entry(
            entry,
            score=score,
            rank=position,
            is_exact=exact,
            note=note,
        ))

    return ranked


# ─────────────────────────────────────────────────────────────────────────────
# § 4  FILTERING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def filter_free(entries: Sequence[DomainEntry]) -> list[DomainEntry]:
    """Return only entries with status == "free", sorted by TLD rank desc."""
    return sorted(
        (e for e in entries if e.status == AvailStatus.FREE.value),
        key=lambda e: -e.tld_rank,
    )


def filter_by_status(
    entries: Sequence[DomainEntry],
    status:  str,
) -> list[DomainEntry]:
    """Return entries matching a given status string."""
    return [e for e in entries if e.status == status]


def filter_by_tld(
    entries: Sequence[DomainEntry],
    tlds:    Sequence[str],
) -> list[DomainEntry]:
    """
    Return entries whose TLD is in the allowed list.

    Args:
        entries: Domain entries to filter.
        tlds:    TLD strings without leading dot, e.g. ["com", "io", "ai"].

    Returns:
        Filtered list preserving original order.
    """
    tld_set = {t.lstrip(".").lower() for t in tlds}
    return [e for e in entries if e.tld.lower() in tld_set]


def filter_exact(
    entries:    Sequence[DomainEntry],
    brand_name: str,
) -> list[DomainEntry]:
    """Return only entries where the SLD exactly matches brand_name."""
    return [e for e in entries if _is_exact(e.domain, brand_name)]


# ─────────────────────────────────────────────────────────────────────────────
# § 5  TOP RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────────────────

def top_recommendations(
    entries:    Sequence[DomainEntry],
    brand_name: str = "",
    n:          int = 5,
    *,
    free_only:  bool = False,
) -> list[RankedDomain]:
    """
    Return the top-N ranked domain recommendations.

    Args:
        entries:    All domain entries (any mix of status).
        brand_name: Brand name for exact-match weighting.
        n:          Maximum number of results.
        free_only:  If True, restrict to FREE domains only.

    Returns:
        Top-N RankedDomain objects, best first.
    """
    pool = [e for e in entries if e.status == AvailStatus.FREE.value] \
        if free_only else list(entries)

    ranked = rank_domains(pool, brand_name)
    return ranked[:n]


def best_domain(
    entries:    Sequence[DomainEntry],
    brand_name: str = "",
) -> Optional[RankedDomain]:
    """
    Return the single best available domain, or None.

    Prefers exact name + premium TLD, then any free domain.
    """
    from typing import Optional  # local to avoid circular at module level
    ranked = top_recommendations(entries, brand_name, n=1, free_only=True)
    return ranked[0] if ranked else None


# ─────────────────────────────────────────────────────────────────────────────
# § 6  GROUPING AND SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def group_by_status(entries: Sequence[DomainEntry]) -> DomainGroups:
    """
    Split entries into free / taken / unknown buckets.

    Each bucket is sorted by TLD rank descending.

    Args:
        entries: Domain entries to group.

    Returns:
        DomainGroups with three sorted lists.
    """
    by_status: dict[str, list[DomainEntry]] = {
        AvailStatus.FREE.value:    [],
        AvailStatus.TAKEN.value:   [],
        AvailStatus.UNKNOWN.value: [],
    }

    for entry in entries:
        bucket = by_status.get(entry.status, by_status[AvailStatus.UNKNOWN.value])
        bucket.append(entry)

    def _sort(lst: list[DomainEntry]) -> list[DomainEntry]:
        return sorted(lst, key=lambda e: -e.tld_rank)

    return DomainGroups(
        free    = _sort(by_status[AvailStatus.FREE.value]),
        taken   = _sort(by_status[AvailStatus.TAKEN.value]),
        unknown = _sort(by_status[AvailStatus.UNKNOWN.value]),
    )


def domain_summary(
    entries:    Sequence[DomainEntry],
    brand_name: str = "",
) -> DomainSummary:
    """
    Compute aggregated statistics for a batch of domain check results.

    Args:
        entries:    Checked domain entries.
        brand_name: Brand name for summary context.

    Returns:
        DomainSummary with counts, best domain, TLD coverage map.
    """
    groups  = group_by_status(entries)
    ranked  = rank_domains(list(filter_free(entries)), brand_name)

    best     = ranked[0] if ranked else None
    coverage = {e.tld: e.status for e in entries}

    free_tlds = sorted(
        {e.tld for e in entries if e.status == AvailStatus.FREE.value},
        key=lambda t: -TLD_SCORES.get(t, 0),
    )

    return DomainSummary(
        brand_name   = brand_name,
        total        = len(entries),
        free         = len(groups.free),
        taken        = len(groups.taken),
        unknown      = len(groups.unknown),
        best_domain  = best.domain if best else "",
        best_score   = best.score  if best else 0,
        free_tlds    = free_tlds,
        tld_coverage = coverage,
        has_dotcom   = coverage.get("com") == AvailStatus.FREE.value,
        has_dotio    = coverage.get("io")  == AvailStatus.FREE.value,
        has_dotai    = coverage.get("ai")  == AvailStatus.FREE.value,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 7  DOMAIN VARIANT GENERATOR  (used by ranker for input)
# ─────────────────────────────────────────────────────────────────────────────

def generate_domain_variants(
    brand_name:     str,
    prefixes:       Sequence[str] = (),
    suffixes:       Sequence[str] = (),
    tlds:           Sequence[str] = (),
    *,
    include_prefix: bool = True,
    include_suffix: bool = True,
    max_variants:   int  = 50,
) -> list[str]:
    """
    Generate domain name variants for a given brand name.

    Produces:
      1. Exact: brand + each TLD
      2. Prefix variants: prefix + brand + top TLDs
      3. Suffix variants: brand + suffix + top TLDs

    Args:
        brand_name:     Lowercase brand name.
        prefixes:       Word prefixes to try (e.g. "get", "use").
        suffixes:       Word suffixes to try (e.g. "hub", "lab").
        tlds:           TLD list ordered by preference.
        include_prefix: Enable prefix variants.
        include_suffix: Enable suffix variants.
        max_variants:   Maximum number of domain strings to return.

    Returns:
        Deduplicated list of domain strings.
    """
    if not tlds:
        tlds = list(TLD_SCORES.keys())[:20]

    seen:   set[str]  = set()
    result: list[str] = []

    def _add(domain: str) -> None:
        d = domain.lower()
        if d not in seen:
            seen.add(d)
            result.append(d)

    # 1. Exact name + all TLDs
    for tld in tlds:
        _add(f"{brand_name}.{tld}")
        if len(result) >= max_variants:
            return result

    # 2. Prefix variants
    if include_prefix:
        top_tlds = list(tlds)[:5]
        for pre in list(prefixes)[:10]:
            for tld in top_tlds:
                _add(f"{pre}{brand_name}.{tld}")
                if len(result) >= max_variants:
                    return result

    # 3. Suffix variants
    if include_suffix:
        top_tlds = list(tlds)[:3]
        for suf in list(suffixes)[:10]:
            for tld in top_tlds:
                _add(f"{brand_name}{suf}.{tld}")
                if len(result) >= max_variants:
                    return result

    return result
