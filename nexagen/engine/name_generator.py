"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  engine/name_generator.py  ·  Full generation pipeline orchestrator        ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Orchestrates the complete name generation pipeline end-to-end.
This is the high-level façade that ties all engine modules together and
can be called directly from cli/commands.py or used programmatically.

Pipeline  (5 stages)
────────────────────
  Stage 1 — Keyword processing
            KeywordEngine.process()
            → clean, validate, profile-boost user keywords

  Stage 2 — Synonym expansion
            SynonymEngine.expand() + filter_by_style()
            → rich scored seed pool

  Stage 3 — Pattern generation
            PatternEngine.generate()
            → 10 linguistic strategies → Candidate pool

  Stage 4 — Mutation generation
            MutationEngine.apply()
            → 12 character-level mutations → extra variants

  Stage 5 — Score, dedup, rank
            BrandScorer.score_batch()
            levenshtein.deduplicate_by_distance()
            → sorted list[NameResult]

Relationship to commands.py
────────────────────────────
  cli/commands.cmd_generate_names() calls NameGenerator.generate() when
  the engine modules are available.  If they are not yet built it falls
  back to its own inline implementation.  The return type is identical:
  list[NameResult].

Public API
──────────
  NameGenerator.generate(keywords, cfg, animated)   → list[NameResult]
  NameGenerator.generate_headless(keywords, cfg)    → list[NameResult]
  generate_names(keywords, cfg)                     → list[NameResult]

Design notes
────────────
  • All UI output goes through ui/ — this module never calls print().
  • animated=False suppresses all Rich output (CI / headless use).
  • Keywords flow through KeywordEngine first so raw user strings work.
  • MutationEngine candidates are merged with PatternEngine candidates
    before scoring so the scorer sees the full diversity of the pool.
  • BrandScorer is instantiated once per run to reuse cached datasets.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from ..analysis.brand_score import BrandScorer, tier_colour_for_score
from ..config.constants import (
    C_ACCENT,
    C_GOLD,
    C_GREEN,
    C_PURPLE,
    GEN_DEDUP_THRESHOLD,
    GEN_MAX_CANDIDATES,
    GEN_MAX_COUNT,
    SCORE_PREMIUM,
    SCORE_STRONG,
)
from ..config.settings import Settings, get_settings
from ..engine.keyword_engine import KeywordEngine
from ..engine.mutation_engine import MutationEngine
from ..engine.pattern_engine import PatternEngine
from ..engine.synonym_engine import SynonymEngine
from ..ui.tables import NameResult
from ..utils.levenshtein import deduplicate_by_distance

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  PIPELINE PROGRESS HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _step(step: int, total: int, text: str) -> None:
    """Print a numbered pipeline step — no-op if banner import fails."""
    try:
        from ..ui.banner import msg_step
        msg_step(step, total, text)
    except Exception:
        pass


def _ok(text: str) -> None:
    try:
        from ..ui.banner import msg_ok
        msg_ok(text)
    except Exception:
        pass


def _info(text: str) -> None:
    try:
        from ..ui.banner import msg_info
        msg_info(text)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# § 2  NAME GENERATOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class NameGenerator:
    """
    Full end-to-end brand name generation pipeline.

    Usage::

        from nexagen.engine.name_generator import NameGenerator
        gen = NameGenerator()
        results = gen.generate(["cloud", "data"], cfg=settings, animated=True)

    Animated mode (default) streams Rich output at each pipeline stage.
    Headless mode (animated=False or generate_headless()) produces no output.
    """

    def __init__(self) -> None:
        self._kw_engine  = KeywordEngine()
        self._syn_engine = SynonymEngine()
        self._pat_engine = PatternEngine()
        self._mut_engine = MutationEngine()

    # ── Public entry point ────────────────────────────────────────────────────

    def generate(
        self,
        keywords:  Sequence[str],
        cfg:       Optional[Settings] = None,
        animated:  bool               = True,
    ) -> list[NameResult]:
        """
        Run the full 5-stage generation pipeline.

        Args:
            keywords:  Raw user-supplied keywords (strings, any format).
            cfg:       Active Settings — controls profile, style, count,
                       length range, score weights, and feature flags.
            animated:  Show Rich progress output at each stage (True for
                       interactive use, False for CI / API callers).

        Returns:
            List of :class:`NameResult` objects sorted by composite score
            descending, capped at min(cfg.count, GEN_MAX_COUNT).
        """
        if cfg is None:
            cfg = get_settings()

        target      = min(cfg.count, GEN_MAX_COUNT)
        total_steps = 5

        # ── Stage 1 : Keyword processing ──────────────────────────────────────
        if animated:
            _step(1, total_steps, "Processing and validating keywords…")

        kw_set = self._kw_engine.process(keywords, cfg)

        if animated:
            if kw_set.warnings:
                from ..ui.banner import msg_warn
                for w in kw_set.warnings:
                    msg_warn(w)
            _ok(
                f"  {len(kw_set.final)} keywords ready  "
                f"({len(kw_set.invalid)} invalid ignored)"
            )

        if not kw_set.final:
            log.warning("No valid keywords after processing; using raw input.")
            kw_set_final = [str(k).strip().lower() for k in keywords if k]
        else:
            kw_set_final = kw_set.final

        # ── Stage 2 : Synonym expansion ───────────────────────────────────────
        if animated:
            _step(2, total_steps, "Expanding via synonym graph and profile vocabulary…")

        expansion = self._syn_engine.expand(
            kw_set_final, cfg,
            depth=1,
            max_words=80,
            phonetic=True,
        )
        styled_seeds = self._syn_engine.filter_by_style(expansion, cfg.style_mode)
        seeds        = [sw.word for sw in styled_seeds[:70]]

        if animated:
            _ok(
                f"  Expanded to {len(seeds)} seeds  "
                f"(synonyms: {expansion.stats.get('synonym', 0)}, "
                f"vocab: {expansion.stats.get('profile', 0)})"
            )

        # ── Stage 3 : Pattern generation ──────────────────────────────────────
        if animated:
            _step(3, total_steps, "Generating candidates via pattern strategies…")

        pat_result  = self._pat_engine.generate(seeds, cfg, max_candidates=GEN_MAX_CANDIDATES)
        pat_names   = pat_result.names

        if animated:
            counts_str = "  ".join(
                f"{s}:{n}" for s, n in pat_result.strategy_counts.items()
            )
            _ok(f"  {pat_result.total} pattern candidates  [{counts_str}]")

        # ── Stage 4 : Mutation generation ─────────────────────────────────────
        if animated:
            _step(4, total_steps, "Applying linguistic mutations…")

        # Feed the first 30 seeds to MutationEngine (character-level work)
        mut_result = self._mut_engine.apply(seeds[:30], cfg, max_candidates=200)
        mut_names  = mut_result.names

        if animated:
            _ok(
                f"  {mut_result.total} mutation variants  "
                f"(strategies: {len(mut_result.strategy_counts)})"
            )

        # ── Merge + Deduplicate ────────────────────────────────────────────────
        combined  = list(dict.fromkeys(pat_names + mut_names))   # preserve order, dedup
        deduped   = deduplicate_by_distance(combined, max_distance=GEN_DEDUP_THRESHOLD)

        log.debug(
            "Pool: %d pattern + %d mutation = %d combined → %d after dedup",
            len(pat_names), len(mut_names), len(combined), len(deduped),
        )

        # ── Stage 5 : Score, rank, trim ───────────────────────────────────────
        if animated:
            _step(5, total_steps, f"Scoring {len(deduped)} unique candidates…")

        scorer  = BrandScorer(cfg)
        results = self._score_all(deduped, scorer, cfg, animated=animated)

        results.sort(key=lambda r: -r.score)
        final = results[:target]

        if animated:
            best_score = final[0].score if final else 0
            _ok(
                f"  Selected top {len(final)} names  —  "
                f"best: {best_score}/100  tier: "
                + (scorer.score_name(final[0].name).tier if final else "—")
            )
            from ..ui.banner import console
            console.print()

        # ── Display ───────────────────────────────────────────────────────────
        if animated and final:
            self._display_results(final)

        return final

    # ── Headless convenience ──────────────────────────────────────────────────

    def generate_headless(
        self,
        keywords: Sequence[str],
        cfg:      Optional[Settings] = None,
    ) -> list[NameResult]:
        """
        Run the full pipeline with no UI output.

        Equivalent to generate(keywords, cfg, animated=False).

        Args:
            keywords: User-supplied keywords.
            cfg:      Active Settings.

        Returns:
            Sorted list[NameResult].
        """
        return self.generate(keywords, cfg, animated=False)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _score_all(
        self,
        names:    list[str],
        scorer:   BrandScorer,
        cfg:      Settings,
        *,
        animated: bool = False,
    ) -> list[NameResult]:
        """
        Score every name in the pool and convert to NameResult.

        Uses Rich progress bar in animated mode.
        """
        results: list[NameResult] = []
        pool:    list[str]        = []

        if animated:
            try:
                from ..ui.progress import track
                iterable = track(
                    names, "Scoring candidates",
                    total=len(names), colour=C_PURPLE,
                )
            except Exception:
                iterable = names
        else:
            iterable = names

        for name in iterable:
            try:
                sr = scorer.score_name(name, pool=pool)
                nr = scorer.to_name_result(sr)
                results.append(nr)
                pool.append(name)
            except Exception as exc:
                log.debug("Scoring failed for %r: %s", name, exc)

        return results

    def _display_results(self, final: list[NameResult]) -> None:
        """Stream the animated name reveal and render the results table."""
        try:
            from ..ui.animations import reveal_names
            from ..ui.tables import print_comparison_table, print_names_table

            reveal_names(
                names   = [r.name.capitalize() for r in final[:10]],
                scores  = [r.score for r in final[:10]],
                colours = [tier_colour_for_score(r.score) for r in final[:10]],
            )
            print_names_table(final, show_domains=False)
            if len(final) > 1:
                print_comparison_table(final, top_n=5)
        except Exception as exc:
            log.debug("Display error (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  SIMPLE FUNCTIONAL INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def generate_names(
    keywords:  Sequence[str],
    cfg:       Optional[Settings] = None,
    *,
    animated:  bool = False,
) -> list[NameResult]:
    """
    Generate brand name candidates and return sorted list[NameResult].

    Simple functional interface for callers that don't need the full
    NameGenerator object.

    Args:
        keywords:  User-supplied keyword strings.
        cfg:       Active Settings.  get_settings() used if None.
        animated:  Enable Rich animated output.  Default False for
                   programmatic use; set True in interactive CLI.

    Returns:
        Sorted list[NameResult], best score first,
        capped at cfg.count (default 20).

    Example::

        from nexagen.engine.name_generator import generate_names
        names = generate_names(["cloud", "agent"], animated=False)
        for r in names:
            print(r.name, r.score, r.tier)
    """
    gen = NameGenerator()
    return gen.generate(keywords, cfg, animated=animated)
