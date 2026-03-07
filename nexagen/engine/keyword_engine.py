"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  engine/keyword_engine.py  ·  Keyword preprocessing and enrichment         ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  https://github.com/cyberempirex/nexagen                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

First stage in the generation pipeline. Transforms raw user-supplied text
into a clean, scored, profile-aware keyword set that feeds into
SynonymEngine for expansion.

Pipeline position
─────────────────
  User input (raw text / keyword list)
       │
       ▼
  KeywordEngine          ← THIS MODULE
  ├─ clean & normalise
  ├─ validate
  ├─ score by relevance
  └─ profile-boost
       │
       ▼
  SynonymEngine          ← synonym_engine.py
       │
       ▼
  PatternEngine / MutationEngine

Responsibilities
────────────────
  • Accept raw text strings, comma-separated lists, or keyword lists
  • Strip punctuation, normalise Unicode, lower-case
  • Filter stop-words, very short tokens, and purely numeric tokens
  • Validate each keyword with validators.validate_keyword()
  • Score keywords: how well they match the active profile vocabulary
  • Profile-boost: re-order keywords so the most domain-relevant ones
    come first (SynonymEngine processes the front of the list first)
  • Extract keywords from free-form product description text
  • Return a KeywordSet containing all intermediate representations

Public API
──────────
  KeywordEngine.process(raw_input, cfg)         → KeywordSet
  KeywordEngine.clean_one(text)                 → str
  KeywordEngine.extract_from_text(text, cfg)    → list[str]
  KeywordEngine.score_keywords(kws, profile)    → list[ScoredKeyword]
  KeywordEngine.boost_for_profile(kws, profile) → list[str]
  KeywordEngine.validate(kws)                   → list[str]  errors
  process_keywords(raw_input, cfg)              → list[str]  (simple)
  extract_keywords(text, cfg)                   → list[str]  (simple)

Data structures
───────────────
  ScoredKeyword  — keyword + profile relevance score + validation status
  KeywordSet     — full preprocessing output with stats
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

from ..config.constants import (
    MAX_KEYWORD_LENGTH,
    MAX_KEYWORDS_PER_RUN,
    Profile,
)
from ..config.settings import Settings, get_settings
from ..utils.dataset_loader import (
    ai_terms,
    business_terms,
    synonyms,
    tech_terms,
    vocab_for_profile,
)
from ..utils.text_utils import (
    extract_keywords as _text_extract,
    is_all_lowercase_alpha,
    normalize,
    strip_non_alpha,
)
from ..utils.validators import validate_keyword

# ─────────────────────────────────────────────────────────────────────────────
# § 1  STOP-WORDS AND FILTERS
# ─────────────────────────────────────────────────────────────────────────────

#: English stop-words that carry no brand-naming signal
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "for", "nor", "on", "at",
    "to", "by", "up", "in", "of", "it", "is", "be", "as", "do",
    "we", "my", "me", "he", "she", "its", "was", "are", "has",
    "had", "will", "can", "may", "not", "no", "if", "so", "with",
    "that", "this", "from", "have", "been", "use", "using", "used",
    "help", "make", "makes", "made", "build", "built", "new", "good",
    "better", "best", "more", "most", "all", "some", "any", "get",
    "got", "our", "your", "their", "his", "her", "its", "also",
    "just", "like", "very", "well", "now", "then", "than", "when",
    "where", "how", "what", "who", "why", "each", "both", "few",
    "own", "too", "here", "there", "such", "into", "out", "over",
    "did", "does", "been", "being", "having",
})

#: Minimum useful keyword length after cleaning
_MIN_KW_LEN: int = 2

#: Maximum useful keyword length before splitting is considered
_MAX_KW_LEN: int = MAX_KEYWORD_LENGTH


# ─────────────────────────────────────────────────────────────────────────────
# § 2  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScoredKeyword:
    """
    A single keyword paired with its profile relevance score.

    Attributes:
        word:        Cleaned lowercase keyword string.
        raw:         The original user-supplied string before cleaning.
        score:       Profile relevance score 0–100 (higher = more relevant).
        is_valid:    True if validate_keyword() returned no errors.
        errors:      Validation error messages (empty if valid).
        in_vocab:    True if word appears in the active profile vocabulary.
        in_synonyms: True if the word is a root in the synonym map.
    """
    word:        str
    raw:         str
    score:       int        = 0
    is_valid:    bool       = True
    errors:      list[str]  = field(default_factory=list)
    in_vocab:    bool       = False
    in_synonyms: bool       = False

    def __hash__(self) -> int:
        return hash(self.word)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ScoredKeyword) and self.word == other.word


@dataclass
class KeywordSet:
    """
    Complete output of a KeywordEngine.process() run.

    Attributes:
        raw_input:      Original strings exactly as the user supplied them.
        cleaned:        All tokens after normalisation (may include invalids).
        valid:          Cleaned tokens that passed validation.
        invalid:        Tokens that failed validation with reasons.
        scored:         ScoredKeyword list sorted by profile relevance.
        profile:        Active profile string used for scoring.
        final:          Final ordered keyword list ready for SynonymEngine
                        (profile-boosted, deduplicated, capped at limit).
        count:          Number of keywords in final.
        warnings:       Any non-fatal processing warnings.
    """
    raw_input:  list[str]
    cleaned:    list[str]
    valid:      list[str]
    invalid:    dict[str, list[str]]         # word → [error messages]
    scored:     list[ScoredKeyword]
    profile:    str
    final:      list[str]
    count:      int                          = 0
    warnings:   list[str]                   = field(default_factory=list)

    def __post_init__(self) -> None:
        self.count = len(self.final)

    @property
    def top(self) -> list[str]:
        """Return the top-10 keywords by relevance score."""
        return [sk.word for sk in self.scored[:10]]

    @property
    def has_valid_keywords(self) -> bool:
        """True if at least one keyword passed validation."""
        return len(self.valid) > 0


# ─────────────────────────────────────────────────────────────────────────────
# § 3  CLEANING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _tokenise(text: str) -> list[str]:
    """
    Split raw input text into tokens on word boundaries.

    Handles comma-separated, space-separated, and mixed inputs.
    Returns lowercase alpha-only tokens.
    """
    # Replace common separators with space
    normalised = re.sub(r"[,;|/\\+&]", " ", text)
    # Split on whitespace and non-alpha runs
    parts = re.split(r"\s+|[^a-zA-Z]+", normalised)
    return [p.lower() for p in parts if p]


def _clean_token(token: str) -> str:
    """
    Normalise a single token to a clean lowercase alpha string.

    Applies Unicode normalisation, removes punctuation, lowercases.
    """
    return re.sub(r"[^a-z]", "", normalize(token).lower())


def _is_useful(token: str) -> bool:
    """Return True if a cleaned token is worth keeping as a keyword."""
    if not token or not token.isalpha():
        return False
    if len(token) < _MIN_KW_LEN or len(token) > _MAX_KW_LEN:
        return False
    if token in _STOP_WORDS:
        return False
    # Reject pure digit sequences that slipped through
    if token.isdigit():
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# § 4  SCORING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Profile → vocabulary weight boosts
_PROFILE_BOOST: dict[str, int] = {
    Profile.TECH.value:      20,
    Profile.AI.value:        20,
    Profile.SECURITY.value:  18,
    Profile.FINANCE.value:   18,
    Profile.HEALTH.value:    16,
    Profile.SOCIAL.value:    15,
    Profile.EDUCATION.value: 14,
    Profile.DOCUMENT.value:  12,
    Profile.GENERIC.value:   10,
}


def _score_keyword(word: str, profile: str, vocab_set: frozenset[str],
                   syn_roots: frozenset[str]) -> int:
    """
    Compute a profile relevance score 0–100 for a single keyword.

    Factors:
      • In profile vocabulary          +30
      • Is a synonym root              +20
      • Length sweet spot (4–8 chars)  +15
      • Strong opening consonant       +10
      • Profile domain boost           +10–20
    """
    score = 30  # baseline

    if word in vocab_set:
        score += 30

    if word in syn_roots:
        score += 20

    n = len(word)
    if 4 <= n <= 8:
        score += 15
    elif 3 <= n <= 10:
        score += 7

    if word and word[0] in "bdfgkprstvz":
        score += 10

    score += _PROFILE_BOOST.get(profile, 10)

    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────────────────
# § 5  KEYWORD ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class KeywordEngine:
    """
    Preprocesses, validates, scores, and orders user-supplied keywords.

    Usage::

        from nexagen.engine.keyword_engine import KeywordEngine
        engine = KeywordEngine()
        ks = engine.process(["cloud security", "zero trust"], cfg)
        seeds = ks.final   # ready for SynonymEngine.expand()

    The engine is stateless — safe to reuse across multiple calls.
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def process(
        self,
        raw_input: Union[str, Sequence[str]],
        cfg:       Optional[Settings] = None,
    ) -> KeywordSet:
        """
        Full keyword preprocessing pipeline.

        Steps:
          1. Accept str or list[str] — normalise to list
          2. Tokenise each input (split on spaces, commas, etc.)
          3. Clean each token (normalise, alpha-only, lowercase)
          4. Filter stop-words and length limits
          5. Validate with validators.validate_keyword()
          6. Score against profile vocabulary and synonym roots
          7. Profile-boost ordering
          8. Deduplicate and cap at MAX_KEYWORDS_PER_RUN

        Args:
            raw_input: User-supplied keyword(s) as a string or list.
            cfg:       Active Settings (profile affects scoring and boost).

        Returns:
            :class:`KeywordSet` with all intermediate representations.
        """
        if cfg is None:
            cfg = get_settings()

        # ── Step 1: Normalise input to list ───────────────────────────────────
        if isinstance(raw_input, str):
            raw_list = [raw_input]
        else:
            raw_list = [str(x) for x in raw_input]

        # ── Step 2: Tokenise ──────────────────────────────────────────────────
        all_tokens: list[tuple[str, str]] = []  # (raw, cleaned)
        for raw_item in raw_list:
            for tok in _tokenise(raw_item):
                cleaned = _clean_token(tok)
                if cleaned:
                    all_tokens.append((tok, cleaned))

        # ── Step 3–4: Filter ──────────────────────────────────────────────────
        cleaned_words: list[str] = []
        seen: set[str] = set()
        for raw_tok, cleaned in all_tokens:
            if cleaned not in seen and _is_useful(cleaned):
                seen.add(cleaned)
                cleaned_words.append(cleaned)

        # ── Step 5: Validate ──────────────────────────────────────────────────
        valid_words: list[str] = []
        invalid_words: dict[str, list[str]] = {}
        warnings: list[str] = []

        for word in cleaned_words:
            result = validate_keyword(word)
            if result.ok:
                valid_words.append(word)
            else:
                errs = [issue.message for issue in result.issues]
                invalid_words[word] = errs

        if not valid_words and cleaned_words:
            # Fallback: use cleaned words ignoring validation
            valid_words = cleaned_words
            warnings.append(
                "Keyword validation failed for all tokens — using cleaned words."
            )

        # ── Step 6: Score ─────────────────────────────────────────────────────
        scored = self.score_keywords(valid_words, cfg.profile)

        # ── Step 7: Profile-boost ordering ───────────────────────────────────
        boosted = self.boost_for_profile(
            [sk.word for sk in scored], cfg.profile
        )

        # ── Step 8: Cap ───────────────────────────────────────────────────────
        final = boosted[:MAX_KEYWORDS_PER_RUN]

        if len(valid_words) > MAX_KEYWORDS_PER_RUN:
            warnings.append(
                f"Input contained {len(valid_words)} keywords; "
                f"capped at {MAX_KEYWORDS_PER_RUN}."
            )

        return KeywordSet(
            raw_input = raw_list,
            cleaned   = cleaned_words,
            valid     = valid_words,
            invalid   = invalid_words,
            scored    = scored,
            profile   = cfg.profile,
            final     = final,
            warnings  = warnings,
        )

    # ── Cleaning ──────────────────────────────────────────────────────────────

    def clean_one(self, text: str) -> str:
        """
        Clean and normalise a single keyword string.

        Args:
            text: Raw keyword string.

        Returns:
            Cleaned lowercase alpha string, or empty string if unusable.
        """
        cleaned = _clean_token(text)
        return cleaned if _is_useful(cleaned) else ""

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score_keywords(
        self,
        keywords: Sequence[str],
        profile:  str = Profile.GENERIC.value,
    ) -> list[ScoredKeyword]:
        """
        Score a list of cleaned keywords by profile relevance.

        Args:
            keywords: Clean lowercase keyword strings.
            profile:  Profile value string (e.g. "ai", "tech").

        Returns:
            List of ScoredKeyword sorted by score descending.
        """
        vocab_set  = frozenset(vocab_for_profile(profile))
        syn_map    = synonyms()
        syn_roots  = frozenset(syn_map.keys())

        scored: list[ScoredKeyword] = []
        for word in keywords:
            w       = word.strip().lower()
            if not w:
                continue
            vr      = validate_keyword(w)
            score   = _score_keyword(w, profile, vocab_set, syn_roots)
            scored.append(ScoredKeyword(
                word        = w,
                raw         = word,
                score       = score,
                is_valid    = vr.ok,
                errors      = [i.message for i in vr.issues],
                in_vocab    = w in vocab_set,
                in_synonyms = w in syn_roots,
            ))

        return sorted(scored, key=lambda sk: -sk.score)

    # ── Profile boost ─────────────────────────────────────────────────────────

    def boost_for_profile(
        self,
        keywords: Sequence[str],
        profile:  str = Profile.GENERIC.value,
    ) -> list[str]:
        """
        Re-order keywords so the most profile-relevant ones come first.

        Profile-matched vocabulary words are moved to the front; the
        remainder retain their original relative order.

        Args:
            keywords: Cleaned keyword strings.
            profile:  Profile value string.

        Returns:
            Re-ordered deduplicated keyword list.
        """
        vocab_set = frozenset(vocab_for_profile(profile))
        syn_roots = frozenset(synonyms().keys())

        boosted:  list[str] = []
        fallback: list[str] = []
        seen: set[str] = set()

        for kw in keywords:
            w = kw.strip().lower()
            if not w or w in seen:
                continue
            seen.add(w)
            if w in vocab_set or w in syn_roots:
                boosted.append(w)
            else:
                fallback.append(w)

        return boosted + fallback

    # ── Free-text extraction ──────────────────────────────────────────────────

    def extract_from_text(
        self,
        text: str,
        cfg:  Optional[Settings] = None,
    ) -> list[str]:
        """
        Extract keywords from free-form product description text.

        Uses text_utils.extract_keywords() to pull meaningful tokens,
        then applies cleaning, validation, and profile scoring.

        Args:
            text: Any prose description (e.g. "A fast cloud-native AI tool").
            cfg:  Active Settings.

        Returns:
            Ordered list of clean keywords, best first.
        """
        if cfg is None:
            cfg = get_settings()

        # Extract meaningful tokens (min_len=3 to skip prepositions)
        raw_kws = _text_extract(text, min_len=3)

        # Run through the full pipeline
        ks = self.process(raw_kws, cfg)
        return ks.final

    # ── Validation helper ─────────────────────────────────────────────────────

    def validate(self, keywords: Sequence[str]) -> list[str]:
        """
        Validate a list of keywords and return a list of error strings.

        Args:
            keywords: Cleaned keyword strings to validate.

        Returns:
            Flat list of human-readable error messages.
            Empty list if all keywords are valid.
        """
        errors: list[str] = []
        for kw in keywords:
            result = validate_keyword(kw)
            if not result.ok:
                for issue in result.issues:
                    errors.append(f"{kw!r}: {issue.message}")
        return errors

    # ── Suggestion helper ─────────────────────────────────────────────────────

    def suggest_related(
        self,
        keyword: str,
        cfg:     Optional[Settings] = None,
        max_suggestions: int = 8,
    ) -> list[str]:
        """
        Suggest related keywords for a single seed word.

        Looks up synonyms and returns profile-relevant matches from the
        vocabulary that share a prefix or substring with the keyword.

        Args:
            keyword:         Seed word to expand.
            cfg:             Active Settings.
            max_suggestions: Maximum suggestions to return.

        Returns:
            Ordered list of suggested related keywords.
        """
        if cfg is None:
            cfg = get_settings()

        w         = _clean_token(keyword)
        syn_map   = synonyms()
        vocab     = vocab_for_profile(cfg.profile)
        vocab_set = frozenset(vocab)

        suggestions: set[str] = set()

        # Direct synonym lookup
        for syn in syn_map.get(w, []):
            s = _clean_token(syn)
            if s and _is_useful(s):
                suggestions.add(s)

        # Vocabulary prefix/substring match
        for v in vocab:
            vv = _clean_token(v)
            if vv and vv != w and _is_useful(vv):
                if w in vv or vv in w or (len(w) >= 3 and vv[:3] == w[:3]):
                    suggestions.add(vv)

        # Score and return top N
        scored = self.score_keywords(list(suggestions), cfg.profile)
        return [sk.word for sk in scored[:max_suggestions]]


# ─────────────────────────────────────────────────────────────────────────────
# § 6  SIMPLE FUNCTIONAL INTERFACES
# ─────────────────────────────────────────────────────────────────────────────

def process_keywords(
    raw_input: Union[str, Sequence[str]],
    cfg:       Optional[Settings] = None,
) -> list[str]:
    """
    Process raw keyword input and return a clean ordered list.

    Simple functional interface for callers that don't need KeywordSet.

    Args:
        raw_input: Keyword string or list of strings.
        cfg:       Active Settings.

    Returns:
        Clean, validated, profile-boosted keyword list.
    """
    engine = KeywordEngine()
    ks     = engine.process(raw_input, cfg)
    return ks.final


def extract_keywords(
    text: str,
    cfg:  Optional[Settings] = None,
) -> list[str]:
    """
    Extract brand-relevant keywords from free-form product description text.

    Args:
        text: Natural language product description.
        cfg:  Active Settings.

    Returns:
        Scored, ordered list of keywords extracted from the text.
    """
    engine = KeywordEngine()
    return engine.extract_from_text(text, cfg)
