"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  domains/domain_generator.py  ·  Full domain variant generation engine     ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Full domain variant generation engine.

domain_ranker.py contains a stateless helper ``generate_domain_variants()``
that produces a flat list of domain strings from a name + TLD list.  This
module is the complete, Settings-aware, profile-aware generation layer that
orchestrates that helper with richer controls:

  • Profile-aware TLD prioritisation (tech/AI names prefer .io .ai .dev)
  • Configurable prefix / suffix variant depth
  • Heuristic label-quality gate (no ugly domains pass through)
  • Deduplication with order preservation
  • Optional integration with :mod:`tld_strategy` for TLD plan selection
  • Returns rich :class:`DomainPlan` objects, not bare strings

Generation pipeline
────────────────────
  1. Resolve TLD list via tld_strategy.recommend_tlds(profile, cfg)
  2. Expand prefix variants (get-, use-, try-, … + brand)
  3. Expand suffix variants (brand + -hub, -lab, -io, …)
  4. Compute label quality for each candidate
  5. Deduplicate, cap at max_domains
  6. Return DomainPlan list sorted by priority

Public API
──────────
  DomainGenerator.generate(name, cfg)        → list[DomainPlan]
  DomainGenerator.generate_exact(name, cfg)  → list[DomainPlan]
  generate_domains(name, cfg)                → list[DomainPlan]
  to_domain_entries(plans, status)           → list[DomainEntry]

Data structures
───────────────
  DomainPlan      — a domain string with priority, variant type, label quality
  VariantType     — EXACT | PREFIX | SUFFIX | COMPOUND
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from ..config.constants import (
    TLD_SCORES,
    AvailStatus,
)
from ..config.settings import Settings, get_settings
from ..ui.tables import DomainEntry
from ..utils.dataset_loader import prefixes as _load_prefixes
from ..utils.dataset_loader import suffixes as _load_suffixes
from ..utils.dataset_loader import tlds as _load_tlds
from ..utils.text_utils import is_pronounceable, vowel_ratio

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Maximum prefix / suffix variants when use_prefixes / use_suffixes enabled
_MAX_PREFIXES = 10
_MAX_SUFFIXES = 8

# Maximum domains returned by generate() — hard cap before cfg.max override
_DEFAULT_MAX_DOMAINS = 40

# Minimum label quality score to include a domain in results
_MIN_LABEL_QUALITY = 35

# Profile → extra TLDs that get priority-bumped for that profile
_PROFILE_TLD_BOOSTS: dict[str, list[str]] = {
    "tech":      ["io", "dev", "tech", "build", "cloud"],
    "ai":        ["ai", "io", "dev", "ml", "build"],
    "security":  ["io", "dev", "systems", "network"],
    "finance":   ["co", "finance", "io", "com"],
    "health":    ["health", "co", "io", "com"],
    "social":    ["co", "io", "app", "social"],
    "education": ["co", "io", "org", "edu"],
    "document":  ["io", "app", "tools", "co"],
    "generic":   ["com", "io", "co", "ai", "dev"],
}

# Prefixes that pair well with tech/AI brand names
_TECH_PREFIXES = ["get", "try", "use", "go", "open", "run", "my", "pro"]
_SOFT_PREFIXES = ["my", "the", "get", "meet", "hello", "hey"]

# Profile → preferred prefix flavours
_PROFILE_PREFIXES: dict[str, list[str]] = {
    "tech":      _TECH_PREFIXES,
    "ai":        ["get", "try", "open", "go", "run", "use"],
    "security":  ["get", "open", "pro", "secure"],
    "finance":   ["get", "my", "use", "try"],
    "health":    _SOFT_PREFIXES,
    "social":    _SOFT_PREFIXES,
    "education": _SOFT_PREFIXES,
    "document":  _TECH_PREFIXES,
    "generic":   _TECH_PREFIXES,
}

# Domain label quality: penalise long, hyphenated, digit-containing labels
_LABEL_RE = re.compile(r"^[a-z][a-z0-9]{2,}$")


# ─────────────────────────────────────────────────────────────────────────────
# § 2  ENUMERATIONS & DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

class VariantType(str, Enum):
    """How this domain variant was constructed."""
    EXACT    = "exact"     # bare brand name + TLD
    PREFIX   = "prefix"    # word prefix + brand + TLD
    SUFFIX   = "suffix"    # brand + word suffix + TLD
    COMPOUND = "compound"  # brand + short modifier word + TLD


@dataclass
class DomainPlan:
    """
    A single domain candidate generated for a brand name.

    Attributes:
        domain:         Full domain string, e.g. ``"nexagen.io"``.
        brand:          The brand name this was derived from.
        tld:            Top-level domain component.
        label:          Second-level domain (SLD) without TLD.
        variant_type:   How this domain was constructed.
        tld_score:      Raw TLD score from TLD_SCORES (0–100).
        label_quality:  Heuristic label quality 0–100 (higher = cleaner label).
        priority:       Combined priority for sorting (higher = recommended first).
        prefix_word:    The prefix word used (empty if not a PREFIX variant).
        suffix_word:    The suffix word used (empty if not a SUFFIX variant).
        is_exact:       True if this is the bare name + TLD (no prefix/suffix).
    """
    domain:       str
    brand:        str
    tld:          str
    label:        str
    variant_type: VariantType
    tld_score:    int  = 0
    label_quality:int  = 0
    priority:     int  = 0
    prefix_word:  str  = ""
    suffix_word:  str  = ""
    is_exact:     bool = False

    def to_domain_entry(self, status: str = AvailStatus.UNKNOWN.value) -> DomainEntry:
        """Convert to a :class:`~nexagen.ui.tables.DomainEntry`."""
        return DomainEntry(
            domain   = self.domain,
            status   = status,
            tld      = self.tld,
            tld_rank = self.tld_score,
        )

    def __str__(self) -> str:
        tag = f"[{self.variant_type.value}]"
        return f"{self.domain:<28} {tag:<12} priority={self.priority}"


# ─────────────────────────────────────────────────────────────────────────────
# § 3  LABEL QUALITY SCORER
# ─────────────────────────────────────────────────────────────────────────────

def _label_quality(label: str) -> int:
    """
    Heuristic quality score for a domain SLD (0–100).

    Factors:
      • All lowercase alpha           → +30
      • Length 4–12 chars             → +30 (ideal), -N per char outside range
      • Pronounceable                 → +20
      • Vowel ratio in 0.20–0.60     → +10
      • No digits                     → +10
    """
    score = 0
    n     = len(label)

    # All lowercase alpha (no digits, no hyphens)
    if label.isalpha() and label == label.lower():
        score += 30
    elif _LABEL_RE.match(label):
        score += 18  # has digits but otherwise OK

    # Length
    if 4 <= n <= 12:
        score += 30
    elif n < 4:
        score += max(0, 30 - (4 - n) * 8)
    else:
        score += max(0, 30 - (n - 12) * 5)

    # Pronounceability
    if label.isalpha() and is_pronounceable(label):
        score += 20

    # Vowel ratio
    vr = vowel_ratio(label)
    if 0.20 <= vr <= 0.60:
        score += 10

    # No digits
    if not any(c.isdigit() for c in label):
        score += 10

    return min(100, max(0, score))


# ─────────────────────────────────────────────────────────────────────────────
# § 4  DOMAIN PLAN FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def _make_plan(
    label:        str,
    tld:          str,
    brand:        str,
    variant_type: VariantType,
    prefix_word:  str = "",
    suffix_word:  str = "",
) -> Optional[DomainPlan]:
    """
    Build a :class:`DomainPlan` for ``label.tld``.

    Returns None if the label fails the minimum quality gate.
    """
    label  = label.lower().strip()
    tld    = tld.lower().strip().lstrip(".")

    if not label or not tld:
        return None

    # Reject obviously broken labels
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$|^[a-z0-9]{1,2}$", label):
        return None

    lq    = _label_quality(label)
    if lq < _MIN_LABEL_QUALITY:
        return None

    ts    = TLD_SCORES.get(tld, 10)
    is_ex = (label == brand.lower())

    # Priority = tld_score × 0.5 + label_quality × 0.3 + exact bonus × 0.2
    priority = round(ts * 0.5 + lq * 0.3 + (100 if is_ex else 0) * 0.2)

    return DomainPlan(
        domain       = f"{label}.{tld}",
        brand        = brand.lower(),
        tld          = tld,
        label        = label,
        variant_type = variant_type,
        tld_score    = ts,
        label_quality= lq,
        priority     = priority,
        prefix_word  = prefix_word,
        suffix_word  = suffix_word,
        is_exact     = is_ex,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 5  DOMAIN GENERATOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class DomainGenerator:
    """
    Settings-aware, profile-aware domain variant generation engine.

    Usage::

        from nexagen.domains.domain_generator import DomainGenerator
        gen     = DomainGenerator()
        plans   = gen.generate("paperdesk", cfg=settings)
        entries = [p.to_domain_entry() for p in plans]
        # entries: list[DomainEntry] → pass to batch_check_domains()

    The generator is stateless — safe to reuse across multiple calls.
    """

    # ── Public entry points ───────────────────────────────────────────────────

    def generate(
        self,
        name:        str,
        cfg:         Optional[Settings] = None,
        *,
        max_domains: int = _DEFAULT_MAX_DOMAINS,
    ) -> list[DomainPlan]:
        """
        Generate a prioritised list of domain candidates for a brand name.

        Respects ``cfg.use_prefixes``, ``cfg.use_suffixes``,
        ``cfg.preferred_tlds``, and ``cfg.profile``.

        Args:
            name:        Brand name (will be lowercased).
            cfg:         Active Settings (loaded from disk if None).
            max_domains: Maximum plans to return (default 40).

        Returns:
            List of :class:`DomainPlan` sorted by priority descending.
        """
        if cfg is None:
            cfg = get_settings()

        brand = name.lower().strip()
        if not brand:
            return []

        # Resolve TLDs
        tld_list = self._resolve_tlds(cfg)

        # Load prefix / suffix datasets
        all_prefixes  = _load_prefixes()
        all_suffixes  = _load_suffixes()
        profile_prefs = _PROFILE_PREFIXES.get(cfg.profile, _TECH_PREFIXES)

        # Sort prefixes: profile-preferred come first
        ordered_prefixes = (
            [p for p in profile_prefs if p in all_prefixes]
            + [p for p in all_prefixes if p not in profile_prefs]
        )[:_MAX_PREFIXES]

        ordered_suffixes = all_suffixes[:_MAX_SUFFIXES]

        seen:   set[str]       = set()
        plans:  list[DomainPlan] = []

        def _add(plan: Optional[DomainPlan]) -> bool:
            if plan and plan.domain not in seen:
                seen.add(plan.domain)
                plans.append(plan)
                return True
            return False

        # ── 1. Exact: brand + each TLD ────────────────────────────────────────
        for tld in tld_list:
            _add(_make_plan(brand, tld, brand, VariantType.EXACT))
            if len(plans) >= max_domains:
                break

        # ── 2. Prefix variants ────────────────────────────────────────────────
        if cfg.use_prefixes and len(plans) < max_domains:
            top_tlds = tld_list[:5]
            for pre in ordered_prefixes:
                label = f"{pre}{brand}"
                for tld in top_tlds:
                    _add(_make_plan(label, tld, brand, VariantType.PREFIX,
                                    prefix_word=pre))
                if len(plans) >= max_domains:
                    break

        # ── 3. Suffix variants ────────────────────────────────────────────────
        if cfg.use_suffixes and len(plans) < max_domains:
            top_tlds = tld_list[:3]
            for suf in ordered_suffixes:
                label = f"{brand}{suf}"
                for tld in top_tlds:
                    _add(_make_plan(label, tld, brand, VariantType.SUFFIX,
                                    suffix_word=suf))
                if len(plans) >= max_domains:
                    break

        # ── Sort by priority (exact / high-TLD first) ─────────────────────────
        plans.sort(key=lambda p: (-p.priority, -p.tld_score, p.label))
        return plans[:max_domains]

    def generate_exact(
        self,
        name:        str,
        cfg:         Optional[Settings] = None,
        *,
        max_domains: int = 20,
    ) -> list[DomainPlan]:
        """
        Generate only EXACT variants (brand + TLD, no prefix/suffix).

        Useful when you want to check the brand name itself across many TLDs
        without the noisier prefix/suffix candidates.

        Args:
            name:        Brand name.
            cfg:         Active Settings.
            max_domains: Maximum plans to return.

        Returns:
            List of :class:`DomainPlan` (EXACT type only).
        """
        if cfg is None:
            cfg = get_settings()

        brand    = name.lower().strip()
        tld_list = self._resolve_tlds(cfg)
        plans: list[DomainPlan] = []
        seen:  set[str]         = set()

        for tld in tld_list:
            plan = _make_plan(brand, tld, brand, VariantType.EXACT)
            if plan and plan.domain not in seen:
                seen.add(plan.domain)
                plans.append(plan)
            if len(plans) >= max_domains:
                break

        plans.sort(key=lambda p: (-p.priority, -p.tld_score))
        return plans

    # ── TLD resolution ────────────────────────────────────────────────────────

    def _resolve_tlds(self, cfg: Settings) -> list[str]:
        """
        Build a deduplicated, priority-ordered TLD list for this config.

        Order:
          1. cfg.preferred_tlds (user-configured)
          2. Profile-boosted TLDs for cfg.profile
          3. Remaining TLDs from the dataset (tlds.txt)
          4. Any extra TLDs from TLD_SCORES not yet included
        """
        profile_boosts = _PROFILE_TLD_BOOSTS.get(cfg.profile, [])
        dataset_tlds   = _load_tlds()
        scores_tlds    = list(TLD_SCORES.keys())

        ordered: list[str] = []
        seen:    set[str]  = set()

        def _push(t: str) -> None:
            t = t.lower().strip().lstrip(".")
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)

        for t in cfg.preferred_tlds:
            _push(t)
        for t in profile_boosts:
            _push(t)
        for t in dataset_tlds:
            _push(t)
        for t in scores_tlds:
            _push(t)

        return ordered

    # ── Conversion helpers ────────────────────────────────────────────────────

    def to_strings(self, plans: Sequence[DomainPlan]) -> list[str]:
        """Extract plain domain strings from a list of DomainPlans."""
        return [p.domain for p in plans]

    def to_domain_entries(
        self,
        plans:  Sequence[DomainPlan],
        status: str = AvailStatus.UNKNOWN.value,
    ) -> list[DomainEntry]:
        """Convert plans to :class:`~nexagen.ui.tables.DomainEntry` objects."""
        return [p.to_domain_entry(status) for p in plans]


# ─────────────────────────────────────────────────────────────────────────────
# § 6  FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def generate_domains(
    name:        str,
    cfg:         Optional[Settings] = None,
    *,
    max_domains: int = _DEFAULT_MAX_DOMAINS,
) -> list[DomainPlan]:
    """
    Generate domain candidates for a brand name.

    Functional wrapper around :meth:`DomainGenerator.generate`.

    Args:
        name:        Brand name.
        cfg:         Active Settings (loaded if None).
        max_domains: Maximum plans to return.

    Returns:
        List of :class:`DomainPlan` sorted by priority.
    """
    return DomainGenerator().generate(name, cfg, max_domains=max_domains)


def generate_exact_domains(
    name:        str,
    cfg:         Optional[Settings] = None,
    *,
    max_domains: int = 20,
) -> list[DomainPlan]:
    """
    Generate exact-match domain candidates only (no prefix/suffix variants).

    Args:
        name:        Brand name.
        cfg:         Active Settings (loaded if None).
        max_domains: Maximum plans.

    Returns:
        List of :class:`DomainPlan` (EXACT type only).
    """
    return DomainGenerator().generate_exact(name, cfg, max_domains=max_domains)


def to_domain_entries(
    plans:  Sequence[DomainPlan],
    status: str = AvailStatus.UNKNOWN.value,
) -> list[DomainEntry]:
    """
    Convert :class:`DomainPlan` objects to :class:`~nexagen.ui.tables.DomainEntry`.

    Args:
        plans:  Domain plans from :func:`generate_domains`.
        status: Status to assign (default ``"unknown"`` — not yet checked).

    Returns:
        List of :class:`DomainEntry`.
    """
    return [p.to_domain_entry(status) for p in plans]


def domain_strings(
    name:        str,
    cfg:         Optional[Settings] = None,
    *,
    max_domains: int = _DEFAULT_MAX_DOMAINS,
) -> list[str]:
    """
    Return a flat list of domain strings for *name*, suitable for passing
    directly to :func:`~nexagen.domains.domain_checker.batch_check_domains`.

    Args:
        name:        Brand name.
        cfg:         Active Settings.
        max_domains: Maximum domains.

    Returns:
        List of domain strings, e.g. ``["nexagen.com", "nexagen.io", ...]``.
    """
    return [p.domain for p in generate_domains(name, cfg, max_domains=max_domains)]
