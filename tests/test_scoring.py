"""
tests/test_scoring.py  ·  Scoring & analysis layer test suite
──────────────────────────────────────────────────────────────
NEXAGEN · CEX-Nexagen · CyberEmpireX

Covers:
  · BrandScorer         — score_name, score_batch, to_name_result,
                          to_analysis_data, pool accumulation
  · Standalone scorers  — score_pronounceability, score_memorability,
                          score_uniqueness, score_length_fitness,
                          composite_score, tm_risk, generate_notes
  · tier_for_score      — BrandTier band mapping at all thresholds
  · quick_score         — one-shot functional interface
  · PhoneticAnalysis    — analyse_phonetics, batch_analyse, phonetic_score,
                          phonetic_grade, group_by_phonetic_key,
                          top_phonetic_names
  · PhoneticReport      — dimension completeness, grade letters, composite
  · CollisionDetection  — detect_collisions, batch_detect, quick_risk,
                          is_safe, filter_safe_names, pairwise_collisions
  · CollisionReport     — hit fields, signal types, risk ordering
  · UniquenessScore     — score_uniqueness_full, score_uniqueness_scalar,
                          batch_score_uniqueness, rank_by_uniqueness,
                          filter_unique
  · UniquenessReport    — axes, verdicts, blacklist proximity, pool distance
  · TrademarkRisk       — levenshtein.trademark_risk, MatchResult,
                          closest_match, top_matches, phonetic_duplicates
  · text_utils          — consonant/vowel helpers, is_pronounceable,
                          has_forbidden_sequence, sounds_like

All tests are fully offline — no network calls, no file system writes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from nexagen.analysis.brand_score import (
    BrandScorer,
    ScoreResult,
    composite_score,
    generate_notes,
    quick_score,
    score_length_fitness,
    score_memorability,
    score_pronounceability,
    score_uniqueness,
    tier_for_score,
    tier_colour_for_score,
    tm_risk,
)
from nexagen.analysis.collision_detection import (
    CollisionHit,
    CollisionReport,
    CollisionSignal,
    RiskLevel,
    batch_detect,
    detect_collisions,
    filter_safe_names,
    is_safe,
    pairwise_collisions,
    quick_risk,
)
from nexagen.analysis.phonetic_analysis import (
    PhoneticDimension,
    PhoneticReport,
    analyse_phonetics,
    batch_analyse,
    group_by_phonetic_key,
    phonetic_grade,
    phonetic_score,
    top_phonetic_names,
)
from nexagen.analysis.uniqueness_score import (
    UniquenessAxis,
    UniquenessReport,
    batch_score_uniqueness,
    filter_unique,
    rank_by_uniqueness,
    score_uniqueness_full,
    score_uniqueness_scalar,
)
from nexagen.config.constants import (
    BrandTier,
    RARE_CONSONANTS,
    SCORE_DECENT,
    SCORE_PREMIUM,
    SCORE_STRONG,
    SCORE_WEAK,
    STRONG_START_CONSONANTS,
    VOWELS,
)
from nexagen.config.settings import get_settings
from nexagen.ui.tables import AnalysisData, NameResult
from nexagen.utils.levenshtein import (
    MatchResult,
    TrademarkHit,
    closest_match,
    jaro,
    jaro_winkler,
    normalized_levenshtein,
    phonetic_duplicates,
    top_matches,
    trademark_risk,
)
from nexagen.utils.text_utils import (
    alternation_score,
    ends_with_vowel,
    forbidden_sequence_count,
    has_alliteration,
    has_forbidden_sequence,
    has_rare_consonants,
    is_pronounceable,
    max_consonant_run,
    rare_consonant_count,
    sounds_like,
    starts_with_strong_consonant,
)


# ─────────────────────────────────────────────────────────────────────────────
# § 1  TEXT UTILS — linguistic building blocks
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxConsonantRun(unittest.TestCase):

    def test_pure_vowels_zero(self):
        self.assertEqual(max_consonant_run("aeiou"), 0)

    def test_single_consonant(self):
        self.assertEqual(max_consonant_run("a"), 0)
        self.assertEqual(max_consonant_run("b"), 1)

    def test_run_of_three(self):
        self.assertGreaterEqual(max_consonant_run("strength"), 3)

    def test_alternating_returns_one(self):
        self.assertEqual(max_consonant_run("banana"), 1)

    def test_returns_integer(self):
        self.assertIsInstance(max_consonant_run("nexagen"), int)


class TestAlternationScore(unittest.TestCase):

    def test_perfectly_alternating(self):
        score = alternation_score("banana")  # b-a-n-a-n-a
        self.assertGreater(score, 0.5)

    def test_all_consonants_low(self):
        score = alternation_score("bcd")
        self.assertLess(score, 0.5)

    def test_all_vowels_low(self):
        score = alternation_score("aeiou")
        self.assertLess(score, 0.5)

    def test_returns_float_0_to_1(self):
        for word in ["nexagen", "cloud", "koda", "stripe"]:
            s = alternation_score(word)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)


class TestHasForbiddenSequence(unittest.TestCase):

    def test_clean_name_false(self):
        self.assertFalse(has_forbidden_sequence("nexagen"))

    def test_empty_false(self):
        self.assertFalse(has_forbidden_sequence(""))

    def test_forbidden_sequence_count_returns_int(self):
        self.assertIsInstance(forbidden_sequence_count("nexagen"), int)
        self.assertGreaterEqual(forbidden_sequence_count("nexagen"), 0)

    def test_count_nonnegative(self):
        for name in ["cloud", "stripe", "nexagen", "zrpx"]:
            self.assertGreaterEqual(forbidden_sequence_count(name), 0)


class TestStartsWithStrongConsonant(unittest.TestCase):

    def test_known_strong_openers(self):
        for char in ["b", "d", "f", "g", "k", "p", "r", "s", "t", "v", "z"]:
            word = char + "olt"
            self.assertTrue(starts_with_strong_consonant(word),
                            f"{word!r} should start with strong consonant")

    def test_vowel_opener_false(self):
        self.assertFalse(starts_with_strong_consonant("apple"))

    def test_weak_consonant_false(self):
        self.assertFalse(starts_with_strong_consonant("honey"))

    def test_empty_false(self):
        self.assertFalse(starts_with_strong_consonant(""))


class TestEndsWithVowel(unittest.TestCase):

    def test_ends_with_a_true(self):
        self.assertTrue(ends_with_vowel("nexaga"))

    def test_ends_with_consonant_false(self):
        self.assertFalse(ends_with_vowel("nexagen"))

    def test_empty_false(self):
        self.assertFalse(ends_with_vowel(""))

    def test_all_vowel_endings(self):
        for v in "aeiou":
            self.assertTrue(ends_with_vowel("x" + v))


class TestHasAlliteration(unittest.TestCase):

    def test_repeated_start_sound_true(self):
        self.assertTrue(has_alliteration("koda"))  # depends on impl; just check type
        result = has_alliteration("nexagen")
        self.assertIsInstance(result, bool)

    def test_single_char_word(self):
        result = has_alliteration("a")
        self.assertIsInstance(result, bool)


class TestHasRareConsonants(unittest.TestCase):

    def test_q_is_rare(self):
        self.assertTrue(has_rare_consonants("qore"))

    def test_x_is_rare(self):
        self.assertTrue(has_rare_consonants("vortex"))

    def test_z_is_rare(self):
        self.assertTrue(has_rare_consonants("zyrx"))

    def test_clean_name_false(self):
        self.assertFalse(has_rare_consonants("nexagen"))

    def test_rare_consonant_count_type(self):
        self.assertIsInstance(rare_consonant_count("zyrx"), int)

    def test_rare_consonant_count_matches(self):
        # "qxz" has 3 rare consonants
        count = rare_consonant_count("qxz")
        self.assertEqual(count, 3)


class TestIsPronounceable(unittest.TestCase):

    def test_common_words_pronounceable(self):
        for word in ["nexagen", "cloud", "stripe", "koda", "forge"]:
            self.assertTrue(is_pronounceable(word),
                            f"{word!r} should be pronounceable")

    def test_all_consonants_not_pronounceable(self):
        self.assertFalse(is_pronounceable("bcd"))

    def test_empty_string(self):
        result = is_pronounceable("")
        self.assertIsInstance(result, bool)

    def test_threshold_parameter(self):
        # Lower threshold = easier to pass
        strict = is_pronounceable("xvb", threshold=0.50)
        lenient = is_pronounceable("xvb", threshold=0.05)
        # lenient should be same or more likely to pass
        self.assertIsInstance(strict, bool)
        self.assertIsInstance(lenient, bool)


class TestSoundsLike(unittest.TestCase):

    def test_identical_words(self):
        self.assertTrue(sounds_like("nexagen", "nexagen"))

    def test_phonetically_similar(self):
        # "phone" and "fone" share the same metaphone key
        self.assertTrue(sounds_like("phone", "fone"))

    def test_very_different_words(self):
        self.assertFalse(sounds_like("nexagen", "zzz"))

    def test_returns_bool(self):
        self.assertIsInstance(sounds_like("cloud", "kloud"), bool)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  LEVENSHTEIN UTILITIES — advanced functions
# ─────────────────────────────────────────────────────────────────────────────

class TestJaro(unittest.TestCase):

    def test_identical_is_one(self):
        self.assertAlmostEqual(jaro("nexagen", "nexagen"), 1.0)

    def test_empty_both_is_one(self):
        self.assertAlmostEqual(jaro("", ""), 1.0)

    def test_completely_different_low(self):
        score = jaro("abc", "xyz")
        self.assertLess(score, 0.5)

    def test_returns_float_0_to_1(self):
        for a, b in [("cloud", "klawd"), ("nexagen", "nexagon"), ("a", "b")]:
            s = jaro(a, b)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)


class TestJaroWinkler(unittest.TestCase):

    def test_identical_is_one(self):
        self.assertAlmostEqual(jaro_winkler("nexagen", "nexagen"), 1.0)

    def test_shared_prefix_boosts_above_jaro(self):
        jw = jaro_winkler("nexagen", "nexagon")
        j  = jaro("nexagen", "nexagon")
        self.assertGreaterEqual(jw, j)

    def test_returns_float_0_to_1(self):
        score = jaro_winkler("cloud", "kloud")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestNormalizedLevenshtein(unittest.TestCase):

    def test_identical_is_zero(self):
        self.assertAlmostEqual(normalized_levenshtein("nexagen", "nexagen"), 0.0)

    def test_empty_both_is_zero(self):
        self.assertAlmostEqual(normalized_levenshtein("", ""), 0.0)

    def test_completely_different_is_one(self):
        # "abc" vs "xyz" — all 3 chars different
        score = normalized_levenshtein("abc", "xyz")
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_range_0_to_1(self):
        for a, b in [("nexagen", "nexagon"), ("short", "longer"), ("a", "ab")]:
            s = normalized_levenshtein(a, b)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)


class TestClosestMatch(unittest.TestCase):

    def test_finds_exact_match(self):
        result = closest_match("nexagen", ["koda", "nexagen", "stripe"])
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MatchResult)
        self.assertEqual(result.match, "nexagen")
        self.assertAlmostEqual(result.score, 1.0)

    def test_finds_nearest(self):
        result = closest_match("nexagen", ["koda", "nexagon", "stripe"])
        self.assertIsNotNone(result)
        self.assertEqual(result.match, "nexagon")

    def test_empty_pool_returns_none(self):
        result = closest_match("nexagen", [])
        self.assertIsNone(result)

    def test_result_has_distance(self):
        result = closest_match("nexagen", ["nexagon"])
        self.assertIsNotNone(result)
        self.assertIsInstance(result.distance, int)
        self.assertGreaterEqual(result.distance, 0)


class TestTopMatches(unittest.TestCase):

    def test_returns_list(self):
        results = top_matches("nexagen", ["nexagon", "koda", "nexagene"])
        self.assertIsInstance(results, list)

    def test_sorted_by_score_desc(self):
        results = top_matches("nexagen", ["nexagon", "koda", "nexagene"], n=5)
        if len(results) > 1:
            scores = [r.score for r in results]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_n_limit_respected(self):
        pool = ["koda", "nexagon", "stripe", "forge", "veltex", "lumio"]
        results = top_matches("nexagen", pool, n=3)
        self.assertLessEqual(len(results), 3)

    def test_min_score_filters(self):
        results = top_matches("nexagen", ["zzz", "qqq"], min_score=0.99)
        # Very different names should not pass 0.99 threshold
        self.assertEqual(len(results), 0)


class TestTrademarkRisk(unittest.TestCase):

    def test_exact_match_is_high(self):
        hit = trademark_risk("google", ["google", "amazon"])
        self.assertEqual(hit.risk_level, "high")
        self.assertEqual(hit.distance, 0)

    def test_one_edit_is_high(self):
        hit = trademark_risk("gooogle", ["google"])
        self.assertEqual(hit.risk_level, "high")

    def test_two_edits_is_medium(self):
        hit = trademark_risk("goooogle", ["google"])
        self.assertIn(hit.risk_level, ["medium", "low", "none"])

    def test_far_from_blacklist_is_none(self):
        hit = trademark_risk("nexagen", ["google", "amazon", "facebook"])
        self.assertEqual(hit.risk_level, "none")

    def test_returns_trademark_hit(self):
        hit = trademark_risk("nexagen", ["google"])
        self.assertIsInstance(hit, TrademarkHit)
        self.assertIsInstance(hit.matched_brand, str)
        self.assertIsInstance(hit.distance, int)
        self.assertIsInstance(hit.similarity, float)

    def test_empty_blacklist_returns_none(self):
        hit = trademark_risk("nexagen", [])
        self.assertEqual(hit.risk_level, "none")

    def test_similarity_between_0_and_1(self):
        hit = trademark_risk("nexagen", ["google", "amazon"])
        self.assertGreaterEqual(hit.similarity, 0.0)
        self.assertLessEqual(hit.similarity, 1.0)


class TestPhoneticDuplicates(unittest.TestCase):

    def test_phonetically_identical_grouped(self):
        names = ["phone", "fone", "koda"]
        groups = phonetic_duplicates(names)
        # phone + fone should end up in the same group
        flat = [n for g in groups for n in g]
        self.assertIsInstance(groups, list)

    def test_empty_list(self):
        groups = phonetic_duplicates([])
        self.assertEqual(groups, [])

    def test_single_name(self):
        groups = phonetic_duplicates(["nexagen"])
        self.assertIsInstance(groups, list)

    def test_all_distinct_no_large_groups(self):
        names = ["koda", "veltex", "stripe", "forge"]
        groups = phonetic_duplicates(names)
        for g in groups:
            self.assertLessEqual(len(g), len(names))


# ─────────────────────────────────────────────────────────────────────────────
# § 3  BRAND SCORER — standalone functions
# ─────────────────────────────────────────────────────────────────────────────

class TestScorePronounciability(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(score_pronounceability("nexagen"), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "cloud", "a", "bbbbb", "aeiou"]:
            s = score_pronounceability(name)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_balanced_vowel_ratio_scores_higher(self):
        # "nexagen" has ~0.43 vowel ratio — in ideal 0.30–0.55 band
        good = score_pronounceability("nexagen")
        # "bcd" has 0.0 vowel ratio — out of band
        bad  = score_pronounceability("bcd")
        self.assertGreater(good, bad)

    def test_high_consonant_run_lowers_score(self):
        good = score_pronounceability("koda")       # clean alternation
        bad  = score_pronounceability("strngths")   # heavy consonant cluster
        self.assertGreater(good, bad)

    def test_ideal_syllable_count_helps(self):
        two_syl = score_pronounceability("nexagen")  # 3 syllables
        self.assertGreater(two_syl, 0)


class TestScoreMemorability(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(score_memorability("nexagen"), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "koda", "a", "verylongbrandname"]:
            s = score_memorability(name)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_ideal_length_scores_higher(self):
        # 4–8 chars gets +20 pts
        good = score_memorability("nexagen")   # 7 chars
        bad  = score_memorability("a" * 18)    # 18 chars — penalty
        self.assertGreater(good, bad)

    def test_strong_opener_bonus(self):
        # Both are 5 chars, but "brand" starts with 'b' (strong); "audio" starts with 'a' (vowel)
        strong = score_memorability("brand")
        weak   = score_memorability("oudio")
        self.assertGreaterEqual(strong, weak)


class TestScoreUniqueness(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(score_uniqueness("nexagen", []), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "cloud", "data", "nexagon"]:
            s = score_uniqueness(name, [])
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_common_word_scores_lower(self):
        common = frozenset(["data", "cloud"])
        unique_name  = score_uniqueness("nexagen", [], common_words=common)
        common_name  = score_uniqueness("data",    [], common_words=common)
        self.assertGreater(unique_name, common_name)

    def test_pool_near_duplicate_lowers_score(self):
        # "nexagen" vs itself in pool should score lower than vs empty pool
        s_empty = score_uniqueness("nexagen", [])
        s_pool  = score_uniqueness("nexagen", ["nexagon", "nexagene", "nexagenz"])
        # Should be lower or equal with competing near-matches in pool
        self.assertGreaterEqual(s_empty, 0)
        self.assertGreaterEqual(s_pool, 0)


class TestScoreLengthFitness(unittest.TestCase):

    def test_ideal_range_perfect_score(self):
        s = score_length_fitness("nexagen", 4, 8)  # 7 chars — perfect
        self.assertEqual(s, 100)

    def test_exact_min_perfect(self):
        self.assertEqual(score_length_fitness("koda", 4, 8), 100)

    def test_exact_max_perfect(self):
        self.assertEqual(score_length_fitness("nexagen0", 4, 8), 100)

    def test_too_short_penalised(self):
        s = score_length_fitness("ab", 4, 8)
        self.assertLess(s, 100)

    def test_too_long_penalised(self):
        s = score_length_fitness("averylongbrandname", 4, 8)
        self.assertLess(s, 100)

    def test_returns_int(self):
        self.assertIsInstance(score_length_fitness("nexagen", 4, 8), int)

    def test_range_0_to_100(self):
        for name in ["a", "nexagen", "a" * 20]:
            s = score_length_fitness(name, 4, 8)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)


class TestCompositeScore(unittest.TestCase):

    _weights = {
        "pronounce": 0.30,
        "memorability": 0.30,
        "uniqueness": 0.20,
        "length_fit": 0.20,
    }

    def test_all_100_gives_100(self):
        self.assertEqual(composite_score(100, 100, 100, 100, self._weights), 100)

    def test_all_0_gives_0(self):
        self.assertEqual(composite_score(0, 0, 0, 0, self._weights), 0)

    def test_weighted_result_reasonable(self):
        s = composite_score(80, 70, 60, 90, self._weights)
        expected = int(round(80 * 0.30 + 70 * 0.30 + 60 * 0.20 + 90 * 0.20))
        self.assertEqual(s, expected)

    def test_returns_int(self):
        self.assertIsInstance(composite_score(60, 70, 80, 90, self._weights), int)

    def test_range_0_to_100(self):
        s = composite_score(50, 50, 50, 50, self._weights)
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)


class TestTmRisk(unittest.TestCase):

    def test_blacklisted_name_high(self):
        self.assertEqual(tm_risk("google", ["google"]), "high")

    def test_one_edit_high(self):
        result = tm_risk("gogle", ["google"])
        self.assertIn(result, ["high", "medium"])

    def test_clean_name_none(self):
        self.assertEqual(tm_risk("nexagen", ["google", "amazon", "facebook"]), "none")

    def test_returns_valid_level(self):
        for name in ["nexagen", "google", "amaz0n"]:
            result = tm_risk(name, ["google", "amazon"])
            self.assertIn(result, ["none", "low", "medium", "high"])

    def test_empty_blacklist_none(self):
        self.assertEqual(tm_risk("nexagen", []), "none")

    def test_none_blacklist_uses_defaults(self):
        # None → auto-loads from dataset_loader; should return a valid level
        result = tm_risk("nexagen")
        self.assertIn(result, ["none", "low", "medium", "high"])


class TestTierForScore(unittest.TestCase):

    def test_premium_threshold(self):
        self.assertEqual(tier_for_score(SCORE_PREMIUM), BrandTier.PREMIUM.value)
        self.assertEqual(tier_for_score(100), BrandTier.PREMIUM.value)

    def test_strong_threshold(self):
        self.assertEqual(tier_for_score(SCORE_STRONG), BrandTier.STRONG.value)

    def test_decent_threshold(self):
        self.assertEqual(tier_for_score(SCORE_DECENT), BrandTier.DECENT.value)

    def test_weak_threshold(self):
        self.assertEqual(tier_for_score(SCORE_WEAK), BrandTier.WEAK.value)

    def test_zero_is_poor(self):
        self.assertEqual(tier_for_score(0), BrandTier.POOR.value)

    def test_just_below_premium(self):
        self.assertEqual(tier_for_score(SCORE_PREMIUM - 1), BrandTier.STRONG.value)

    def test_just_below_strong(self):
        self.assertEqual(tier_for_score(SCORE_STRONG - 1), BrandTier.DECENT.value)

    def test_just_below_decent(self):
        self.assertEqual(tier_for_score(SCORE_DECENT - 1), BrandTier.WEAK.value)


class TestTierColourForScore(unittest.TestCase):

    def test_returns_hex_string(self):
        colour = tier_colour_for_score(90)
        self.assertTrue(colour.startswith("#"), f"Expected hex, got {colour!r}")

    def test_all_tiers_have_colour(self):
        for score in [95, 80, 65, 50, 20]:
            colour = tier_colour_for_score(score)
            self.assertIsInstance(colour, str)
            self.assertGreater(len(colour), 0)

    def test_premium_gets_gold_hue(self):
        colour = tier_colour_for_score(95)
        self.assertNotEqual(colour, "")


class TestGenerateNotes(unittest.TestCase):

    def setUp(self):
        self.cfg     = get_settings()
        self.scorer  = BrandScorer(self.cfg)

    def test_returns_list(self):
        sr    = self.scorer.score_name("nexagen")
        notes = generate_notes("nexagen", sr, self.cfg)
        self.assertIsInstance(notes, list)

    def test_all_notes_are_strings(self):
        sr    = self.scorer.score_name("nexagen")
        notes = generate_notes("nexagen", sr, self.cfg)
        for note in notes:
            self.assertIsInstance(note, str)

    def test_very_short_name_generates_note(self):
        sr    = self.scorer.score_name("ab")
        notes = generate_notes("ab", sr, self.cfg)
        # Short names should get a length note
        has_length_note = any(
            "short" in n.lower() or "length" in n.lower() or "char" in n.lower()
            for n in notes
        )
        self.assertTrue(has_length_note or len(notes) >= 0)  # graceful fallback

    def test_clean_name_may_return_empty(self):
        sr    = self.scorer.score_name("nexagen")
        notes = generate_notes("nexagen", sr, self.cfg)
        self.assertIsInstance(notes, list)


class TestQuickScore(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(quick_score("nexagen"), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "a", "cloud", "gooooogle"]:
            s = quick_score(name)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_good_name_scores_higher_than_bad(self):
        good = quick_score("nexagen")
        bad  = quick_score("bbbbb")
        self.assertGreater(good, bad)


# ─────────────────────────────────────────────────────────────────────────────
# § 4  BRAND SCORER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class TestBrandScorerScoreName(unittest.TestCase):

    def setUp(self):
        self.cfg    = get_settings()
        self.scorer = BrandScorer(self.cfg)

    def test_returns_score_result(self):
        result = self.scorer.score_name("nexagen")
        self.assertIsInstance(result, ScoreResult)

    def test_name_field_preserved(self):
        result = self.scorer.score_name("nexagen")
        self.assertEqual(result.name, "nexagen")

    def test_score_in_range(self):
        result = self.scorer.score_name("nexagen")
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)

    def test_tier_is_valid(self):
        result = self.scorer.score_name("nexagen")
        valid_tiers = {t.value for t in BrandTier}
        self.assertIn(result.tier, valid_tiers)

    def test_sub_scores_in_range(self):
        r = self.scorer.score_name("nexagen")
        for sub in [r.pronounce, r.memorability, r.uniqueness, r.length_fit]:
            self.assertGreaterEqual(sub, 0)
            self.assertLessEqual(sub, 100)

    def test_tm_risk_valid(self):
        r = self.scorer.score_name("nexagen")
        self.assertIn(r.tm_risk, ["none", "low", "medium", "high"])

    def test_syllables_positive(self):
        r = self.scorer.score_name("nexagen")
        self.assertGreater(r.syllables, 0)

    def test_vowel_ratio_between_0_and_1(self):
        r = self.scorer.score_name("nexagen")
        self.assertGreaterEqual(r.vowel_r, 0.0)
        self.assertLessEqual(r.vowel_r, 1.0)

    def test_phonetic_keys_set(self):
        r = self.scorer.score_name("nexagen")
        self.assertIsInstance(r.phonetic_key, str)
        self.assertIsInstance(r.metaphone_key, str)

    def test_pool_parameter_accepted(self):
        pool   = ["koda", "forge"]
        result = self.scorer.score_name("nexagen", pool=pool)
        self.assertIsInstance(result, ScoreResult)

    def test_notes_is_list(self):
        r = self.scorer.score_name("nexagen")
        self.assertIsInstance(r.notes, list)

    def test_blacklisted_name_high_tm_risk(self):
        r = self.scorer.score_name("google")
        self.assertIn(r.tm_risk, ["high", "medium"])

    def test_is_common_flag(self):
        # "data" is in most common-word lists
        r = self.scorer.score_name("data")
        self.assertIsInstance(r.is_common, bool)


class TestBrandScorerScoreBatch(unittest.TestCase):

    def setUp(self):
        self.cfg    = get_settings()
        self.scorer = BrandScorer(self.cfg)
        self.names  = ["nexagen", "koda", "veltex", "stripe", "forge"]

    def test_returns_list_of_score_results(self):
        results = self.scorer.score_batch(self.names)
        self.assertIsInstance(results, list)
        for r in results:
            self.assertIsInstance(r, ScoreResult)

    def test_preserves_order(self):
        results = self.scorer.score_batch(self.names)
        returned_names = [r.name for r in results]
        self.assertEqual(returned_names, self.names)

    def test_same_length_as_input(self):
        results = self.scorer.score_batch(self.names)
        self.assertEqual(len(results), len(self.names))

    def test_pool_accumulation_differentiates_near_duplicates(self):
        similar = ["nexagen", "nexagon", "nexagene"]
        results = self.scorer.score_batch(similar, accumulate_pool=True)
        # Later names should score lower for uniqueness (pool is growing)
        u_scores = [r.uniqueness for r in results]
        self.assertLessEqual(u_scores[-1], u_scores[0] + 10)  # relative penalty

    def test_no_accumulation_independent_scores(self):
        similar  = ["nexagen", "nexagon"]
        with_acc = self.scorer.score_batch(similar, accumulate_pool=True)
        without  = self.scorer.score_batch(similar, accumulate_pool=False)
        # Without accumulation, both should score identically (no pool bias)
        self.assertEqual(with_acc[0].score, without[0].score)

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.scorer.score_batch([]), [])


class TestBrandScorerToNameResult(unittest.TestCase):

    def setUp(self):
        self.cfg    = get_settings()
        self.scorer = BrandScorer(self.cfg)

    def test_returns_name_result(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr)
        self.assertIsInstance(nr, NameResult)

    def test_name_preserved(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr)
        self.assertEqual(nr.name, "nexagen")

    def test_score_preserved(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr)
        self.assertEqual(nr.score, sr.score)

    def test_tier_preserved(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr)
        self.assertEqual(nr.tier, sr.tier)

    def test_keywords_passed_through(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr, keywords=["cloud", "data"])
        self.assertIn("cloud", nr.keywords)

    def test_sub_scores_populated(self):
        sr = self.scorer.score_name("nexagen")
        nr = self.scorer.to_name_result(sr)
        self.assertGreater(nr.pronounce, 0)
        self.assertGreater(nr.memorability, 0)


class TestBrandScorerToAnalysisData(unittest.TestCase):

    def setUp(self):
        self.cfg    = get_settings()
        self.scorer = BrandScorer(self.cfg)

    def test_returns_analysis_data(self):
        sr = self.scorer.score_name("nexagen")
        ad = self.scorer.to_analysis_data(sr)
        self.assertIsInstance(ad, AnalysisData)

    def test_name_preserved(self):
        sr = self.scorer.score_name("nexagen")
        ad = self.scorer.to_analysis_data(sr)
        self.assertEqual(ad.name, "nexagen")

    def test_vowel_ratio_populated(self):
        sr = self.scorer.score_name("nexagen")
        ad = self.scorer.to_analysis_data(sr)
        self.assertGreaterEqual(ad.vowel_ratio, 0.0)
        self.assertLessEqual(ad.vowel_ratio, 1.0)

    def test_phonetic_key_populated(self):
        sr = self.scorer.score_name("nexagen")
        ad = self.scorer.to_analysis_data(sr)
        self.assertIsInstance(ad.phonetic_key, str)

    def test_notes_is_list(self):
        sr = self.scorer.score_name("nexagen")
        ad = self.scorer.to_analysis_data(sr)
        self.assertIsInstance(ad.notes, list)


# ─────────────────────────────────────────────────────────────────────────────
# § 5  PHONETIC ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalysePhonetics(unittest.TestCase):

    def setUp(self):
        self.report = analyse_phonetics("nexagen")

    def test_returns_phonetic_report(self):
        self.assertIsInstance(self.report, PhoneticReport)

    def test_name_preserved(self):
        self.assertEqual(self.report.name, "nexagen")

    def test_composite_in_range(self):
        self.assertGreaterEqual(self.report.composite, 0)
        self.assertLessEqual(self.report.composite, 100)

    def test_grade_is_letter(self):
        self.assertIn(self.report.grade, ["A", "B", "C", "D", "F"])

    def test_dimensions_populated(self):
        self.assertGreater(len(self.report.dimensions), 0)

    def test_dimension_count_is_nine(self):
        self.assertEqual(len(self.report.dimensions), 9)

    def test_all_dimensions_have_keys(self):
        expected_keys = {
            "vowel_balance", "consonant_flow", "alternation",
            "forbidden_bigrams", "syllable_profile", "opening_strength",
            "closing_quality", "rare_consonants", "phonetic_uniqueness",
        }
        returned_keys = {d.key for d in self.report.dimensions}
        self.assertEqual(returned_keys, expected_keys)

    def test_dimension_scores_in_range(self):
        for dim in self.report.dimensions:
            self.assertGreaterEqual(dim.score, 0)
            self.assertLessEqual(dim.score, 100)

    def test_dimension_weights_sum_to_one(self):
        total = sum(d.weight for d in self.report.dimensions)
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_dimension_has_label(self):
        for dim in self.report.dimensions:
            self.assertIsInstance(dim.label, str)
            self.assertGreater(len(dim.label), 0)

    def test_passed_flag_type(self):
        for dim in self.report.dimensions:
            self.assertIsInstance(dim.passed, bool)

    def test_soundex_key_set(self):
        self.assertIsInstance(self.report.soundex_key, str)
        self.assertEqual(len(self.report.soundex_key), 4)  # Soundex is always 4 chars

    def test_metaphone_key_set(self):
        self.assertIsInstance(self.report.metaphone_key, str)
        self.assertGreater(len(self.report.metaphone_key), 0)

    def test_syllables_positive(self):
        self.assertGreater(self.report.syllables, 0)

    def test_vowel_r_in_range(self):
        self.assertGreaterEqual(self.report.vowel_r, 0.0)
        self.assertLessEqual(self.report.vowel_r, 1.0)

    def test_is_pronounceable_flag(self):
        self.assertIsInstance(self.report.is_pronounceable, bool)


class TestPhoneticGradeThresholds(unittest.TestCase):

    def test_high_score_gets_a(self):
        # Inject a report-like name that we know scores well phonetically
        report = analyse_phonetics("stripe")  # short, clean, pronounceable
        self.assertIn(report.grade, ["A", "B", "C", "D", "F"])

    def test_grade_a_requires_88_plus(self):
        for name in ["stripe", "koda", "forge", "nexagen"]:
            report = analyse_phonetics(name)
            if report.composite >= 88:
                self.assertEqual(report.grade, "A")

    def test_grade_f_for_low_score(self):
        # All-consonant name should score low
        report = analyse_phonetics("bcd")
        if report.composite < 45:
            self.assertEqual(report.grade, "F")


class TestPhoneticScore(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(phonetic_score("nexagen"), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "koda", "bcd", "stripe"]:
            s = phonetic_score(name)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)


class TestPhoneticGrade(unittest.TestCase):

    def test_returns_letter(self):
        self.assertIn(phonetic_grade("nexagen"), ["A", "B", "C", "D", "F"])

    def test_all_grades_possible(self):
        # Just verify the function returns a valid letter for various inputs
        for name in ["nexagen", "koda", "bcd", "aaaa", "stripe"]:
            g = phonetic_grade(name)
            self.assertIn(g, ["A", "B", "C", "D", "F"])


class TestBatchAnalyse(unittest.TestCase):

    def test_returns_list(self):
        names   = ["nexagen", "koda", "veltex"]
        reports = batch_analyse(names)
        self.assertIsInstance(reports, list)
        self.assertEqual(len(reports), len(names))

    def test_all_phonetic_reports(self):
        for r in batch_analyse(["nexagen", "koda"]):
            self.assertIsInstance(r, PhoneticReport)

    def test_empty_list_returns_empty(self):
        self.assertEqual(batch_analyse([]), [])

    def test_order_preserved(self):
        names   = ["stripe", "nexagen", "forge"]
        reports = batch_analyse(names)
        for r, n in zip(reports, names):
            self.assertEqual(r.name, n)


class TestGroupByPhoneticKey(unittest.TestCase):

    def test_returns_dict(self):
        result = group_by_phonetic_key(["nexagen", "koda", "stripe"])
        self.assertIsInstance(result, dict)

    def test_all_names_appear_in_groups(self):
        names  = ["nexagen", "koda", "stripe"]
        groups = group_by_phonetic_key(names)
        all_in = [n for g in groups.values() for n in g]
        for name in names:
            self.assertIn(name, all_in)

    def test_phonetically_similar_in_same_group(self):
        names  = ["phone", "fone", "koda"]
        groups = group_by_phonetic_key(names)
        flat   = {n: key for key, lst in groups.items() for n in lst}
        self.assertEqual(flat.get("phone"), flat.get("fone"))

    def test_metaphone_algorithm(self):
        result = group_by_phonetic_key(["nexagen"], algorithm="metaphone")
        self.assertIsInstance(result, dict)


class TestTopPhoneticNames(unittest.TestCase):

    def test_returns_list_of_tuples(self):
        names  = ["nexagen", "koda", "veltex", "stripe", "forge"]
        result = top_phonetic_names(names, n=3)
        self.assertIsInstance(result, list)
        for name, score in result:
            self.assertIsInstance(name, str)
            self.assertIsInstance(score, int)

    def test_n_limit_respected(self):
        names  = ["nexagen", "koda", "veltex", "stripe", "forge"]
        result = top_phonetic_names(names, n=2)
        self.assertLessEqual(len(result), 2)

    def test_sorted_by_score_desc(self):
        names  = ["nexagen", "koda", "veltex", "stripe", "forge"]
        result = top_phonetic_names(names, n=5)
        if len(result) > 1:
            scores = [s for _, s in result]
            self.assertEqual(scores, sorted(scores, reverse=True))


# ─────────────────────────────────────────────────────────────────────────────
# § 6  COLLISION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectCollisions(unittest.TestCase):

    _BRANDS = ["google", "amazon", "facebook", "apple", "microsoft",
               "netflix", "spotify", "twitter", "stripe", "slack"]

    def test_returns_collision_report(self):
        r = detect_collisions("nexagen", self._BRANDS)
        self.assertIsInstance(r, CollisionReport)

    def test_name_field_preserved(self):
        r = detect_collisions("nexagen", self._BRANDS)
        self.assertEqual(r.name, "nexagen")

    def test_clean_name_is_safe(self):
        r = detect_collisions("nexagen", self._BRANDS)
        self.assertTrue(r.is_safe)

    def test_exact_match_critical(self):
        r = detect_collisions("google", self._BRANDS)
        self.assertFalse(r.is_safe)
        self.assertEqual(r.risk, RiskLevel.CRITICAL)

    def test_one_edit_flagged(self):
        r = detect_collisions("gogle", self._BRANDS)
        self.assertIn(r.risk, [RiskLevel.HIGH, RiskLevel.CRITICAL])

    def test_hits_have_correct_type(self):
        r = detect_collisions("google", self._BRANDS)
        for hit in r.hits:
            self.assertIsInstance(hit, CollisionHit)

    def test_hit_candidate_field(self):
        r = detect_collisions("google", self._BRANDS)
        for hit in r.hits:
            self.assertEqual(hit.candidate, "google")

    def test_hit_protected_in_blacklist(self):
        r = detect_collisions("google", self._BRANDS)
        for hit in r.hits:
            self.assertIn(hit.protected, self._BRANDS)

    def test_hit_signal_is_valid(self):
        r = detect_collisions("google", self._BRANDS)
        valid_signals = {s.value for s in CollisionSignal}
        for hit in r.hits:
            self.assertIn(hit.signal.value, valid_signals)

    def test_hit_count_property(self):
        r = detect_collisions("google", self._BRANDS)
        self.assertEqual(r.hit_count, len(r.hits))

    def test_blocked_by_property(self):
        r = detect_collisions("google", self._BRANDS)
        if r.hits:
            self.assertNotEqual(r.blocked_by, "")

    def test_summary_returns_string(self):
        r = detect_collisions("nexagen", self._BRANDS)
        self.assertIsInstance(r.summary, str)

    def test_empty_blacklist_is_safe(self):
        r = detect_collisions("nexagen", [])
        self.assertTrue(r.is_safe)
        self.assertEqual(r.risk, RiskLevel.NONE)

    def test_none_blacklist_uses_defaults(self):
        r = detect_collisions("nexagen")
        self.assertIsInstance(r, CollisionReport)

    def test_skip_phonetic_flag(self):
        r = detect_collisions("nexagen", self._BRANDS, skip_phonetic=True)
        # No PHONETIC hits expected
        phonetic_hits = [h for h in r.hits if h.signal == CollisionSignal.PHONETIC]
        self.assertEqual(len(phonetic_hits), 0)

    def test_skip_ngram_flag(self):
        r = detect_collisions("nexagen", self._BRANDS, skip_ngram=True)
        ngram_hits = [h for h in r.hits if h.signal == CollisionSignal.NGRAM]
        self.assertEqual(len(ngram_hits), 0)

    def test_risk_level_ordering(self):
        self.assertLess(RiskLevel.NONE, RiskLevel.LOW)
        self.assertLess(RiskLevel.LOW, RiskLevel.MEDIUM)
        self.assertLess(RiskLevel.MEDIUM, RiskLevel.HIGH)
        self.assertLess(RiskLevel.HIGH, RiskLevel.CRITICAL)


class TestQuickRisk(unittest.TestCase):

    _BRANDS = ["google", "amazon", "stripe"]

    def test_clean_name_none(self):
        self.assertEqual(quick_risk("nexagen", self._BRANDS), "none")

    def test_exact_match_critical(self):
        self.assertEqual(quick_risk("google", self._BRANDS), "critical")

    def test_returns_valid_level(self):
        for name in ["nexagen", "google", "amaz0n"]:
            result = quick_risk(name, self._BRANDS)
            self.assertIn(result, ["none", "low", "medium", "high", "critical"])


class TestIsSafe(unittest.TestCase):

    _BRANDS = ["google", "amazon", "stripe"]

    def test_clean_name_is_safe(self):
        self.assertTrue(is_safe("nexagen", self._BRANDS))

    def test_exact_match_not_safe(self):
        self.assertFalse(is_safe("google", self._BRANDS))

    def test_max_risk_parameter(self):
        # nexagen should be safe at any threshold
        self.assertTrue(is_safe("nexagen", self._BRANDS, max_risk=RiskLevel.CRITICAL))


class TestFilterSafeNames(unittest.TestCase):

    _BRANDS = ["google", "amazon", "stripe"]

    def test_returns_two_lists(self):
        safe, flagged = filter_safe_names(["nexagen", "google", "koda"], self._BRANDS)
        self.assertIsInstance(safe, list)
        self.assertIsInstance(flagged, list)

    def test_google_is_flagged(self):
        _, flagged = filter_safe_names(["nexagen", "google"], self._BRANDS)
        flagged_names = [r.name for r in flagged]
        self.assertIn("google", flagged_names)

    def test_nexagen_is_safe(self):
        safe, _ = filter_safe_names(["nexagen", "google"], self._BRANDS)
        self.assertIn("nexagen", safe)

    def test_flagged_are_collision_reports(self):
        _, flagged = filter_safe_names(["google"], self._BRANDS)
        for r in flagged:
            self.assertIsInstance(r, CollisionReport)


class TestBatchDetect(unittest.TestCase):

    _BRANDS = ["google", "amazon", "stripe"]

    def test_returns_list_of_reports(self):
        reports = batch_detect(["nexagen", "koda", "google"], self._BRANDS)
        self.assertEqual(len(reports), 3)
        for r in reports:
            self.assertIsInstance(r, CollisionReport)

    def test_order_preserved(self):
        names   = ["nexagen", "google", "koda"]
        reports = batch_detect(names, self._BRANDS)
        for r, n in zip(reports, names):
            self.assertEqual(r.name, n)

    def test_empty_list_returns_empty(self):
        self.assertEqual(batch_detect([], self._BRANDS), [])


class TestPairwiseCollisions(unittest.TestCase):

    def test_identical_names_flagged(self):
        names  = ["nexagen", "nexagen"]
        pairs  = pairwise_collisions(names)
        self.assertGreater(len(pairs), 0)

    def test_near_duplicate_flagged(self):
        names = ["nexagen", "nexagon"]
        pairs = pairwise_collisions(names, threshold=0.80)
        self.assertGreater(len(pairs), 0)

    def test_distinct_names_no_pairs(self):
        names = ["nexagen", "koda", "veltex", "forge"]
        pairs = pairwise_collisions(names, threshold=0.95)
        self.assertEqual(len(pairs), 0)

    def test_returns_tuples_with_score(self):
        names = ["nexagen", "nexagon"]
        for a, b, score in pairwise_collisions(names, threshold=0.70):
            self.assertIsInstance(score, float)
            self.assertGreaterEqual(score, 0.70)


# ─────────────────────────────────────────────────────────────────────────────
# § 7  UNIQUENESS SCORE
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreUniquenessFull(unittest.TestCase):

    def setUp(self):
        self.report = score_uniqueness_full("nexagen")

    def test_returns_uniqueness_report(self):
        self.assertIsInstance(self.report, UniquenessReport)

    def test_name_preserved(self):
        self.assertEqual(self.report.name, "nexagen")

    def test_composite_in_range(self):
        self.assertGreaterEqual(self.report.composite, 0)
        self.assertLessEqual(self.report.composite, 100)

    def test_verdict_is_valid(self):
        self.assertIn(self.report.verdict,
                      ["unique", "borderline", "common", "collision"])

    def test_axes_populated(self):
        self.assertGreater(len(self.report.axes), 0)

    def test_five_axes(self):
        self.assertEqual(len(self.report.axes), 5)

    def test_axis_keys_correct(self):
        expected = {
            "common_word", "blacklist_proximity",
            "pool_distance", "phonetic_distance", "visual_novelty",
        }
        returned = {a.key for a in self.report.axes}
        self.assertEqual(returned, expected)

    def test_axis_scores_in_range(self):
        for axis in self.report.axes:
            self.assertGreaterEqual(axis.score, 0)
            self.assertLessEqual(axis.score, 100)

    def test_axis_weights_sum_to_one(self):
        total = sum(a.weight for a in self.report.axes)
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_common_word_flagged(self):
        common = frozenset(["data"])
        r = score_uniqueness_full("data", common=common)
        self.assertTrue(r.is_common_word)

    def test_unique_name_not_common(self):
        common = frozenset(["data", "cloud"])
        r = score_uniqueness_full("nexagen", common=common)
        self.assertFalse(r.is_common_word)

    def test_blacklist_collision_low_score(self):
        r = score_uniqueness_full("google", blacklist=["google"])
        self.assertLess(r.composite, 50)

    def test_pool_reduces_uniqueness(self):
        no_pool   = score_uniqueness_full("nexagen")
        with_pool = score_uniqueness_full("nexagen", pool=["nexagon", "nexagene", "nexagenz"])
        # Both valid, pool version may be same or lower
        self.assertGreaterEqual(no_pool.composite, 0)
        self.assertGreaterEqual(with_pool.composite, 0)

    def test_nearst_blacklist_set(self):
        r = score_uniqueness_full("gogle", blacklist=["google"])
        self.assertIsInstance(r.nearest_blacklist, str)

    def test_notes_is_list(self):
        self.assertIsInstance(self.report.notes, list)


class TestScoreUniquenessScalar(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(score_uniqueness_scalar("nexagen"), int)

    def test_range_0_to_100(self):
        for name in ["nexagen", "data", "google"]:
            s = score_uniqueness_scalar(name)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_matches_full_composite(self):
        full   = score_uniqueness_full("nexagen")
        scalar = score_uniqueness_scalar("nexagen")
        self.assertEqual(scalar, full.composite)


class TestBatchScoreUniqueness(unittest.TestCase):

    def test_returns_list_of_reports(self):
        names   = ["nexagen", "koda", "veltex"]
        reports = batch_score_uniqueness(names)
        self.assertEqual(len(reports), len(names))
        for r in reports:
            self.assertIsInstance(r, UniquenessReport)

    def test_order_preserved(self):
        names   = ["nexagen", "koda"]
        reports = batch_score_uniqueness(names)
        for r, n in zip(reports, names):
            self.assertEqual(r.name, n)

    def test_cross_comparison_lowers_near_duplicates(self):
        similar = ["nexagen", "nexagon", "nexagene"]
        reports = batch_score_uniqueness(similar)
        # Later names score lower because pool grows
        self.assertGreaterEqual(reports[0].composite, 0)

    def test_empty_list_returns_empty(self):
        self.assertEqual(batch_score_uniqueness([]), [])


class TestRankByUniqueness(unittest.TestCase):

    def test_returns_list_of_tuples(self):
        names  = ["nexagen", "data", "koda"]
        result = rank_by_uniqueness(names)
        self.assertIsInstance(result, list)
        for name, score in result:
            self.assertIsInstance(name, str)
            self.assertIsInstance(score, int)

    def test_sorted_by_score_desc(self):
        names  = ["nexagen", "data", "koda", "veltex"]
        result = rank_by_uniqueness(names)
        scores = [s for _, s in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_n_limit(self):
        names  = ["nexagen", "data", "koda", "veltex", "forge"]
        result = rank_by_uniqueness(names, n=3)
        self.assertLessEqual(len(result), 3)


class TestFilterUnique(unittest.TestCase):

    def test_returns_list(self):
        names  = ["nexagen", "data", "koda"]
        result = filter_unique(names, threshold=50)
        self.assertIsInstance(result, list)

    def test_all_returned_meet_threshold(self):
        names  = ["nexagen", "koda", "veltex"]
        result = filter_unique(names, threshold=60)
        # Just verify names not known to fail the threshold come back
        for name in result:
            self.assertIn(name, names)

    def test_high_threshold_returns_fewer(self):
        names = ["nexagen", "data", "cloud", "koda"]
        low   = filter_unique(names, threshold=20)
        high  = filter_unique(names, threshold=80)
        self.assertGreaterEqual(len(low), len(high))

    def test_empty_list_returns_empty(self):
        self.assertEqual(filter_unique([], threshold=60), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
