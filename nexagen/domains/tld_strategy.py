"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  domains/tld_strategy.py  ·  TLD selection strategy & recommendation       ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

TLD selection strategy and recommendation engine.

Answers the question: *given a brand profile and availability results, which
TLD should this company register first — and what's the strategic rationale?*

Responsibilities
────────────────
  • TLD tier classification (Premium / Strong / Standard / Niche)
  • Profile-aware TLD recommendation with rationale strings
  • Availability-aware re-ranking (free tier-1 > taken tier-1)
  • Budget strategies (must-have, nice-to-have, optional)
  • TLD intelligence: recognition, trust, SEO, tech perception scores
  • Portfolio planning: recommend a minimum viable TLD set

TLD tiers
─────────
  PREMIUM   — .com .io .ai         (universal recognition, highest trust)
  STRONG    — .co .dev .app .tech  (widely recognised, tech-positive)
  STANDARD  — .cloud .build .tools .run .labs .hub .studio
  NICHE     — .network .systems .digital .xyz .me .gg .so + long-tail

Public API
──────────
  TLDStrategy.recommend(profile, cfg, available_tlds) → TLDRecommendation
  TLDStrategy.tier(tld)                               → TLDTier
  TLDStrategy.score(tld, profile)                     → int
  TLDStrategy.portfolio(profile, available_tlds, n)   → list[str]
  recommend_tlds(profile, cfg)                        → list[str]
  tld_tier(tld)                                       → str
  tld_score(tld, profile)                             → int

Data structures
───────────────
  TLDTier            — PREMIUM | STRONG | STANDARD | NICHE
  TLDInfo            — per-TLD intelligence record
  TLDRecommendation  — primary + portfolio + rationale for a profile
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from ..config.constants import TLD_SCORES, AvailStatus
from ..config.settings import Settings, get_settings
from ..ui.tables import DomainEntry
from ..utils.dataset_loader import tlds as _load_tlds

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  TLD TIER ENUM
# ─────────────────────────────────────────────────────────────────────────────

class TLDTier(str, Enum):
    """Quality / recognition tier for a top-level domain."""
    PREMIUM  = "premium"    # .com .io .ai
    STRONG   = "strong"     # .co .dev .app .tech .labs
    STANDARD = "standard"   # .cloud .build .tools .run .hub .studio
    NICHE    = "niche"      # all others

    @property
    def weight(self) -> int:
        return {"premium": 4, "strong": 3, "standard": 2, "niche": 1}[self.value]

    @property
    def label(self) -> str:
        return self.value.capitalize()


# ─────────────────────────────────────────────────────────────────────────────
# § 2  TLD INTELLIGENCE TABLE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TLDInfo:
    """
    Intelligence record for a single TLD.

    Attributes:
        tld:         TLD string without leading dot, e.g. ``"io"``.
        tier:        Quality tier.
        base_score:  Raw score from TLD_SCORES (0–100).
        recognition: Global consumer recognition (0–100).
        trust:       Perceived trustworthiness (0–100).
        tech_score:  Tech / SaaS perception (0–100).
        seo_friendly:Whether Google treats it on par with gTLDs.
        registrar_cost: Typical annual cost in USD (0 = unknown).
        rationale:   One-line recommendation rationale.
        profiles:    Profiles this TLD is especially well-suited for.
    """
    tld:           str
    tier:          TLDTier
    base_score:    int
    recognition:   int   = 70
    trust:         int   = 70
    tech_score:    int   = 50
    seo_friendly:  bool  = True
    registrar_cost:int   = 0
    rationale:     str   = ""
    profiles:      list[str] = field(default_factory=list)

    @property
    def dotted(self) -> str:
        return f".{self.tld}"

    @property
    def composite(self) -> int:
        """Composite score from all intelligence dimensions."""
        return round(
            self.base_score    * 0.35 +
            self.recognition   * 0.25 +
            self.trust         * 0.20 +
            self.tech_score    * 0.20
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 3  TLD INTELLIGENCE DATABASE
# ─────────────────────────────────────────────────────────────────────────────

_TLD_DB: dict[str, TLDInfo] = {
    # ── PREMIUM ───────────────────────────────────────────────────────────────
    "com": TLDInfo("com", TLDTier.PREMIUM, 100, recognition=100, trust=100,
                   tech_score=80, seo_friendly=True, registrar_cost=12,
                   rationale="The global standard — maximum trust and recognition.",
                   profiles=["generic", "finance", "health", "education"]),

    "io":  TLDInfo("io", TLDTier.PREMIUM, 85, recognition=88, trust=85,
                   tech_score=98, seo_friendly=True, registrar_cost=30,
                   rationale="The de-facto TLD for tech startups and SaaS products.",
                   profiles=["tech", "ai", "security", "document"]),

    "ai":  TLDInfo("ai", TLDTier.PREMIUM, 82, recognition=82, trust=80,
                   tech_score=100, seo_friendly=True, registrar_cost=60,
                   rationale="Signals AI / ML products. Premium positioning.",
                   profiles=["ai", "tech"]),

    # ── STRONG ────────────────────────────────────────────────────────────────
    "co":  TLDInfo("co", TLDTier.STRONG, 78, recognition=80, trust=78,
                   tech_score=65, seo_friendly=True, registrar_cost=25,
                   rationale="Short, professional, widely accepted alternative to .com.",
                   profiles=["generic", "social", "finance"]),

    "dev": TLDInfo("dev", TLDTier.STRONG, 74, recognition=72, trust=78,
                   tech_score=95, seo_friendly=True, registrar_cost=12,
                   rationale="Google-operated .dev — ideal for developer tools.",
                   profiles=["tech", "ai", "document"]),

    "app": TLDInfo("app", TLDTier.STRONG, 70, recognition=72, trust=74,
                   tech_score=88, seo_friendly=True, registrar_cost=18,
                   rationale="Google-operated .app — perfect for mobile/web apps.",
                   profiles=["tech", "social", "document"]),

    "tech":TLDInfo("tech", TLDTier.STRONG, 68, recognition=65, trust=70,
                   tech_score=88, seo_friendly=True, registrar_cost=40,
                   rationale="Communicates technology focus unambiguously.",
                   profiles=["tech", "ai", "security"]),

    "labs":TLDInfo("labs", TLDTier.STRONG, 55, recognition=58, trust=65,
                   tech_score=85, seo_friendly=True, registrar_cost=20,
                   rationale="R&D and experimental product positioning.",
                   profiles=["tech", "ai", "security"]),

    "hub": TLDInfo("hub", TLDTier.STRONG, 50, recognition=55, trust=60,
                   tech_score=70, seo_friendly=True, registrar_cost=20,
                   rationale="Community and platform positioning.",
                   profiles=["social", "education", "document"]),

    # ── STANDARD ─────────────────────────────────────────────────────────────
    "cloud":  TLDInfo("cloud", TLDTier.STANDARD, 65, recognition=62, trust=65,
                      tech_score=80, seo_friendly=True, registrar_cost=22,
                      rationale="Cloud infrastructure and SaaS positioning.",
                      profiles=["tech", "ai"]),

    "build":  TLDInfo("build", TLDTier.STANDARD, 62, recognition=50, trust=58,
                      tech_score=75, seo_friendly=True, registrar_cost=20,
                      rationale="Developer tools, CI/CD, and engineering platforms.",
                      profiles=["tech", "document"]),

    "tools":  TLDInfo("tools", TLDTier.STANDARD, 60, recognition=55, trust=60,
                      tech_score=72, seo_friendly=True, registrar_cost=20,
                      rationale="Productivity tools, utilities, and SaaS tooling.",
                      profiles=["tech", "document", "education"]),

    "run":    TLDInfo("run", TLDTier.STANDARD, 58, recognition=48, trust=55,
                      tech_score=70, seo_friendly=True, registrar_cost=15,
                      rationale="Execution and deployment-oriented products.",
                      profiles=["tech"]),

    "studio": TLDInfo("studio", TLDTier.STANDARD, 48, recognition=52, trust=58,
                      tech_score=60, seo_friendly=True, registrar_cost=20,
                      rationale="Design agencies, creative tools, and indie studios.",
                      profiles=["social", "education"]),

    "net":    TLDInfo("net", TLDTier.STANDARD, 54, recognition=72, trust=68,
                      tech_score=55, seo_friendly=True, registrar_cost=12,
                      rationale="Network and infrastructure positioning.",
                      profiles=["tech", "security"]),

    "org":    TLDInfo("org", TLDTier.STANDARD, 50, recognition=75, trust=72,
                      tech_score=35, seo_friendly=True, registrar_cost=12,
                      rationale="Non-profit, open-source, and community projects.",
                      profiles=["education", "generic"]),

    "systems":TLDInfo("systems", TLDTier.STANDARD, 56, recognition=45, trust=58,
                      tech_score=78, seo_friendly=True, registrar_cost=25,
                      rationale="Infrastructure and systems-level software.",
                      profiles=["security", "tech"]),

    # ── NICHE ─────────────────────────────────────────────────────────────────
    "xyz":    TLDInfo("xyz", TLDTier.NICHE, 20, recognition=40, trust=38,
                      tech_score=45, seo_friendly=True, registrar_cost=1,
                      rationale="Very affordable but lower trust perception.",
                      profiles=["generic"]),

    "me":     TLDInfo("me", TLDTier.NICHE, 30, recognition=52, trust=50,
                      tech_score=42, seo_friendly=True, registrar_cost=20,
                      rationale="Personal brands and founder-led products.",
                      profiles=["social", "generic"]),

    "link":   TLDInfo("link", TLDTier.NICHE, 40, recognition=40, trust=42,
                      tech_score=48, seo_friendly=True, registrar_cost=10,
                      rationale="Link-sharing, URL shorteners, and social tools.",
                      profiles=["social"]),

    "digital":TLDInfo("digital", TLDTier.NICHE, 42, recognition=45, trust=48,
                      tech_score=50, seo_friendly=True, registrar_cost=30,
                      rationale="Digital transformation and marketing agencies.",
                      profiles=["generic", "social"]),

    "online": TLDInfo("online", TLDTier.NICHE, 45, recognition=48, trust=48,
                      tech_score=40, seo_friendly=True, registrar_cost=30,
                      rationale="Online services and e-commerce.",
                      profiles=["generic"]),

    "gg":     TLDInfo("gg", TLDTier.NICHE, 25, recognition=35, trust=35,
                      tech_score=60, seo_friendly=True, registrar_cost=20,
                      rationale="Gaming and esports community TLD.",
                      profiles=["social"]),
}

# Fill any TLD from TLD_SCORES not already in _TLD_DB
for _tld, _score in TLD_SCORES.items():
    if _tld not in _TLD_DB:
        _tier = (
            TLDTier.PREMIUM  if _score >= 80 else
            TLDTier.STRONG   if _score >= 55 else
            TLDTier.STANDARD if _score >= 35 else
            TLDTier.NICHE
        )
        _TLD_DB[_tld] = TLDInfo(
            tld=_tld, tier=_tier, base_score=_score,
            rationale=f"Score {_score}/100 from TLD_SCORES.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 4  PROFILE → TLD RANKING
# ─────────────────────────────────────────────────────────────────────────────

# For each profile: ranked list of TLDs by strategic fit (most → least)
_PROFILE_RANKED: dict[str, list[str]] = {
    "tech":      ["io", "dev", "com", "tech", "app", "ai", "cloud", "build", "tools", "co"],
    "ai":        ["ai", "io", "dev", "com", "tech", "cloud", "co", "app"],
    "security":  ["io", "dev", "com", "systems", "network", "co", "tech"],
    "finance":   ["com", "co", "io", "finance", "net", "tech"],
    "health":    ["com", "health", "co", "io", "org", "net"],
    "social":    ["co", "com", "io", "app", "social", "studio", "gg"],
    "education": ["com", "co", "io", "org", "edu", "app", "tools"],
    "document":  ["io", "app", "tools", "dev", "com", "co", "cloud"],
    "generic":   ["com", "io", "co", "ai", "dev", "app", "tech"],
}

# TLDs in a minimal viable portfolio per profile
_PORTFOLIO_MUST_HAVE: dict[str, list[str]] = {
    "tech":      ["io", "com"],
    "ai":        ["ai", "io"],
    "security":  ["io", "com"],
    "finance":   ["com", "co"],
    "health":    ["com", "co"],
    "social":    ["co", "com"],
    "education": ["com", "org"],
    "document":  ["io", "com"],
    "generic":   ["com", "io"],
}

_PORTFOLIO_NICE_TO_HAVE: dict[str, list[str]] = {
    "tech":      ["dev", "app", "ai"],
    "ai":        ["com", "dev", "tech"],
    "security":  ["dev", "systems", "net"],
    "finance":   ["net", "finance", "io"],
    "health":    ["health", "org", "io"],
    "social":    ["app", "io", "link"],
    "education": ["io", "app", "tools"],
    "document":  ["app", "tools", "co"],
    "generic":   ["co", "dev", "app"],
}


# ─────────────────────────────────────────────────────────────────────────────
# § 5  RECOMMENDATION DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TLDRecommendation:
    """
    Full TLD strategy recommendation for a brand name + profile.

    Attributes:
        profile:         Profile the recommendation was computed for.
        primary:         The single highest-priority TLD to register first.
        primary_info:    :class:`TLDInfo` for the primary TLD.
        primary_rationale: Why this TLD was chosen as primary.
        must_have:       Minimum portfolio — register all of these.
        nice_to_have:    Secondary portfolio — register if budget allows.
        optional:        Defensive registrations — brand protection.
        ranked_tlds:     Full ordered list of TLDs for this profile.
        availability:    Dict ``{tld: status}`` for available TLDs (populated
                         when called with domain check results).
        notes:           Strategic advisory notes.
    """
    profile:            str
    primary:            str
    primary_info:       TLDInfo
    primary_rationale:  str
    must_have:          list[str]         = field(default_factory=list)
    nice_to_have:       list[str]         = field(default_factory=list)
    optional:           list[str]         = field(default_factory=list)
    ranked_tlds:        list[str]         = field(default_factory=list)
    availability:       dict[str, str]    = field(default_factory=dict)
    notes:              list[str]         = field(default_factory=list)

    @property
    def free_must_have(self) -> list[str]:
        """Must-have TLDs confirmed as FREE in availability dict."""
        return [t for t in self.must_have
                if self.availability.get(t) == AvailStatus.FREE.value]

    @property
    def taken_must_have(self) -> list[str]:
        """Must-have TLDs confirmed as TAKEN in availability dict."""
        return [t for t in self.must_have
                if self.availability.get(t) == AvailStatus.TAKEN.value]

    def __str__(self) -> str:
        return (
            f"TLDRecommendation(profile={self.profile}  "
            f"primary=.{self.primary}  must={['.'+t for t in self.must_have]})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# § 6  TLD STRATEGY CLASS
# ─────────────────────────────────────────────────────────────────────────────

class TLDStrategy:
    """
    TLD selection strategy and recommendation engine.

    Stateless — safe to instantiate once and reuse.

    Usage::

        from nexagen.domains.tld_strategy import TLDStrategy
        strategy = TLDStrategy()

        # Simple ranked list for domain_generator
        tlds = strategy.ranked_tlds("tech", cfg)

        # Full advisory recommendation
        rec = strategy.recommend("ai", cfg)
        print(rec.primary_rationale)

        # Availability-aware re-ranking
        rec = strategy.recommend("tech", cfg, available_tlds=["io","dev"])
    """

    def tier(self, tld: str) -> TLDTier:
        """
        Return the :class:`TLDTier` for a TLD.

        Args:
            tld: TLD string (with or without leading dot).

        Returns:
            TLDTier (defaults to NICHE for unknown TLDs).
        """
        t = tld.lower().lstrip(".")
        return _TLD_DB.get(t, TLDInfo(t, TLDTier.NICHE, 10)).tier

    def info(self, tld: str) -> TLDInfo:
        """
        Return the full :class:`TLDInfo` intelligence record for a TLD.

        Args:
            tld: TLD string.

        Returns:
            TLDInfo (stub record for unknown TLDs).
        """
        t = tld.lower().lstrip(".")
        return _TLD_DB.get(t, TLDInfo(t, TLDTier.NICHE, TLD_SCORES.get(t, 10)))

    def score(self, tld: str, profile: str = "generic") -> int:
        """
        Return a profile-aware composite TLD score (0–100).

        A TLD that appears in the profile's ranked list receives a bonus
        proportional to its ranking position.

        Args:
            tld:     TLD string.
            profile: Brand profile identifier.

        Returns:
            Integer score 0–100.
        """
        t         = tld.lower().lstrip(".")
        info      = self.info(t)
        base      = info.composite

        ranked = _PROFILE_RANKED.get(profile, _PROFILE_RANKED["generic"])
        if t in ranked:
            # Rank 0 = best; boost decreases linearly
            rank_bonus = max(0, 20 - ranked.index(t) * 2)
            return min(100, base + rank_bonus)
        return base

    def ranked_tlds(
        self,
        profile:        str              = "generic",
        cfg:            Optional[Settings] = None,
        *,
        available_tlds: Optional[Sequence[str]] = None,
        max_tlds:       int              = 30,
    ) -> list[str]:
        """
        Return a priority-ordered TLD list for a profile.

        If *available_tlds* is provided (e.g. from domain check results),
        free TLDs are promoted above taken ones of the same tier.

        Args:
            profile:        Brand profile.
            cfg:            Settings (preferred_tlds respected).
            available_tlds: TLDs confirmed as FREE. Free TLDs are promoted.
            max_tlds:       Maximum TLDs to return.

        Returns:
            Ordered list of TLD strings.
        """
        if cfg is None:
            cfg = get_settings()

        free_set = set(t.lower().lstrip(".") for t in (available_tlds or []))

        # Collect all candidates
        candidates: set[str] = set()
        for t in cfg.preferred_tlds:
            candidates.add(t.lower())
        for t in _PROFILE_RANKED.get(profile, []):
            candidates.add(t)
        for t in _load_tlds():
            candidates.add(t.lower())
        for t in TLD_SCORES.keys():
            candidates.add(t)

        def _sort_key(t: str) -> tuple[int, int, int, str]:
            is_free   = int(t in free_set)    # 1 = free, 0 = unknown/taken
            prof_score = self.score(t, profile)
            tier_w     = self.tier(t).weight
            return (-is_free, -tier_w, -prof_score, t)

        ordered = sorted(candidates, key=_sort_key)
        return ordered[:max_tlds]

    def recommend(
        self,
        profile:        str                        = "generic",
        cfg:            Optional[Settings]         = None,
        *,
        available_tlds: Optional[Sequence[str]]    = None,
        domain_entries: Optional[Sequence[DomainEntry]] = None,
    ) -> TLDRecommendation:
        """
        Produce a full TLD strategy recommendation for a brand profile.

        Args:
            profile:        Brand profile.
            cfg:            Active Settings.
            available_tlds: TLDs confirmed as FREE (overrides domain_entries).
            domain_entries: Checked :class:`DomainEntry` results — used to
                            build the availability dict and re-rank free TLDs.

        Returns:
            :class:`TLDRecommendation`
        """
        if cfg is None:
            cfg = get_settings()

        # Build availability map from domain_entries
        availability: dict[str, str] = {}
        if domain_entries:
            for entry in domain_entries:
                availability[entry.tld] = entry.status

        # Resolve free TLDs
        free_set: set[str] = set()
        if available_tlds:
            free_set = {t.lower().lstrip(".") for t in available_tlds}
        elif availability:
            free_set = {t for t, s in availability.items()
                        if s == AvailStatus.FREE.value}

        ranked = self.ranked_tlds(
            profile, cfg, available_tlds=list(free_set) or None, max_tlds=25,
        )

        # Primary TLD: first profile-ranked free TLD, else first profile-ranked
        profile_ranked = _PROFILE_RANKED.get(profile, _PROFILE_RANKED["generic"])
        primary = next(
            (t for t in profile_ranked if t in free_set),
            None
        ) or (profile_ranked[0] if profile_ranked else "com")

        primary_info = self.info(primary)

        # Portfolio
        must_have    = _PORTFOLIO_MUST_HAVE.get(profile, ["com", "io"])
        nice_to_have = _PORTFOLIO_NICE_TO_HAVE.get(profile, ["dev", "app"])
        optional_    = [t for t in ranked[:15]
                        if t not in must_have and t not in nice_to_have][:5]

        # Primary rationale
        rationale = primary_info.rationale or f".{primary} is the best fit for {profile} products."
        if primary in free_set:
            rationale += " Currently AVAILABLE."
        elif primary in availability and availability[primary] == AvailStatus.TAKEN.value:
            rationale += " Note: TAKEN — consider alternatives from must-have list."

        # Advisory notes
        notes: list[str] = []
        taken_must = [t for t in must_have
                      if availability.get(t) == AvailStatus.TAKEN.value]
        if taken_must:
            notes.append(
                f"Must-have TLDs already taken: {['.'+t for t in taken_must]}. "
                "Register alternatives quickly."
            )
        free_must = [t for t in must_have
                     if availability.get(t) == AvailStatus.FREE.value]
        if free_must:
            notes.append(
                f"Must-have TLDs currently free: {['.'+t for t in free_must]}. "
                "Register immediately."
            )
        if not free_set and not availability:
            notes.append(
                "Run domain availability checks to get personalised availability-aware advice."
            )

        return TLDRecommendation(
            profile           = profile,
            primary           = primary,
            primary_info      = primary_info,
            primary_rationale = rationale,
            must_have         = must_have,
            nice_to_have      = nice_to_have,
            optional          = optional_,
            ranked_tlds       = ranked,
            availability      = availability,
            notes             = notes,
        )

    def portfolio(
        self,
        profile:        str,
        available_tlds: Optional[Sequence[str]] = None,
        *,
        n:              int = 5,
    ) -> list[str]:
        """
        Return the minimum viable TLD portfolio for a profile.

        Combines must-have + nice-to-have, filtered to *available_tlds* first,
        then falling back to the strategy default.

        Args:
            profile:        Brand profile.
            available_tlds: TLDs confirmed as FREE.
            n:              Maximum portfolio size.

        Returns:
            List of TLD strings for the recommended portfolio.
        """
        must     = _PORTFOLIO_MUST_HAVE.get(profile, ["com", "io"])
        nice     = _PORTFOLIO_NICE_TO_HAVE.get(profile, ["dev", "app"])
        combined = list(dict.fromkeys(must + nice))  # preserve order, deduplicate

        if available_tlds:
            free_set = {t.lower().lstrip(".") for t in available_tlds}
            # Prioritise free TLDs within portfolio
            free_first = [t for t in combined if t in free_set]
            others     = [t for t in combined if t not in free_set]
            combined   = free_first + others

        return combined[:n]

    def tier_breakdown(
        self,
        tlds: Sequence[str],
    ) -> dict[str, list[str]]:
        """
        Group a list of TLDs by their tier.

        Args:
            tlds: TLD strings.

        Returns:
            Dict ``{tier_name: [tlds]}`` with keys
            ``"premium"``, ``"strong"``, ``"standard"``, ``"niche"``.
        """
        result: dict[str, list[str]] = {
            "premium": [], "strong": [], "standard": [], "niche": [],
        }
        for tld in tlds:
            t    = tld.lower().lstrip(".")
            tier = self.tier(t).value
            result[tier].append(t)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# § 7  FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

# Module-level singleton for functional API calls
_strategy = TLDStrategy()


def recommend_tlds(
    profile:        str                    = "generic",
    cfg:            Optional[Settings]     = None,
    *,
    available_tlds: Optional[Sequence[str]] = None,
    max_tlds:       int                    = 25,
) -> list[str]:
    """
    Return a priority-ordered TLD list for a profile.

    Functional wrapper around :meth:`TLDStrategy.ranked_tlds`.

    Args:
        profile:        Brand profile.
        cfg:            Active Settings.
        available_tlds: TLDs confirmed as FREE (will be promoted).
        max_tlds:       Maximum TLDs to return.

    Returns:
        Ordered list of TLD strings.
    """
    return _strategy.ranked_tlds(profile, cfg,
                                 available_tlds=available_tlds,
                                 max_tlds=max_tlds)


def tld_tier(tld: str) -> str:
    """
    Return the tier name string for a TLD.

    Args:
        tld: TLD string.

    Returns:
        ``"premium"`` | ``"strong"`` | ``"standard"`` | ``"niche"``
    """
    return _strategy.tier(tld).value


def tld_score(tld: str, profile: str = "generic") -> int:
    """
    Return a profile-aware composite score for a TLD (0–100).

    Args:
        tld:     TLD string.
        profile: Brand profile.

    Returns:
        Integer score 0–100.
    """
    return _strategy.score(tld, profile)


def tld_info(tld: str) -> TLDInfo:
    """
    Return the full :class:`TLDInfo` intelligence record for a TLD.

    Args:
        tld: TLD string.

    Returns:
        :class:`TLDInfo`
    """
    return _strategy.info(tld)
