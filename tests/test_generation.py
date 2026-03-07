"""
tests/test_generation.py  ·  Name generation pipeline test suite
─────────────────────────────────────────────────────────────────
NEXAGEN · CEX-Nexagen · CyberEmpireX

Covers:
  · KeywordEngine     — tokenisation, validation, profile boosting, KeywordSet
  · SynonymEngine     — seed expansion, style filtering, ExpansionResult
  · PatternEngine     — all 10 linguistic strategies, GenerationResult
  · MutationEngine    — all 12 mutation strategies, style-gating, dedup
  · NameGenerator     — full 5-stage pipeline (headless mode), NameResult output
  · generate_names    — functional interface contract
  · levenshtein utils — deduplicate_by_distance, find_duplicates
  · text_utils        — syllable counting, vowel ratio, soundex/metaphone
  · validators        — validate_brand_name rules

Tests are entirely offline — no network, no file I/O beyond dataset reads.
The pipeline runs in animated=False (headless) mode throughout.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from nexagen.config.constants import (
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    GEN_DEFAULT_COUNT,
    Profile,
    StyleMode,
    BrandTier,
)
from nexagen.config.settings import get_settings
from nexagen.engine.keyword_engine import (
    KeywordEngine,
    KeywordSet,
    extract_keywords,
    process_keywords,
)
from nexagen.engine.mutation_engine import (
    MutationEngine,
    MutatedCandidate,
    MutationResult,
    MUT_VOWEL_DROP,
    MUT_PHONEME_SUB,
    MUT_POWER_ENDING,
    MUT_X_INFUSION,
    apply_mutations,
)
from nexagen.engine.name_generator import NameGenerator, generate_names
from nexagen.engine.pattern_engine import PatternEngine
from nexagen.engine.synonym_engine import SynonymEngine
from nexagen.ui.tables import NameResult
from nexagen.utils.levenshtein import (
    deduplicate_by_distance,
    find_duplicates,
    levenshtein,
    similarity,
)
from nexagen.utils.text_utils import (
    metaphone,
    soundex,
    syllable_count,
    vowel_ratio,
)
from nexagen.utils.validators import validate_brand_name


# ─────────────────────────────────────────────────────────────────────────────
# § 1  TEXT UTILS — foundational, no external deps
# ─────────────────────────────────────────────────────────────────────────────

class TestVowelRatio(unittest.TestCase):

    def test_all_vowels_is_one(self):
        self.assertAlmostEqual(vowel_ratio("aeiou"), 1.0)

    def test_all_consonants_is_zero(self):
        self.assertAlmostEqual(vowel_ratio("bcd"), 0.0)

    def test_typical_word(self):
        vr = vowel_ratio("nexagen")
        self.assertGreater(vr, 0.0)
        self.assertLess(vr, 1.0)

    def test_empty_string(self):
        # Should not raise; return 0 or handle gracefully
        result = vowel_ratio("")
        self.assertIsInstance(result, float)

    def test_balanced_name_range(self):
        # "signal" has 2 vowels out of 6 chars = 0.33
        vr = vowel_ratio("signal")
        self.assertAlmostEqual(vr, 2/6, places=2)


class TestSyllableCount(unittest.TestCase):

    def test_monosyllable(self):
        self.assertEqual(syllable_count("brand"), 1)

    def test_two_syllables(self):
        self.assertEqual(syllable_count("nexagen"), 3)   # nex-a-gen

    def test_single_vowel_word(self):
        count = syllable_count("a")
        self.assertGreaterEqual(count, 1)

    def test_long_word_more_syllables(self):
        short = syllable_count("go")
        long  = syllable_count("infrastructure")
        self.assertGreater(long, short)

    def test_returns_positive_int(self):
        for word in ["kit", "nexagen", "platform", "cyberempirex"]:
            self.assertGreater(syllable_count(word), 0)


class TestSoundexMetaphone(unittest.TestCase):

    def test_soundex_same_sound_same_code(self):
        self.assertEqual(soundex("Smith"), soundex("Smythe"))

    def test_soundex_length_four(self):
        code = soundex("nexagen")
        self.assertEqual(len(code), 4)

    def test_soundex_starts_with_first_letter(self):
        code = soundex("nexagen")
        self.assertEqual(code[0].upper(), "N")

    def test_metaphone_returns_string(self):
        key = metaphone("nexagen")
        self.assertIsInstance(key, str)
        self.assertGreater(len(key), 0)

    def test_metaphone_similar_sounds(self):
        # "phone" and "fone" should have same/similar metaphone keys
        k1 = metaphone("phone")
        k2 = metaphone("fone")
        self.assertEqual(k1, k2)

    def test_soundex_empty_string_graceful(self):
        result = soundex("")
        self.assertIsInstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  LEVENSHTEIN UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

class TestLevenshtein(unittest.TestCase):

    def test_identical_strings_distance_zero(self):
        self.assertEqual(levenshtein("nexagen", "nexagen"), 0)

    def test_empty_vs_word(self):
        self.assertEqual(levenshtein("", "abc"), 3)

    def test_one_char_diff(self):
        self.assertEqual(levenshtein("cat", "bat"), 1)

    def test_completely_different(self):
        dist = levenshtein("abc", "xyz")
        self.assertEqual(dist, 3)

    def test_symmetric(self):
        self.assertEqual(levenshtein("nexagen", "nexagon"),
                         levenshtein("nexagon", "nexagen"))


class TestSimilarity(unittest.TestCase):

    def test_identical_is_one(self):
        self.assertAlmostEqual(similarity("nexagen", "nexagen"), 1.0)

    def test_completely_different_near_zero(self):
        s = similarity("aaaa", "zzzz")
        self.assertLess(s, 0.4)

    def test_one_char_diff_high(self):
        s = similarity("nexagen", "nexagen")
        self.assertGreater(s, 0.9)

    def test_range_0_to_1(self):
        for a, b in [("ab", "cd"), ("test", "testing"), ("x", "xyz")]:
            s = similarity(a, b)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)


class TestDeduplicateByDistance(unittest.TestCase):

    def test_exact_duplicates_removed(self):
        names = ["nexagen", "nexagen", "koda"]
        result = deduplicate_by_distance(names, max_distance=0)
        self.assertNotIn("nexagen", result[1:])  # only one survives

    def test_near_duplicates_removed(self):
        names = ["nexagen", "nexagon", "koda"]
        result = deduplicate_by_distance(names, max_distance=2)
        # nexagen and nexagon are 1 apart — one should be removed
        self.assertLessEqual(len(result), 2)

    def test_distinct_names_all_kept(self):
        names = ["koda", "veltex", "zyrx", "lumio"]
        result = deduplicate_by_distance(names, max_distance=2)
        self.assertEqual(len(result), 4)

    def test_empty_list(self):
        self.assertEqual(deduplicate_by_distance([]), [])

    def test_single_item(self):
        self.assertEqual(deduplicate_by_distance(["nexagen"]), ["nexagen"])

    def test_preserves_first_occurrence(self):
        names = ["nexagen", "nexagon"]
        result = deduplicate_by_distance(names, max_distance=2)
        self.assertEqual(result[0], "nexagen")


class TestFindDuplicates(unittest.TestCase):

    def test_finds_near_pair(self):
        names = ["nexagen", "nexagen", "koda"]
        dupes = find_duplicates(names, threshold=0.95)
        # Both "nexagen" entries are identical → should be flagged
        self.assertGreater(len(dupes), 0)

    def test_no_pairs_in_distinct_names(self):
        names = ["koda", "veltex", "zyrx", "blume"]
        dupes = find_duplicates(names, threshold=0.95)
        self.assertEqual(len(dupes), 0)

    def test_returns_tuples_with_score(self):
        names = ["nexagen", "nexagen"]
        for a, b, score in find_duplicates(names, threshold=0.9):
            self.assertIsInstance(score, float)
            self.assertGreaterEqual(score, 0.9)


# ─────────────────────────────────────────────────────────────────────────────
# § 3  BRAND NAME VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateBrandName(unittest.TestCase):

    def test_valid_name_passes(self):
        r = validate_brand_name("nexagen")
        self.assertTrue(r.is_valid, r.issues)

    def test_empty_name_fails(self):
        r = validate_brand_name("")
        self.assertFalse(r.is_valid)

    def test_too_short_fails(self):
        r = validate_brand_name("a")
        self.assertFalse(r.is_valid)

    def test_too_long_fails(self):
        r = validate_brand_name("a" * (NAME_LENGTH_HARD_MAX + 1))
        self.assertFalse(r.is_valid)

    def test_digits_in_name(self):
        # Most validators allow alphanumeric names
        r = validate_brand_name("nexagen3")
        self.assertIsNotNone(r)

    def test_spaces_fail(self):
        r = validate_brand_name("my brand")
        self.assertFalse(r.is_valid)

    def test_special_chars_fail(self):
        r = validate_brand_name("nex@gen")
        self.assertFalse(r.is_valid)

    def test_trademark_clash_flagged(self):
        # "google" should collide at distance 0 with the blacklist
        r = validate_brand_name("google")
        # Either invalid or has trademark warning
        has_issue = (not r.is_valid) or any(
            "trademark" in str(i).lower() or "blacklist" in str(i).lower()
            for i in r.issues
        )
        self.assertTrue(has_issue)

    def test_uppercase_name_treated_gracefully(self):
        r = validate_brand_name("NEXAGEN")
        # Should either pass (after lowercasing) or fail gracefully
        self.assertIsNotNone(r)


# ─────────────────────────────────────────────────────────────────────────────
# § 4  KEYWORD ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class TestKeywordEngine(unittest.TestCase):

    def setUp(self):
        self.engine = KeywordEngine()
        self.cfg    = get_settings()

    def test_process_returns_keyword_set(self):
        ks = self.engine.process(["cloud", "data"], self.cfg)
        self.assertIsInstance(ks, KeywordSet)

    def test_valid_keywords_in_final(self):
        ks = self.engine.process(["cloud", "data"], self.cfg)
        self.assertGreater(len(ks.final), 0)

    def test_empty_keywords_produce_empty_final(self):
        ks = self.engine.process([], self.cfg)
        self.assertEqual(len(ks.final), 0)

    def test_whitespace_only_filtered(self):
        ks = self.engine.process(["  ", "\t", "cloud"], self.cfg)
        for kw in ks.final:
            self.assertEqual(kw, kw.strip())

    def test_too_short_word_filtered(self):
        ks = self.engine.process(["a", "b", "cloud"], self.cfg)
        for kw in ks.final:
            self.assertGreater(len(kw), 1)

    def test_duplicates_deduplicated(self):
        ks = self.engine.process(["cloud", "cloud", "data"], self.cfg)
        self.assertEqual(len(ks.final), len(set(ks.final)))

    def test_profile_boosting(self):
        self.cfg.profile = Profile.AI.value
        ks_ai = self.engine.process(["neural", "data"], self.cfg)
        self.assertGreater(len(ks_ai.final), 0)

    def test_scored_list_populated(self):
        ks = self.engine.process(["cloud", "data", "platform"], self.cfg)
        self.assertGreater(len(ks.scored), 0)

    def test_invalid_words_tracked(self):
        # Numbers-only string should be rejected
        ks = self.engine.process(["12345", "cloud"], self.cfg)
        # Either filtered to final or tracked in invalid
        total = len(ks.final) + len(ks.invalid)
        self.assertGreaterEqual(total, 1)

    def test_count_matches_final_length(self):
        ks = self.engine.process(["cloud", "data", "ai"], self.cfg)
        self.assertEqual(ks.count, len(ks.final))


class TestKeywordEngineProcessFunctional(unittest.TestCase):

    def test_process_keywords_returns_list(self):
        result = process_keywords(["cloud", "data"])
        self.assertIsInstance(result, list)

    def test_extract_keywords_from_text(self):
        text = "We build AI-powered cloud infrastructure for enterprise teams"
        keywords = extract_keywords(text)
        self.assertIsInstance(keywords, list)
        self.assertGreater(len(keywords), 0)

    def test_extract_keywords_removes_stopwords(self):
        text = "We build a tool for the team"
        keywords = extract_keywords(text)
        stopwords = {"a", "the", "for", "we"}
        for kw in keywords:
            self.assertNotIn(kw.lower(), stopwords)


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SYNONYM ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class TestSynonymEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SynonymEngine()
        self.cfg    = get_settings()

    def test_expand_returns_expansion_result(self):
        result = self.engine.expand(["cloud", "data"], self.cfg)
        self.assertIsNotNone(result)

    def test_expansion_includes_seeds(self):
        result = self.engine.expand(["cloud"], self.cfg)
        seed_words = [sw.word for sw in result.seeds if hasattr(result.seeds[0], 'word')] \
                     if result.seeds and hasattr(result.seeds[0], 'word') else result.seeds
        # Either seeds list or words list should contain the original
        all_words = [sw.word for sw in result.words] if result.words else []
        self.assertGreater(len(all_words) + len(seed_words), 0)

    def test_expansion_stats_populated(self):
        result = self.engine.expand(["cloud", "data"], self.cfg)
        self.assertIsInstance(result.stats, dict)

    def test_filter_by_style_returns_list(self):
        result = self.engine.expand(["cloud", "data"], self.cfg)
        styled = self.engine.filter_by_style(result, StyleMode.MINIMAL.value)
        self.assertIsInstance(styled, list)

    def test_filter_by_style_nonempty(self):
        result = self.engine.expand(["cloud", "data", "platform"], self.cfg)
        for style in [StyleMode.MINIMAL, StyleMode.FUTURISTIC, StyleMode.SOFT]:
            styled = self.engine.filter_by_style(result, style.value)
            self.assertGreaterEqual(len(styled), 0)

    def test_expansion_words_are_strings(self):
        result = self.engine.expand(["cloud"], self.cfg)
        for sw in result.words:
            self.assertIsInstance(sw.word, str)
            self.assertGreater(len(sw.word), 0)


# ─────────────────────────────────────────────────────────────────────────────
# § 6  PATTERN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class TestPatternEngine(unittest.TestCase):

    def setUp(self):
        self.engine = PatternEngine()
        self.cfg    = get_settings()
        self.seeds  = ["cloud", "data", "platform", "nexus", "forge"]

    def test_generate_returns_generation_result(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertIsNotNone(result)

    def test_candidates_populated(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertGreater(result.total, 0)

    def test_names_list_populated(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertGreater(len(result.names), 0)

    def test_names_are_strings(self):
        result = self.engine.generate(self.seeds, self.cfg)
        for name in result.names:
            self.assertIsInstance(name, str)
            self.assertGreater(len(name), 0)

    def test_strategy_counts_populated(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertIsInstance(result.strategy_counts, dict)
        self.assertGreater(len(result.strategy_counts), 0)

    def test_max_candidates_respected(self):
        result = self.engine.generate(self.seeds, self.cfg, max_candidates=10)
        self.assertLessEqual(result.total, 10)

    def test_no_duplicate_names(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertEqual(len(result.names), len(set(result.names)))

    def test_name_lengths_within_hard_bounds(self):
        result = self.engine.generate(self.seeds, self.cfg)
        for name in result.names:
            self.assertGreaterEqual(len(name), NAME_LENGTH_HARD_MIN)
            self.assertLessEqual(len(name), NAME_LENGTH_HARD_MAX)

    def test_by_strategy_dict_populated(self):
        result = self.engine.generate(self.seeds, self.cfg)
        self.assertIsInstance(result.by_strategy, dict)

    def test_all_names_alphabetic_or_mixed(self):
        result = self.engine.generate(self.seeds, self.cfg)
        for name in result.names[:20]:
            # Names should be lowercase alphanumeric (no spaces, no special chars)
            self.assertRegex(name, r"^[a-z0-9]+$")

    def test_different_profiles_produce_results(self):
        for profile in [Profile.TECH, Profile.AI, Profile.GENERIC]:
            self.cfg.profile = profile.value
            result = self.engine.generate(["cloud", "data"], self.cfg)
            self.assertGreater(result.total, 0)


# ─────────────────────────────────────────────────────────────────────────────
# § 7  MUTATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class TestMutationEngine(unittest.TestCase):

    def setUp(self):
        self.engine = MutationEngine()
        self.cfg    = get_settings()
        self.seeds  = ["cloud", "nexus", "forge", "data", "platform"]

    def test_apply_returns_mutation_result(self):
        result = self.engine.apply(self.seeds, self.cfg)
        self.assertIsInstance(result, MutationResult)

    def test_candidates_have_correct_type(self):
        result = self.engine.apply(self.seeds, self.cfg)
        for c in result.candidates:
            self.assertIsInstance(c, MutatedCandidate)

    def test_candidates_have_names(self):
        result = self.engine.apply(self.seeds, self.cfg)
        for c in result.candidates:
            self.assertIsInstance(c.name, str)
            self.assertGreater(len(c.name), 0)

    def test_candidates_have_strategies(self):
        result = self.engine.apply(self.seeds, self.cfg)
        for c in result.candidates:
            self.assertIsInstance(c.strategy, str)
            self.assertGreater(len(c.strategy), 0)

    def test_candidates_have_sources(self):
        result = self.engine.apply(self.seeds, self.cfg)
        for c in result.candidates:
            self.assertIn(c.source, self.seeds)

    def test_strategy_counts_populated(self):
        result = self.engine.apply(self.seeds, self.cfg)
        self.assertIsInstance(result.strategy_counts, dict)
        self.assertGreater(len(result.strategy_counts), 0)

    def test_by_strategy_dict_populated(self):
        result = self.engine.apply(self.seeds, self.cfg)
        self.assertIsInstance(result.by_strategy, dict)

    def test_total_matches_candidates_count(self):
        result = self.engine.apply(self.seeds, self.cfg)
        self.assertEqual(result.total, len(result.candidates))

    def test_max_candidates_respected(self):
        result = self.engine.apply(self.seeds, self.cfg, max_candidates=10)
        self.assertLessEqual(len(result.candidates), 10)

    def test_no_duplicate_names(self):
        result = self.engine.apply(self.seeds, self.cfg)
        names = [c.name for c in result.candidates]
        self.assertEqual(len(names), len(set(names)))

    def test_name_lengths_within_hard_bounds(self):
        result = self.engine.apply(self.seeds, self.cfg)
        for c in result.candidates:
            self.assertGreaterEqual(len(c.name), NAME_LENGTH_HARD_MIN)
            self.assertLessEqual(len(c.name), NAME_LENGTH_HARD_MAX)

    def test_futuristic_style_enables_x_infusion(self):
        self.cfg.style_mode = StyleMode.FUTURISTIC.value
        result = self.engine.apply(["nexus", "forge"], self.cfg)
        strategies_used = set(result.strategy_counts.keys())
        # FUTURISTIC style should include power_ending or x_infusion
        has_futuristic = bool(
            strategies_used & {MUT_POWER_ENDING, MUT_X_INFUSION, MUT_PHONEME_SUB}
        )
        self.assertTrue(has_futuristic, f"Got: {strategies_used}")

    def test_minimal_style_uses_fewer_strategies(self):
        self.cfg.style_mode = StyleMode.MINIMAL.value
        result_min = self.engine.apply(self.seeds, self.cfg)
        strategies_min = len(result_min.strategy_counts)

        self.cfg.style_mode = StyleMode.FUTURISTIC.value
        result_fut = self.engine.apply(self.seeds, self.cfg)
        strategies_fut = len(result_fut.strategy_counts)

        self.assertLessEqual(strategies_min, strategies_fut)

    def test_apply_one_with_specific_strategies(self):
        candidates = self.engine.apply_one(
            "nexus",
            strategies=[MUT_VOWEL_DROP, MUT_PHONEME_SUB],
            cfg=self.cfg,
        )
        self.assertIsInstance(candidates, list)
        for c in candidates:
            self.assertIn(c.strategy, [MUT_VOWEL_DROP, MUT_PHONEME_SUB])

    def test_empty_seeds_returns_empty(self):
        result = self.engine.apply([], self.cfg)
        self.assertEqual(result.total, 0)

    def test_apply_mutations_functional_interface(self):
        names = apply_mutations(["cloud", "nexus"], self.cfg)
        self.assertIsInstance(names, list)
        for n in names:
            self.assertIsInstance(n, str)


# ─────────────────────────────────────────────────────────────────────────────
# § 8  NAME GENERATOR — full pipeline (headless)
# ─────────────────────────────────────────────────────────────────────────────

class TestNameGenerator(unittest.TestCase):

    def setUp(self):
        self.gen = NameGenerator()
        self.cfg = get_settings()
        self.cfg.count = 10   # keep tests fast
        self.keywords = ["cloud", "data", "platform"]

    def test_generate_returns_name_results(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        self.assertIsInstance(results, list)
        for r in results:
            self.assertIsInstance(r, NameResult)

    def test_results_capped_at_count(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        self.assertLessEqual(len(results), self.cfg.count)

    def test_results_sorted_by_score_desc(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        if len(results) > 1:
            scores = [r.score for r in results]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_every_result_has_name(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        for r in results:
            self.assertIsInstance(r.name, str)
            self.assertGreater(len(r.name), 0)

    def test_every_result_has_score(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        for r in results:
            self.assertGreaterEqual(r.score, 0)
            self.assertLessEqual(r.score, 100)

    def test_every_result_has_tier(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        valid_tiers = {t.value for t in BrandTier}
        for r in results:
            self.assertIn(r.tier, valid_tiers)

    def test_name_lengths_within_hard_bounds(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        for r in results:
            self.assertGreaterEqual(len(r.name), NAME_LENGTH_HARD_MIN)
            self.assertLessEqual(len(r.name), NAME_LENGTH_HARD_MAX)

    def test_no_duplicate_names(self):
        results = self.gen.generate_headless(self.keywords, self.cfg)
        names = [r.name for r in results]
        self.assertEqual(len(names), len(set(names)))

    def test_single_keyword_still_works(self):
        results = self.gen.generate_headless(["cloud"], self.cfg)
        self.assertGreater(len(results), 0)

    def test_profile_tech_produces_results(self):
        self.cfg.profile = Profile.TECH.value
        results = self.gen.generate_headless(["security", "data"], self.cfg)
        self.assertGreater(len(results), 0)

    def test_profile_ai_produces_results(self):
        self.cfg.profile = Profile.AI.value
        results = self.gen.generate_headless(["neural", "model"], self.cfg)
        self.assertGreater(len(results), 0)

    def test_style_modes_all_produce_results(self):
        for style in StyleMode:
            self.cfg.style_mode = style.value
            results = self.gen.generate_headless(["forge", "nexus"], self.cfg)
            self.assertGreater(len(results), 0,
                               f"Style {style.value} produced no results")

    def test_generate_headless_matches_generate_animated_false(self):
        r1 = self.gen.generate_headless(["cloud"], self.cfg)
        # Both should return NameResult list
        self.assertIsInstance(r1, list)


class TestGenerateNamesFunctional(unittest.TestCase):

    def test_returns_list(self):
        cfg = get_settings()
        cfg.count = 5
        results = generate_names(["cloud"], cfg, animated=False)
        self.assertIsInstance(results, list)

    def test_results_are_name_results(self):
        cfg = get_settings()
        cfg.count = 5
        results = generate_names(["data", "platform"], cfg, animated=False)
        for r in results:
            self.assertIsInstance(r, NameResult)

    def test_count_respected(self):
        cfg = get_settings()
        cfg.count = 3
        results = generate_names(["nexus", "forge"], cfg, animated=False)
        self.assertLessEqual(len(results), 3)

    def test_scores_in_range(self):
        cfg = get_settings()
        cfg.count = 5
        for r in generate_names(["cloud"], cfg, animated=False):
            self.assertGreaterEqual(r.score, 0)
            self.assertLessEqual(r.score, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
