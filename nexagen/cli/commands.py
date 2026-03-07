"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  cli/commands.py  ·  All command handlers — generate, analyze, domains,    ║
║                      startup report, and export                             ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Each public function in this module is a complete command handler.
They all follow the same contract:

  • Accept a cfg: Settings argument for all tunable parameters
  • Accept animated: bool to toggle UI animations
  • Return structured data (list | dict | None) — never print-only
  • Use the ui/ layer for all output, never call print() directly
  • Degrade gracefully: advanced engine modules are imported with
    try/except so the CLI works even before those modules are built

Public API
──────────
  cmd_generate_names(keywords, cfg, animated)   → list[NameResult]
  cmd_analyze_brand(names, cfg, animated)       → list[AnalysisData]
  cmd_domain_suggestions(name, cfg, ...)        → dict
  cmd_startup_report(project, keywords, ...)    → dict
  cmd_export(data, fmt, cfg)                    → str | None

Internal helpers (prefixed _) are not part of the public API and may
change between versions.
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from ..config.constants import (
    BRAND_BLACKLIST_SEED,
    C_ACCENT,
    C_AMBER,
    C_GOLD,
    C_GRAY,
    C_GREEN,
    C_PURPLE,
    C_RED,
    C_TEAL,
    C_WHITE,
    CHECK_MAX_WORKERS,
    CHECK_TIMEOUT_SEC,
    DATASETS_DIR,
    DS_AI_TERMS,
    DS_BUSINESS_TERMS,
    DS_COMMON_WORDS,
    DS_PREFIXES,
    DS_SUFFIXES,
    DS_SYNONYMS,
    DS_TECH_TERMS,
    DS_TLDS,
    EXPORT_DIR,
    GEN_DEFAULT_COUNT,
    GEN_MAX_CANDIDATES,
    GEN_MAX_COUNT,
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    SCORE_DECENT,
    SCORE_PREMIUM,
    SCORE_STRONG,
    SCORE_WEAK,
    TLD_SCORES,
    BrandTier,
    Profile,
)
from ..config.settings import Settings, get_settings
from ..ui.banner import (
    console,
    msg_fail,
    msg_info,
    msg_ok,
    msg_step,
    msg_warn,
    print_hint,
    print_panel,
    section,
    separator,
    subsection,
)
from ..ui.progress import CheckResult
from ..ui.tables import (
    AnalysisData,
    DomainEntry,
    NameResult,
    PlatformEntry,
    print_analysis_table,
    print_comparison_table,
    print_domain_table,
    print_export_summary,
    print_names_table,
    print_platform_table,
    print_score_card,
    print_startup_report_summary,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  DATASET LOADER  (lightweight, no dataset_loader module needed)
# ─────────────────────────────────────────────────────────────────────────────

class _DatasetCache:
    """
    Lazy-loading, in-process cache for all dataset files.
    Loads each file once and holds it for the process lifetime.
    """
    _cache: dict[str, list[str]] = {}

    @classmethod
    def load(cls, path: Path) -> list[str]:
        key = str(path)
        if key not in cls._cache:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                cls._cache[key] = [
                    ln.strip().lower()
                    for ln in lines
                    if ln.strip() and not ln.strip().startswith("#")
                ]
            except (OSError, FileNotFoundError):
                cls._cache[key] = []
        return cls._cache[key]

    @classmethod
    def load_synonyms(cls) -> dict[str, list[str]]:
        """Parse synonyms.txt → {root: [syn1, syn2, ...]}."""
        key = "__synonyms__"
        if key not in cls._cache:
            groups: dict[str, list[str]] = {}
            try:
                for line in DS_SYNONYMS.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip().lower() for p in re.split(r"[,|;]", line)]
                    if len(parts) >= 2:
                        groups[parts[0]] = parts[1:]
            except (OSError, FileNotFoundError):
                pass
            cls._cache[key] = groups  # type: ignore[assignment]
        return cls._cache[key]  # type: ignore[return-value]

    @classmethod
    def common_words(cls) -> frozenset[str]:
        key = "__common__"
        if key not in cls._cache:
            cls._cache[key] = frozenset(cls.load(DS_COMMON_WORDS))
        return frozenset(cls._cache[key])

    @classmethod
    def blacklist(cls) -> frozenset[str]:
        key = "__blacklist__"
        if key not in cls._cache:
            extra: list[str] = []
            try:
                bl_path = DATASETS_DIR / "brand_blacklist.txt"
                if bl_path.exists():
                    extra = [ln.strip().lower() for ln in bl_path.read_text().splitlines()
                             if ln.strip() and not ln.startswith("#")]
            except OSError:
                pass
            cls._cache[key] = list(BRAND_BLACKLIST_SEED | frozenset(extra))
        return frozenset(cls._cache[key])

    @classmethod
    def tlds(cls) -> list[str]:
        return cls.load(DS_TLDS) or ["com", "io", "co", "ai", "dev"]

    @classmethod
    def prefixes(cls) -> list[str]:
        return cls.load(DS_PREFIXES) or [
            "get", "use", "try", "my", "the", "go", "run", "build",
            "open", "free", "fast", "smart", "pro", "next", "meta",
        ]

    @classmethod
    def suffixes(cls) -> list[str]:
        return cls.load(DS_SUFFIXES) or [
            "hub", "lab", "io", "ai", "ly", "fy", "ify", "er",
            "ops", "base", "kit", "desk", "flow", "forge",
        ]

    @classmethod
    def tech_terms(cls) -> list[str]:
        return cls.load(DS_TECH_TERMS)

    @classmethod
    def ai_terms(cls) -> list[str]:
        return cls.load(DS_AI_TERMS)

    @classmethod
    def business_terms(cls) -> list[str]:
        return cls.load(DS_BUSINESS_TERMS)

    @classmethod
    def vocab_for_profile(cls, profile: str) -> list[str]:
        """Return the vocabulary list most relevant to the given profile."""
        mapping: dict[str, list[str]] = {
            Profile.TECH.value:     cls.tech_terms(),
            Profile.AI.value:       cls.ai_terms(),
            Profile.SECURITY.value: cls.tech_terms(),
            Profile.FINANCE.value:  cls.business_terms(),
            Profile.HEALTH.value:   cls.business_terms(),
            Profile.SOCIAL.value:   cls.business_terms(),
        }
        base = mapping.get(profile, [])
        # Always blend a little tech vocabulary
        if not base:
            base = cls.tech_terms() + cls.business_terms()
        return base


DS = _DatasetCache  # short alias


# ─────────────────────────────────────────────────────────────────────────────
# § 2  NAME GENERATION ENGINE  (self-contained — no engine/ module needed)
# ─────────────────────────────────────────────────────────────────────────────

def _expand_keywords(keywords: list[str], cfg: Settings) -> list[str]:
    """
    Expand seed keywords with synonyms and profile vocabulary.

    Returns a de-duplicated list of candidate seed words.
    """
    seeds: list[str] = list(keywords)
    synonyms = DS.load_synonyms()
    vocab    = DS.vocab_for_profile(cfg.profile)

    # Synonym expansion
    if cfg.use_synonyms:
        for kw in list(seeds):
            if kw in synonyms:
                seeds.extend(synonyms[kw][:4])

    # Nearest vocab words (those containing or contained in any keyword)
    if vocab:
        for kw in keywords:
            for v in vocab:
                if kw in v or v in kw or (len(kw) > 3 and kw[:3] == v[:3]):
                    seeds.append(v)

    # Deduplicate, keep first occurrence
    seen: set[str] = set()
    result: list[str] = []
    for w in seeds:
        w = re.sub(r"[^a-z]", "", w.lower())
        if w and w not in seen and len(w) >= 2:
            seen.add(w)
            result.append(w)

    return result[:60]


def _generate_candidates(seeds: list[str], cfg: Settings) -> list[str]:
    """
    Generate raw candidate names from seeds using multiple strategies.
    Returns a list of lowercase alphabetic strings, before scoring.
    """
    candidates: set[str] = set()
    prefixes = DS.prefixes()  if cfg.use_prefixes  else []
    suffixes = DS.suffixes()  if cfg.use_suffixes  else []
    vocab    = DS.vocab_for_profile(cfg.profile)

    # Strategy 1: Direct seeds (already clean)
    for s in seeds:
        if cfg.min_len <= len(s) <= cfg.max_len:
            candidates.add(s)

    # Strategy 2: Seed + suffix combinations
    for seed in seeds[:20]:
        for suf in suffixes[:25]:
            combo = seed + suf
            if cfg.min_len <= len(combo) <= cfg.max_len:
                candidates.add(combo)

    # Strategy 3: Prefix + seed combinations
    for seed in seeds[:20]:
        for pre in prefixes[:20]:
            combo = pre + seed
            if cfg.min_len <= len(combo) <= cfg.max_len:
                candidates.add(combo)

    # Strategy 4: Seed + seed blends (two-word compounds)
    if cfg.use_multiword and len(seeds) >= 2:
        for i, a in enumerate(seeds[:15]):
            for b in seeds[i + 1: i + 8]:
                if a == b:
                    continue
                combo = a + b
                if cfg.min_len <= len(combo) <= cfg.max_len:
                    candidates.add(combo)
                # Truncated blend: first half of a + b
                blend = a[: len(a) // 2 + 1] + b
                if cfg.min_len <= len(blend) <= cfg.max_len:
                    candidates.add(blend)

    # Strategy 5: Vocab sampling (profile-matched random picks)
    if vocab:
        sample = random.sample(vocab, min(60, len(vocab)))
        for v in sample:
            if cfg.min_len <= len(v) <= cfg.max_len:
                candidates.add(v)
            for suf in suffixes[:10]:
                combo = v + suf
                if cfg.min_len <= len(combo) <= cfg.max_len:
                    candidates.add(combo)

    # Strategy 6: Mutations (drop vowel, add -ex/-ix/-on endings)
    mutations: list[str] = []
    for seed in seeds[:12]:
        # Drop last vowel if long enough
        if len(seed) > 5:
            from ..config.constants import VOWELS
            for i in range(len(seed) - 1, 0, -1):
                if seed[i] in "aeiou":
                    mutant = seed[:i] + seed[i + 1:]
                    if cfg.min_len <= len(mutant) <= cfg.max_len:
                        mutations.append(mutant)
                    break
        # Add power endings
        for ending in ("ex", "ix", "on", "en", "al", "ar"):
            m = seed.rstrip("aeiou") + ending
            if cfg.min_len <= len(m) <= cfg.max_len:
                mutations.append(m)

    candidates.update(mutations)

    # Final filter: alphabetic only, within length bounds
    result = [
        c for c in candidates
        if c.isalpha()
        and cfg.min_len <= len(c) <= cfg.max_len
    ]

    return result[:GEN_MAX_CANDIDATES]


# ─────────────────────────────────────────────────────────────────────────────
# § 3  BRAND SCORING ENGINE  (self-contained)
# ─────────────────────────────────────────────────────────────────────────────

def _score_pronounceability(name: str) -> int:
    """Score how easy the name is to say aloud (0–100)."""
    from ..utils.text_utils import (
        vowel_ratio, max_consonant_run,
        alternation_score, has_forbidden_sequence,
        syllable_count,
    )
    score = 60  # baseline

    # Vowel ratio: ideal ~35–50%
    vr = vowel_ratio(name)
    if 0.30 <= vr <= 0.55:
        score += 20
    elif 0.20 <= vr < 0.30 or 0.55 < vr <= 0.65:
        score += 8
    else:
        score -= 15

    # Consonant clusters
    run = max_consonant_run(name)
    if run <= 1:
        score += 15
    elif run == 2:
        score += 8
    elif run == 3:
        score -= 5
    else:
        score -= 20

    # Alternation (CVCV…)
    alt = alternation_score(name)
    score += int(alt * 15)

    # Forbidden sequences
    if has_forbidden_sequence(name):
        score -= 20

    # Syllable count: 2–3 syllables are ideal
    syls = syllable_count(name)
    if syls in (2, 3):
        score += 10
    elif syls == 1 and len(name) <= 4:
        score += 5
    elif syls > 4:
        score -= 10

    return max(0, min(100, score))


def _score_memorability(name: str) -> int:
    """Score how memorable / catchy the name is (0–100)."""
    from ..utils.text_utils import (
        syllable_count, ends_with_vowel,
        starts_with_strong_consonant, has_alliteration,
    )
    score = 55

    n = len(name)

    # Length sweet spot
    if NAME_LENGTH_IDEAL_MIN <= n <= NAME_LENGTH_IDEAL_MAX:
        score += 20
    elif n < NAME_LENGTH_IDEAL_MIN:
        score += max(0, 12 - (NAME_LENGTH_IDEAL_MIN - n) * 6)
    else:
        score -= min(20, (n - NAME_LENGTH_IDEAL_MAX) * 4)

    # Strong opening consonant
    if starts_with_strong_consonant(name):
        score += 8

    # Ends on a vowel (soft, approachable)
    if ends_with_vowel(name):
        score += 6

    # Alliteration bonus
    if has_alliteration(name):
        score += 8

    # Syllable rhythm: 2–3 syllables optimal
    syls = syllable_count(name)
    if syls == 2:
        score += 12
    elif syls == 3:
        score += 8
    elif syls == 1:
        score += 4
    else:
        score -= (syls - 3) * 6

    # Penalise long unbroken strings
    if n > 10:
        score -= (n - 10) * 3

    return max(0, min(100, score))


def _score_uniqueness(name: str, pool: list[str]) -> int:
    """Score how distinct the name is from others in the pool (0–100)."""
    from ..utils.levenshtein import levenshtein

    common = DS.common_words()
    blacklist = DS.blacklist()
    score = 80

    # Exact hit in common words
    if name in common:
        score -= 25

    # Blacklist similarity
    for brand in blacklist:
        d = levenshtein(name, brand)
        if d == 0:
            return 0
        if d <= 2:
            score -= 30
            break
        if d <= 3:
            score -= 10

    # Distance from pool (near-duplicates)
    if pool:
        min_dist = min(levenshtein(name, other) for other in pool[:50])
        if min_dist <= 1:
            score -= 30
        elif min_dist == 2:
            score -= 15
        elif min_dist == 3:
            score -= 5

    return max(0, min(100, score))


def _score_length_fitness(name: str, cfg: Settings) -> int:
    """Score how well the name length fits the configured ideal (0–100)."""
    n     = len(name)
    ideal = (cfg.min_len + cfg.max_len) / 2
    delta = abs(n - ideal)
    score = max(0, 100 - int(delta * 12))
    # Bonus for perfect sweet-spot
    if cfg.min_len <= n <= cfg.max_len:
        score = min(100, score + 10)
    return score


def _composite_score(
    pronounce: int,
    memory: int,
    unique: int,
    length_fit: int,
    weights: dict[str, float],
) -> int:
    raw = (
        pronounce   * weights.get("pronounce",    0.30) +
        memory      * weights.get("memorability", 0.30) +
        unique      * weights.get("uniqueness",   0.20) +
        length_fit  * weights.get("length_fit",   0.20)
    )
    return max(0, min(100, round(raw)))


def _tm_risk(name: str) -> str:
    """Quick trademark risk level using Levenshtein against blacklist."""
    from ..utils.levenshtein import levenshtein
    bl = DS.blacklist()
    for brand in bl:
        d = levenshtein(name, brand)
        if d == 0:
            return "high"
        if d <= 1:
            return "high"
        if d <= 2:
            return "medium"
        if d <= 3:
            return "low"
    return "none"


def _score_name(
    name: str,
    pool: list[str],
    cfg:  Settings,
) -> NameResult:
    """Score a single candidate and return a NameResult."""
    from ..utils.text_utils import syllable_count

    w  = cfg.score_weights
    p  = _score_pronounceability(name)
    m  = _score_memorability(name)
    u  = _score_uniqueness(name, pool)
    lf = _score_length_fitness(name, cfg)
    cs = _composite_score(p, m, u, lf, w)
    tm = _tm_risk(name)

    return NameResult(
        name=name,
        score=cs,
        pronounce=p,
        memorability=m,
        uniqueness=u,
        length_fit=lf,
        tm_risk=tm,
        syllables=syllable_count(name),
        profile=cfg.profile,
        style=cfg.style_mode,
    )


# ─────────────────────────────────────────────────────────────────────────────
# § 4  DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def _deduplicate(names: list[str], max_distance: int = 2) -> list[str]:
    """Remove near-duplicates using Levenshtein distance."""
    from ..utils.levenshtein import levenshtein
    kept: list[str] = []
    for candidate in names:
        too_close = any(
            levenshtein(candidate, k) <= max_distance for k in kept
        )
        if not too_close:
            kept.append(candidate)
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# § 5  CMD — GENERATE NAMES
# ─────────────────────────────────────────────────────────────────────────────

def cmd_generate_names(
    keywords:  list[str],
    cfg:       Optional[Settings] = None,
    animated:  bool               = True,
) -> list[NameResult]:
    """
    Generate brand name candidates from seed keywords.

    Pipeline:
      1. Expand keywords via synonyms + profile vocabulary
      2. Generate candidates using 6 strategies
      3. Deduplicate (Levenshtein distance ≤ 2)
      4. Score all candidates in parallel
      5. Sort by composite score, return top cfg.count names

    Args:
        keywords: 1–10 seed words supplied by the user.
        cfg:      Active Settings (defaults to get_settings()).
        animated: Whether to show Rich progress animations.

    Returns:
        Sorted list of NameResult objects (best first).
    """
    if cfg is None:
        cfg = get_settings()

    target = min(cfg.count, GEN_MAX_COUNT)

    # ── Step 1: Expand seeds ──────────────────────────────────────────────────
    from ..ui.animations import Spinner, reveal_names
    from ..ui.progress import GenerationProgress

    if animated:
        msg_step(1, 5, "Expanding keywords and synonyms…")

    seeds = _expand_keywords(keywords, cfg)

    if animated:
        msg_ok(f"Expanded to {len(seeds)} seed words")

    # ── Step 2: Generate candidates ───────────────────────────────────────────
    if animated:
        msg_step(2, 5, "Generating candidate names…")

    raw = _generate_candidates(seeds, cfg)

    if animated:
        msg_ok(f"{len(raw)} raw candidates generated")

    # ── Step 3: Deduplicate ───────────────────────────────────────────────────
    if animated:
        msg_step(3, 5, "Deduplicating candidates…")

    deduped = _deduplicate(raw)

    if animated:
        msg_ok(f"{len(deduped)} unique candidates after deduplication")

    # ── Step 4: Score ─────────────────────────────────────────────────────────
    if animated:
        msg_step(4, 5, f"Scoring {len(deduped)} candidates…")

    scored: list[NameResult] = []

    if animated:
        from ..ui.progress import track
        for name in track(deduped, "Scoring candidates", total=len(deduped), colour=C_PURPLE):
            result = _score_name(name, [r.name for r in scored], cfg)
            scored.append(result)
    else:
        for name in deduped:
            result = _score_name(name, [r.name for r in scored], cfg)
            scored.append(result)

    # ── Step 5: Sort and trim ─────────────────────────────────────────────────
    if animated:
        msg_step(5, 5, "Sorting and selecting top names…")

    scored.sort(key=lambda r: -r.score)
    final = scored[:target]

    if animated:
        console.print()
        msg_ok(f"Selected {len(final)} names  —  best score: {final[0].score if final else 0}/100")
        console.print()

    # ── Display results ───────────────────────────────────────────────────────
    if animated and final:
        reveal_names(
            names=[r.name.capitalize() for r in final[:10]],
            scores=[r.score for r in final[:10]],
            colours=[_tier_colour_for_score(r.score) for r in final[:10]],
        )

    print_names_table(final, show_domains=False)

    if len(final) > 1:
        print_comparison_table(final, top_n=5)

    return final


def _tier_colour_for_score(score: int) -> str:
    """Map a numeric score to a Rich hex colour string."""
    if score >= SCORE_PREMIUM:
        return C_GOLD
    if score >= SCORE_STRONG:
        return C_GREEN
    if score >= SCORE_DECENT:
        return C_ACCENT
    if score >= SCORE_WEAK:
        return C_AMBER
    return C_RED


# ─────────────────────────────────────────────────────────────────────────────
# § 6  CMD — ANALYZE BRAND
# ─────────────────────────────────────────────────────────────────────────────

def cmd_analyze_brand(
    names:    list[str],
    cfg:      Optional[Settings] = None,
    animated: bool               = True,
) -> list[AnalysisData]:
    """
    Analyze brand strength for one or more names.

    Produces:
      - Individual score cards for ≤ 3 names
      - Analysis comparison table for all names

    Args:
        names:    List of lowercase names to analyze.
        cfg:      Active Settings.
        animated: Whether to use animated scoring progress.

    Returns:
        List of AnalysisData with full dimension breakdown.
    """
    if cfg is None:
        cfg = get_settings()

    from ..utils.text_utils import (
        syllable_count, vowel_ratio,
        has_forbidden_sequence, soundex,
    )
    from ..ui.animations import PulseBar

    section("Brand Strength Analysis", C_PURPLE)
    console.print()

    results: list[AnalysisData] = []

    for i, name in enumerate(names, 1):
        if animated:
            msg_step(i, len(names), f"Analyzing '{name}'…")

        pool = [r.name for r in results]

        p  = _score_pronounceability(name)
        m  = _score_memorability(name)
        u  = _score_uniqueness(name, pool)
        lf = _score_length_fitness(name, cfg)
        cs = _composite_score(p, m, u, lf, cfg.score_weights)
        tm = _tm_risk(name)

        notes: list[str] = []

        if has_forbidden_sequence(name):
            notes.append("Contains a phonetically awkward character sequence.")
        if name in DS.common_words():
            notes.append("This is a common English word — low brand distinction.")
        if len(name) < NAME_LENGTH_IDEAL_MIN:
            notes.append(f"Name is short ({len(name)} chars); ideal minimum is {NAME_LENGTH_IDEAL_MIN}.")
        if len(name) > NAME_LENGTH_IDEAL_MAX:
            notes.append(f"Name is long ({len(name)} chars); may be harder to remember.")
        if tm in ("high", "medium"):
            notes.append(f"Trademark risk level is {tm.upper()} — verify before use.")
        if cs >= SCORE_PREMIUM:
            notes.append("Exceptional brand name — all metrics above threshold.")
        elif cs >= SCORE_STRONG:
            notes.append("Strong brand candidate — good to proceed.")

        data = AnalysisData(
            name=name,
            score=cs,
            tier=BrandTier.from_score(cs).value,
            pronounce=p,
            memorability=m,
            uniqueness=u,
            length_fit=lf,
            syllables=syllable_count(name),
            vowel_ratio=vowel_ratio(name),
            tm_risk=tm,
            is_common=name in DS.common_words(),
            phonetic_key=soundex(name),
            notes=notes,
        )
        results.append(data)

        # Show individual score card for first 3 names
        if i <= 3:
            console.print()
            print_score_card(name, data)

        if animated:
            time.sleep(0.1)

    # Summary table for multiple names
    if len(results) > 1:
        print_analysis_table(results)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# § 7  DOMAIN GENERATION + AVAILABILITY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _generate_domains(name: str, cfg: Settings) -> list[str]:
    """
    Generate a prioritised list of domain names for a brand name.

    Combines:
      - name + preferred TLDs
      - name + prefix variations  (getname, tryname, usename…)
      - name + suffix variations  (namehq, namehub, nameapp…)
    """
    domains: list[str] = []

    # Preferred TLDs first
    for tld in cfg.preferred_tlds:
        domains.append(f"{name}.{tld}")

    # Remaining TLDs from constants
    for tld in list(TLD_SCORES.keys())[:20]:
        candidate = f"{name}.{tld}"
        if candidate not in domains:
            domains.append(candidate)

    # Prefix variants
    if cfg.use_prefixes:
        prefixes = DS.prefixes()[:8]
        for pre in prefixes:
            for tld in cfg.preferred_tlds[:3]:
                domains.append(f"{pre}{name}.{tld}")

    # Suffix variants
    if cfg.use_suffixes:
        suffixes = DS.suffixes()[:6]
        for suf in suffixes:
            for tld in cfg.preferred_tlds[:2]:
                domains.append(f"{name}{suf}.{tld}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            result.append(d)

    return result[:40]


def _check_domain_rdap(domain: str, timeout: float = CHECK_TIMEOUT_SEC) -> str:
    """
    Query RDAP to check domain registration status.

    Returns: "free" | "taken" | "unknown"
    """
    try:
        url = f"https://rdap.org/domain/{domain}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "nexagen/1.0 (domain-check)",
                "Accept":     "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return "taken"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "free"
        return "unknown"
    except Exception:
        return "unknown"
    return "unknown"


def _check_platform_github(handle: str, timeout: float = CHECK_TIMEOUT_SEC) -> str:
    """Check GitHub user/org availability."""
    try:
        url = f"https://api.github.com/users/{handle}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "nexagen/1.0",
                "Accept":     "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "taken" if resp.status == 200 else "unknown"
    except urllib.error.HTTPError as e:
        return "free" if e.code == 404 else "unknown"
    except Exception:
        return "unknown"


def _check_platform_pypi(package: str, timeout: float = CHECK_TIMEOUT_SEC) -> str:
    """Check PyPI package name availability."""
    try:
        url = f"https://pypi.org/pypi/{package}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "nexagen/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "taken" if resp.status == 200 else "unknown"
    except urllib.error.HTTPError as e:
        return "free" if e.code == 404 else "unknown"
    except Exception:
        return "unknown"


def _check_platform_npm(package: str, timeout: float = CHECK_TIMEOUT_SEC) -> str:
    """Check npm package name availability."""
    try:
        url = f"https://registry.npmjs.org/{package}"
        req = urllib.request.Request(url, headers={"User-Agent": "nexagen/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "taken" if resp.status == 200 else "unknown"
    except urllib.error.HTTPError as e:
        return "free" if e.code == 404 else "unknown"
    except Exception:
        return "unknown"


def cmd_domain_suggestions(
    name:              str,
    cfg:               Optional[Settings] = None,
    animated:          bool               = True,
    check_platforms:   bool               = True,
) -> dict[str, Any]:
    """
    Generate and check domain + platform availability for a brand name.

    Args:
        name:            Lowercase brand name.
        cfg:             Active Settings.
        animated:        Whether to show animated scan progress.
        check_platforms: Whether to also check GitHub/PyPI/npm.

    Returns:
        Dict with keys: "name", "domains" (list[DomainEntry]),
        "platforms" (list[PlatformEntry]).
    """
    if cfg is None:
        cfg = get_settings()

    from ..ui.animations import flash_check, live_scan
    from ..ui.progress import DomainCheckProgress

    section(f"Domain Availability  —  {name.upper()}", C_TEAL)
    console.print()

    domains_to_check = _generate_domains(name, cfg)
    domain_entries: list[DomainEntry] = []
    platform_entries: list[PlatformEntry] = []

    # ── Domain checks (parallel) ──────────────────────────────────────────────
    total = len(domains_to_check)
    msg_info(f"Checking {total} domains across {len(set(d.split('.')[-1] for d in domains_to_check))} TLDs…")
    console.print()

    do_checks = cfg.do_domain_checks

    def _check_one_domain(domain: str) -> DomainEntry:
        tld_part = domain.split(".")[-1]
        rank     = TLD_SCORES.get(tld_part, 10)
        if do_checks:
            status = _check_domain_rdap(domain, cfg.check_timeout)
        else:
            status = "unknown"
        return DomainEntry(
            domain=domain,
            status=status,
            tld=tld_part,
            tld_rank=rank,
        )

    if animated:
        with DomainCheckProgress(total=total, label="Checking domains") as dcp:
            workers = min(cfg.check_workers, total, CHECK_MAX_WORKERS)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_check_one_domain, d): d for d in domains_to_check}
                for fut in as_completed(futures):
                    entry = fut.result()
                    domain_entries.append(entry)
                    dcp.record(CheckResult(
                        target=entry.domain,
                        platform="domain",
                        available=entry.status == "free",
                        detail=entry.tld,
                    ))
    else:
        workers = min(cfg.check_workers, total, CHECK_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            domain_entries = list(ex.map(_check_one_domain, domains_to_check))

    # ── Platform checks ───────────────────────────────────────────────────────
    if check_platforms and cfg.do_handle_checks:
        console.print()
        msg_info("Checking platform handle availability…")
        console.print()

        platform_tasks: list[tuple[str, str, Callable]] = []
        if cfg.check_github:
            platform_tasks.append((name, "github",  _check_platform_github))
        if cfg.check_pypi:
            platform_tasks.append((name, "pypi",    _check_platform_pypi))
        if cfg.check_npm:
            platform_tasks.append((name, "npm",     _check_platform_npm))

        def _check_platform(task: tuple) -> PlatformEntry:
            handle, platform, fn = task
            status = fn(handle, cfg.check_timeout)
            return PlatformEntry(handle=handle, platform=platform, status=status)

        with ThreadPoolExecutor(max_workers=len(platform_tasks) or 1) as ex:
            platform_entries = list(ex.map(_check_platform, platform_tasks))

    # ── Display results ───────────────────────────────────────────────────────
    console.print()
    print_domain_table(domain_entries, name=name)

    if platform_entries:
        print_platform_table(platform_entries, name=name)

    return {
        "name":      name,
        "domains":   domain_entries,
        "platforms": platform_entries,
    }


# ─────────────────────────────────────────────────────────────────────────────
# § 8  CMD — STARTUP REPORT
# ─────────────────────────────────────────────────────────────────────────────

def cmd_startup_report(
    project:  str,
    keywords: list[str],
    count:    int               = GEN_DEFAULT_COUNT,
    cfg:      Optional[Settings] = None,
    animated: bool               = True,
) -> dict[str, Any]:
    """
    Full startup naming intelligence report.

    Combines:
      1. Name generation from keywords
      2. Brand scoring for all candidates
      3. Domain availability for top 5 names
      4. Platform handle checks for best name
      5. Summary report display

    Args:
        project:  Project or startup name (for report header).
        keywords: 1–6 seed keywords.
        count:    Number of names to generate.
        cfg:      Active Settings.
        animated: Whether to use animated progress.

    Returns:
        Dict with full report data.
    """
    if cfg is None:
        cfg = get_settings()

    cfg.count = min(count, GEN_MAX_COUNT)
    start     = time.monotonic()

    from ..ui.progress import MultiStepProgress, WorkflowStep

    section(f"Startup Naming Report  ·  {project}", C_GOLD)
    console.print()

    steps = [
        WorkflowStep("Keyword analysis",    total=len(keywords) * 10, colour=C_TEAL),
        WorkflowStep("Name generation",     total=cfg.count,           colour=C_ACCENT),
        WorkflowStep("Brand scoring",       total=cfg.count,           colour=C_PURPLE),
        WorkflowStep("Domain discovery",    total=5 * len(cfg.preferred_tlds), colour=C_GREEN),
        WorkflowStep("Platform checks",     total=3,                   colour=C_GOLD),
    ]

    domain_hits:    list[DomainEntry]   = []
    platform_hits:  list[PlatformEntry] = []

    if animated:
        with MultiStepProgress(steps, title=f"Building report: {project}") as msp:

            # Step 1: Keyword analysis
            seeds = _expand_keywords(keywords, cfg)
            for _ in range(len(keywords) * 10):
                msp.advance("Keyword analysis")
                time.sleep(0.01)
            msp.complete("Keyword analysis")

            # Step 2: Generation
            raw = _generate_candidates(seeds, cfg)
            deduped = _deduplicate(raw)
            for _ in range(min(cfg.count, len(deduped))):
                msp.advance("Name generation")
                time.sleep(0.008)
            msp.complete("Name generation")

            # Step 3: Scoring
            scored: list[NameResult] = []
            for name in deduped:
                result = _score_name(name, [r.name for r in scored], cfg)
                scored.append(result)
                msp.advance("Brand scoring")
            scored.sort(key=lambda r: -r.score)
            top_names = scored[:cfg.count]
            msp.complete("Brand scoring")

            # Step 4: Domain discovery for top 5
            top5_names = [r.name for r in top_names[:5]]
            for nm in top5_names:
                dom_list = _generate_domains(nm, cfg)
                for dom in dom_list[:len(cfg.preferred_tlds)]:
                    tld    = dom.split(".")[-1]
                    status = _check_domain_rdap(dom, cfg.check_timeout) if cfg.do_domain_checks else "unknown"
                    domain_hits.append(DomainEntry(dom, status, tld, TLD_SCORES.get(tld, 10)))
                    msp.advance("Domain discovery")
            msp.complete("Domain discovery")

            # Step 5: Platform checks for best name
            best = top_names[0].name if top_names else ""
            if best and cfg.do_handle_checks:
                for platform, fn in [
                    ("github", _check_platform_github),
                    ("pypi",   _check_platform_pypi),
                    ("npm",    _check_platform_npm),
                ]:
                    status = fn(best, cfg.check_timeout)
                    platform_hits.append(PlatformEntry(best, platform, status))
                    msp.advance("Platform checks")
            msp.complete("Platform checks")

    else:
        # Silent mode
        seeds       = _expand_keywords(keywords, cfg)
        raw         = _generate_candidates(seeds, cfg)
        deduped     = _deduplicate(raw)
        scored_list: list[NameResult] = []
        for nm in deduped:
            scored_list.append(_score_name(nm, [r.name for r in scored_list], cfg))
        scored_list.sort(key=lambda r: -r.score)
        top_names   = scored_list[:cfg.count]

    elapsed = time.monotonic() - start

    # ── Attach domain data to top NameResults ─────────────────────────────────
    for res in top_names:
        res.domains = {
            e.domain.split(".", 1)[-1]: e.status
            for e in domain_hits
            if e.domain.startswith(res.name + ".")
        }
        res.platforms = {
            p.platform: p.status
            for p in platform_hits
            if p.handle == res.name
        }

    # ── Display ───────────────────────────────────────────────────────────────
    console.print()
    print_names_table(top_names, title=f"Names for '{project}'", show_domains=True)
    print_startup_report_summary(
        project=project,
        keywords=keywords,
        top_names=top_names,
        domain_hits=domain_hits,
        elapsed=elapsed,
    )

    if domain_hits:
        print_domain_table(domain_hits, name=top_names[0].name if top_names else "")
    if platform_hits:
        print_platform_table(platform_hits, name=top_names[0].name if top_names else "")

    return {
        "project":         project,
        "keywords":        keywords,
        "names":           top_names,
        "domains":         domain_hits,
        "platforms":       platform_hits,
        "names_generated": len(top_names),
        "checks_run":      len(domain_hits) + len(platform_hits),
        "elapsed":         elapsed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# § 9  CMD — EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def cmd_export(
    data:  Any,
    fmt:   str               = "json",
    cfg:   Optional[Settings] = None,
    label: str               = "",
) -> Optional[str]:
    """
    Export command results to JSON, CSV, Markdown, or all three.

    Args:
        data:  Result data — list[NameResult] | list[AnalysisData] | dict.
        fmt:   "json" | "csv" | "markdown" | "all".
        cfg:   Active Settings (for export path).
        label: Optional filename prefix.

    Returns:
        Path string of the primary output file, or None on failure.
    """
    if cfg is None:
        cfg = get_settings()

    export_dir = Path(cfg.export_dir)
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg_fail(f"Cannot create export directory: {exc}")
        return None

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = f"{label or 'nexagen_export'}_{ts}"

    formats = ["json", "csv", "markdown"] if fmt == "all" else [fmt]
    primary: Optional[str] = None

    for f in formats:
        try:
            path = _write_export(data, export_dir / f"{file_stem}.{_fmt_ext(f)}", f)
            if path and not primary:
                primary = str(path)
            print_export_summary(
                path=str(path) if path else "—",
                fmt=f.upper(),
                n_records=_count_records(data),
            )
        except Exception as exc:
            msg_fail(f"Export to {f.upper()} failed: {exc}")

    return primary


def _fmt_ext(fmt: str) -> str:
    return {"json": "json", "csv": "csv", "markdown": "md"}.get(fmt, fmt)


def _count_records(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict) and "names" in data:
        return len(data["names"])
    return 1


def _to_serialisable(obj: Any) -> Any:
    """Recursively convert dataclasses and custom types to JSON-safe dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_serialisable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_serialisable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _write_export(data: Any, path: Path, fmt: str) -> Optional[Path]:
    """Write data to a file in the requested format."""

    # Normalise data to a list of dicts
    if isinstance(data, list):
        rows = [_to_serialisable(item) for item in data]
    elif isinstance(data, dict):
        rows = [_to_serialisable(data)]
    else:
        rows = [{"value": str(data)}]

    if fmt == "json":
        payload = {
            "nexagen_export": True,
            "version": "1.0.0",
            "author": "CEX-Nexagen",
            "exported_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": rows,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    elif fmt == "csv":
        if not rows:
            return None
        keys = list(rows[0].keys()) if isinstance(rows[0], dict) else ["value"]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                if isinstance(row, dict):
                    writer.writerow({k: str(v) for k, v in row.items()})

    elif fmt == "markdown":
        lines: list[str] = [
            "# NEXAGEN Export\n",
            f"**Author:** CEX-Nexagen  ·  **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  "
            f"·  **Records:** {len(rows)}\n",
            "",
        ]
        for i, row in enumerate(rows, 1):
            if isinstance(row, dict):
                name = row.get("name", f"Result {i}")
                score = row.get("score", "")
                tier  = row.get("tier",  "")
                lines.append(f"## {i}. {str(name).capitalize()}")
                if score:
                    lines.append(f"**Score:** {score}  **Tier:** {tier}")
                for k, v in row.items():
                    if k not in ("name", "score", "tier") and v:
                        lines.append(f"- **{k}:** {v}")
                lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    return path
