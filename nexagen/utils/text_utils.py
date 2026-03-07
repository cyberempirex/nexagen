"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  utils/text_utils.py  ·  Text manipulation and linguistic utilities         ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Pure functions only — no I/O, no side effects, no state.
Every function in this module operates on strings and returns strings or
primitive values.  All are importable independently.
"""

from __future__ import annotations

import re
import string
import unicodedata
from functools import lru_cache
from typing import Generator, Iterator, Sequence

from ..config.constants import (
    CONSONANTS,
    FORBIDDEN_SEQUENCES,
    RARE_CONSONANTS,
    STRONG_START_CONSONANTS,
    VOWELS,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """
    Full normalization pipeline:
      1. Unicode NFC normalization
      2. Strip accents / diacritics → ASCII equivalents
      3. Lowercase
      4. Strip leading / trailing whitespace

    Examples:
        >>> normalize("Café")
        'cafe'
        >>> normalize("  NEXAGEN  ")
        'nexagen'
    """
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def to_title(text: str) -> str:
    """
    Capitalize the first letter, leave the rest as-is.
    Unlike str.title(), does NOT capitalize after punctuation.

    Examples:
        >>> to_title("paperdesk")
        'Paperdesk'
    """
    if not text:
        return text
    return text[0].upper() + text[1:]


def to_camel(text: str) -> str:
    """
    Convert a space/underscore/hyphen-separated string to CamelCase.

    Examples:
        >>> to_camel("paper desk")
        'PaperDesk'
        >>> to_camel("note_garden")
        'NoteGarden'
    """
    parts = re.split(r"[\s_\-]+", text.strip())
    return "".join(p.capitalize() for p in parts if p)


def to_snake(text: str) -> str:
    """
    Convert CamelCase or space-separated text to snake_case.

    Examples:
        >>> to_snake("PaperDesk")
        'paper_desk'
        >>> to_snake("DataBridge API")
        'databridge_api'
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return re.sub(r"[\s\-]+", "_", s).lower()


def to_kebab(text: str) -> str:
    """
    Convert to kebab-case (lowercased, hyphen-separated).

    Examples:
        >>> to_kebab("PaperDesk Hub")
        'paper-desk-hub'
    """
    return to_snake(text).replace("_", "-")


def slugify(text: str) -> str:
    """
    Produce a URL-safe slug: lowercase, alphanumeric + hyphens only.

    Examples:
        >>> slugify("NoteGarden — your workspace")
        'notegarden-your-workspace'
    """
    normalized = normalize(text)
    slug = re.sub(r"[^a-z0-9\s\-]", "", normalized)
    slug = re.sub(r"[\s\-]+", "-", slug)
    return slug.strip("-")


def strip_non_alpha(text: str) -> str:
    """Remove all non-alphabetic characters."""
    return re.sub(r"[^a-zA-Z]", "", text)


def strip_punctuation(text: str) -> str:
    """Remove all punctuation characters."""
    return text.translate(str.maketrans("", "", string.punctuation))


# ─────────────────────────────────────────────────────────────────────────────
# § 2  BRAND NAME FORMATTING
# ─────────────────────────────────────────────────────────────────────────────

def format_brand_name(name: str) -> str:
    """
    Apply canonical brand formatting: strip non-alpha, capitalize first letter.
    The primary format used when displaying generated names to the user.

    Examples:
        >>> format_brand_name("paperdesk")
        'Paperdesk'
        >>> format_brand_name("data_bridge")
        'DataBridge'
    """
    clean = strip_non_alpha(name).lower()
    return to_title(clean) if "_" not in name else to_camel(name)


def brand_variants(name: str) -> dict[str, str]:
    """
    Return all common formatting variants of a brand name.

    Returns:
        dict with keys: raw, display, camel, upper, domain, slug
    """
    clean = normalize(strip_non_alpha(name))
    return {
        "raw":     clean,
        "display": to_title(clean),
        "camel":   to_camel(clean),
        "upper":   clean.upper(),
        "domain":  clean,           # lowercase, no separators — for domains
        "slug":    slugify(clean),
    }


# ─────────────────────────────────────────────────────────────────────────────
# § 3  TOKENISATION & WORD EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-zA-Z]{2,}")


def extract_words(text: str) -> list[str]:
    """
    Extract all alphabetic tokens of length >= 2, lowercased.

    Examples:
        >>> extract_words("AI platform for note-taking in 2026")
        ['AI', 'platform', 'for', 'note', 'taking', 'in']
        # (lowercased by caller or returned as-is depending on use-case)
    """
    return [m.group().lower() for m in _WORD_RE.finditer(text)]


def extract_keywords(text: str, min_len: int = 3) -> list[str]:
    """
    Extract meaningful keywords from free-form idea text.
    Filters out very short words and common stop words.

    Args:
        text:    User-provided idea string.
        min_len: Minimum character length to keep.

    Returns:
        Deduplicated list of keywords, order-preserved.
    """
    stop_words = {
        "the", "and", "for", "with", "this", "that", "are", "was",
        "were", "from", "into", "they", "have", "has", "can", "will",
        "its", "our", "your", "you", "all", "not", "but", "more",
        "also", "very", "just", "been", "like", "make", "some",
        "than", "then", "them", "when", "which", "who", "how",
    }
    seen: set[str] = set()
    result: list[str] = []
    for word in extract_words(text):
        if len(word) >= min_len and word not in stop_words and word not in seen:
            seen.add(word)
            result.append(word)
    return result


def split_camel(text: str) -> list[str]:
    """
    Split a CamelCase string into its component words.

    Examples:
        >>> split_camel("PaperDeskHub")
        ['Paper', 'Desk', 'Hub']
        >>> split_camel("openAIplatform")
        ['open', 'AI', 'platform']
    """
    return re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]|\d+",
                      text)


def tokenize_name(name: str) -> list[str]:
    """
    Decompose a compound brand name into its likely component words.
    Handles CamelCase, hyphens, underscores, and pure lowercase runs.

    Examples:
        >>> tokenize_name("PaperDesk")
        ['paper', 'desk']
        >>> tokenize_name("data-bridge")
        ['data', 'bridge']
        >>> tokenize_name("stackhub")
        ['stackhub']   # single word — can't decompose without a dictionary
    """
    # Try explicit separators first
    if re.search(r"[-_\s]", name):
        return [t.lower() for t in re.split(r"[-_\s]+", name) if t]
    # Try CamelCase
    parts = split_camel(name)
    if len(parts) > 1:
        return [p.lower() for p in parts]
    # Return as single token
    return [name.lower()]


# ─────────────────────────────────────────────────────────────────────────────
# § 4  PHONETICS & LINGUISTIC ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=2048)
def count_vowels(word: str) -> int:
    """Return the number of vowel characters in a word."""
    return sum(1 for c in word.lower() if c in VOWELS)


@lru_cache(maxsize=2048)
def count_consonants(word: str) -> int:
    """Return the number of consonant characters in a word."""
    return sum(1 for c in word.lower() if c in CONSONANTS)


@lru_cache(maxsize=2048)
def vowel_ratio(word: str) -> float:
    """Return the ratio of vowels to total alphabetic characters (0.0–1.0)."""
    alpha = [c for c in word.lower() if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for c in alpha if c in VOWELS) / len(alpha)


@lru_cache(maxsize=2048)
def syllable_count(word: str) -> int:
    """
    Estimate syllable count using a vowel-group heuristic.
    Accurate enough for scoring; not a full phonetic parser.

    Examples:
        >>> syllable_count("nexagen")   # → 3
        >>> syllable_count("data")      # → 2
    """
    word = word.lower().strip()
    if not word:
        return 0
    word = re.sub(r"[^a-z]", "", word)
    # Count vowel groups (consecutive vowels = one syllable)
    groups = re.findall(r"[aeiou]+", word)
    count = len(groups)
    # Silent 'e' at end: "forge" → 1 syllable not 2
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


@lru_cache(maxsize=2048)
def max_consonant_run(word: str) -> int:
    """
    Return the length of the longest consecutive consonant sequence.

    Examples:
        >>> max_consonant_run("strength")   # → 4  (ngth)
        >>> max_consonant_run("nexagen")    # → 2  (nx)
    """
    word = word.lower()
    max_run = 0
    current = 0
    for c in word:
        if c in CONSONANTS:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


@lru_cache(maxsize=2048)
def alternation_score(word: str) -> float:
    """
    Score how well vowels and consonants alternate (0.0–1.0).
    Perfect CVCV or VCVC patterns score 1.0.
    Clusters of same type reduce the score.

    Examples:
        >>> alternation_score("nexagen")   # high
        >>> alternation_score("strength")  # lower
    """
    word = word.lower()
    alpha = [c for c in word if c.isalpha()]
    if len(alpha) < 2:
        return 1.0
    transitions = sum(
        1 for i in range(len(alpha) - 1)
        if (alpha[i] in VOWELS) != (alpha[i + 1] in VOWELS)
    )
    return transitions / (len(alpha) - 1)


@lru_cache(maxsize=2048)
def has_forbidden_sequence(word: str) -> bool:
    """Return True if the word contains any phonetically forbidden bigram."""
    word = word.lower()
    return any(seq in word for seq in FORBIDDEN_SEQUENCES)


def forbidden_sequence_count(word: str) -> int:
    """Return the number of distinct forbidden sequences present."""
    word = word.lower()
    return sum(1 for seq in FORBIDDEN_SEQUENCES if seq in word)


@lru_cache(maxsize=2048)
def starts_with_strong_consonant(word: str) -> bool:
    """Return True if the word begins with a memorability-boosting consonant."""
    return bool(word) and word[0].lower() in STRONG_START_CONSONANTS


@lru_cache(maxsize=2048)
def ends_with_vowel(word: str) -> bool:
    """Return True if the word ends with a vowel."""
    return bool(word) and word[-1].lower() in VOWELS


@lru_cache(maxsize=2048)
def has_alliteration(word: str) -> bool:
    """Return True if the word has repeated starting-sound patterns (rough)."""
    word = word.lower()
    # Simple check: same character appears in two different positions
    if len(word) < 4:
        return False
    return (
        word[0] == word[2]
        or (len(word) > 3 and word[0] == word[3])
        or (len(word) > 4 and word[1] == word[3])
    )


@lru_cache(maxsize=2048)
def is_pronounceable(word: str, threshold: float = 0.35) -> bool:
    """
    Quick heuristic: True if the word is likely pronounceable by an
    English speaker.

    Criteria:
      - Vowel ratio ≥ threshold (default 35 %)
      - No forbidden sequences
      - Max consonant run ≤ 3
    """
    word = word.lower()
    if not word.isalpha():
        return False
    return (
        vowel_ratio(word) >= threshold
        and not has_forbidden_sequence(word)
        and max_consonant_run(word) <= 3
    )


@lru_cache(maxsize=2048)
def has_rare_consonants(word: str) -> bool:
    """Return True if the word contains rare/unusual consonants (q,x,z,j,v,k)."""
    return any(c in RARE_CONSONANTS for c in word.lower())


def rare_consonant_count(word: str) -> int:
    """Count how many rare consonants appear in the word."""
    return sum(1 for c in word.lower() if c in RARE_CONSONANTS)


# ─────────────────────────────────────────────────────────────────────────────
# § 5  COMPOUND NAME UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def combine_parts(*parts: str, separator: str = "") -> str:
    """
    Join word parts into a compound name.

    Args:
        *parts:    Word fragments to combine.
        separator: String placed between parts ("", "-", " ", etc.)

    Examples:
        >>> combine_parts("paper", "desk")
        'paperdesk'
        >>> combine_parts("paper", "desk", separator="-")
        'paper-desk'
    """
    return separator.join(p.strip().lower() for p in parts if p.strip())


def truncate_name(name: str, max_len: int) -> str:
    """
    Truncate a name to max_len characters, removing trailing consonant
    clusters for a cleaner result.

    Examples:
        >>> truncate_name("datacentercloud", 10)
        'datacenter'
    """
    if len(name) <= max_len:
        return name
    truncated = name[:max_len]
    # Walk back to the last vowel to avoid ending on an ugly consonant cluster
    for i in range(len(truncated) - 1, max(len(truncated) - 4, 0), -1):
        if truncated[i] in VOWELS:
            return truncated[: i + 1]
    return truncated


def blend_words(word_a: str, word_b: str) -> list[str]:
    """
    Generate portmanteau blends of two words.
    Returns up to 3 blending options.

    Examples:
        >>> blend_words("nexus", "agent")
        ['nexagent', 'nexagen', 'nxagent']
    """
    a = word_a.lower()
    b = word_b.lower()
    blends: list[str] = []

    # Strategy 1: Take first half of A + full B
    mid_a = len(a) // 2
    blends.append(a[:mid_a] + b)

    # Strategy 2: Take A up to last vowel + B from first vowel
    a_cut = len(a)
    for i in range(len(a) - 1, -1, -1):
        if a[i] in VOWELS:
            a_cut = i + 1
            break
    b_start = 0
    for i, c in enumerate(b):
        if c in VOWELS:
            b_start = i
            break
    blend2 = a[:a_cut] + b[b_start:]
    if blend2 not in blends:
        blends.append(blend2)

    # Strategy 3: Consonant-only prefix of A + B
    a_consonants = "".join(c for c in a if c in CONSONANTS)
    if a_consonants:
        blend3 = a_consonants[:2] + b
        if blend3 not in blends:
            blends.append(blend3)

    # Filter: must be at least 4 chars and pronounceable-ish
    return [b for b in blends if 4 <= len(b) <= 12 and b != a and b != b]


def acronym(phrase: str) -> str:
    """
    Extract the acronym (first letter of each word) from a phrase.

    Examples:
        >>> acronym("neural engine for data")
        'NEFD'
    """
    words = phrase.split()
    return "".join(w[0].upper() for w in words if w).upper()


def backronym(letters: str, word_bank: list[str]) -> str | None:
    """
    Attempt to build a phrase where each letter of ``letters`` is the
    first letter of a word from ``word_bank``.

    Args:
        letters:   Uppercase acronym, e.g. "NEXO"
        word_bank: List of candidate words to use.

    Returns:
        A phrase string, or None if not all letters could be matched.
    """
    letters = letters.upper()
    bank_by_letter: dict[str, list[str]] = {}
    for w in word_bank:
        if w:
            bank_by_letter.setdefault(w[0].upper(), []).append(w.capitalize())

    result: list[str] = []
    for letter in letters:
        candidates = bank_by_letter.get(letter)
        if not candidates:
            return None
        result.append(candidates[0])
    return " ".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# § 6  STRING SIMILARITY (non-Levenshtein)
# ─────────────────────────────────────────────────────────────────────────────

def common_prefix_length(a: str, b: str) -> int:
    """Return the length of the longest common prefix of two strings."""
    a, b = a.lower(), b.lower()
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i


def common_suffix_length(a: str, b: str) -> int:
    """Return the length of the longest common suffix."""
    return common_prefix_length(a[::-1], b[::-1])


def soundex(word: str) -> str:
    """
    Classic Soundex phonetic algorithm implementation.
    Maps similar-sounding words to the same code.

    Examples:
        >>> soundex("Smith")  → 'S530'
        >>> soundex("Smythe") → 'S530'
    """
    word = word.upper()
    if not word:
        return "0000"

    code_map = {
        "B": "1", "F": "1", "P": "1", "V": "1",
        "C": "2", "G": "2", "J": "2", "K": "2",
        "Q": "2", "S": "2", "X": "2", "Z": "2",
        "D": "3", "T": "3",
        "L": "4",
        "M": "5", "N": "5",
        "R": "6",
    }

    first_letter = word[0]
    coded = first_letter
    prev_code = code_map.get(first_letter, "0")

    for char in word[1:]:
        code = code_map.get(char, "0")
        if code != "0" and code != prev_code:
            coded += code
        prev_code = code

    coded = (coded + "000")[:4]
    return coded


def metaphone(word: str) -> str:
    """
    Simplified Double Metaphone-inspired phonetic key.
    Not a full implementation — provides a fast approximation
    suitable for brand name similarity checks.
    """
    word = word.lower()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return ""

    # Initial letter transformations
    substitutions = [
        (r"^ae",   "E"),  (r"^gn",   "N"),  (r"^kn",   "N"),
        (r"^pn",   "N"),  (r"^wr",   "R"),  (r"^wh",   "W"),
        (r"ph",    "F"),  (r"ck",    "K"),  (r"qu",    "K"),
        (r"sch",   "SK"), (r"tch",   "X"),  (r"th",    "0"),
        (r"sh",    "X"),  (r"ch",    "X"),
        (r"([aeiou])h", r"\1"),             # silent h after vowel
        (r"([aeiou])\1+", r"\1"),           # collapse double vowels
        (r"[aeiou]", "A"),                  # all vowels → A
    ]

    result = word
    for pattern, replacement in substitutions:
        result = re.sub(pattern, replacement, result)

    # Remove trailing vowels
    result = result.rstrip("A")
    return result.upper()[:6]  # cap at 6 chars


def sounds_like(a: str, b: str) -> bool:
    """
    Quick phonetic similarity check using Soundex.
    Returns True if both words share the same Soundex code.
    """
    return soundex(a) == soundex(b)


# ─────────────────────────────────────────────────────────────────────────────
# § 7  TEXT DISPLAY UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def truncate_display(text: str, max_width: int, ellipsis: str = "…") -> str:
    """
    Truncate text for terminal display, appending an ellipsis if cut.

    Examples:
        >>> truncate_display("PlatformNamingEngine", 15)
        'PlatformNaming…'
    """
    if len(text) <= max_width:
        return text
    return text[: max_width - len(ellipsis)] + ellipsis


def pad_center(text: str, width: int, fill: str = " ") -> str:
    """Center-pad text to the given width."""
    return text.center(width, fill)


def wrap_text(text: str, width: int = 72) -> str:
    """
    Wrap text to the given width while preserving paragraph breaks.
    """
    paragraphs = text.split("\n\n")
    wrapped = []
    for para in paragraphs:
        # Collapse internal whitespace
        clean = re.sub(r"\s+", " ", para.strip())
        if len(clean) <= width:
            wrapped.append(clean)
            continue
        # Manual word-wrap
        words = clean.split()
        lines: list[str] = []
        current: list[str] = []
        current_len = 0
        for word in words:
            if current_len + len(word) + len(current) > width:
                lines.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += len(word)
        if current:
            lines.append(" ".join(current))
        wrapped.append("\n".join(lines))
    return "\n\n".join(wrapped)


def number_to_ordinal(n: int) -> str:
    """
    Convert an integer to its English ordinal string.

    Examples:
        >>> number_to_ordinal(1)  → '1st'
        >>> number_to_ordinal(12) → '12th'
    """
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pluralize(word: str, count: int) -> str:
    """
    Very simple English pluralization (handles -s / -es).
    """
    if count == 1:
        return word
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and not word[-2:-1] in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


# ─────────────────────────────────────────────────────────────────────────────
# § 8  GENERATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def iter_ngrams(text: str, n: int) -> Iterator[str]:
    """
    Yield all character n-grams from text.

    Examples:
        >>> list(iter_ngrams("nexo", 2))
        ['ne', 'ex', 'xo']
    """
    for i in range(len(text) - n + 1):
        yield text[i: i + n]


def unique_preserve_order(items: Sequence[str]) -> list[str]:
    """
    Return a deduplicated list preserving original insertion order.
    Case-insensitive: keeps the first occurrence.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def filter_by_length(
    names: list[str],
    min_len: int,
    max_len: int,
) -> list[str]:
    """Return only names whose length is within [min_len, max_len]."""
    return [n for n in names if min_len <= len(n) <= max_len]


def sort_by_length(names: list[str], ascending: bool = True) -> list[str]:
    """Sort names by character length."""
    return sorted(names, key=len, reverse=not ascending)


def contains_digit(text: str) -> bool:
    """Return True if text contains any digit character."""
    return any(c.isdigit() for c in text)


def is_all_lowercase_alpha(text: str) -> bool:
    """Return True if text is non-empty and contains only lowercase letters."""
    return bool(text) and text.isalpha() and text == text.lower()


def char_frequency(word: str) -> dict[str, int]:
    """Return a character frequency dict for a word."""
    freq: dict[str, int] = {}
    for c in word.lower():
        if c.isalpha():
            freq[c] = freq.get(c, 0) + 1
    return freq


def longest_common_substring(a: str, b: str) -> str:
    """
    Return the longest common substring of two strings.
    O(n·m) — fine for name-length strings.
    """
    a, b = a.lower(), b.lower()
    m, n = len(a), len(b)
    best = ""
    # dp[i][j] = length of LCS ending at a[i-1], b[j-1]
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                if dp[i][j] > len(best):
                    best = a[i - dp[i][j]: i]
            else:
                dp[i][j] = 0
    return best
