"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  utils/validators.py  ·  Input validation and name constraint checking      ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

All validation functions return typed result objects so callers can
inspect reasons for rejection without string-parsing error messages.

Design principles:
  • Never raise exceptions — return ValidationResult instead
  • Pure functions, no side effects
  • Composable — validators can be chained via validate_all()
  • Fast — suitable for validating hundreds of generated names per second
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Callable, Iterable, Sequence

from ..config.constants import (
    BRAND_BLACKLIST_SEED,
    CONSONANTS,
    FORBIDDEN_SEQUENCES,
    MAX_KEYWORD_LENGTH,
    MAX_KEYWORDS_PER_RUN,
    NAME_LENGTH_HARD_MAX,
    NAME_LENGTH_HARD_MIN,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    VOWELS,
    Profile,
    StyleMode,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  RESULT TYPES
# ─────────────────────────────────────────────────────────────────────────────

@unique
class Severity(str, Enum):
    """How serious a validation issue is."""
    ERROR   = "error"    # hard failure — name must be rejected
    WARNING = "warning"  # soft issue  — name can be kept but flagged
    INFO    = "info"     # advisory    — informational only


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""
    code:     str       # machine-readable identifier e.g. "NAME_TOO_SHORT"
    message:  str       # human-readable description
    severity: Severity = Severity.ERROR

    def is_error(self) -> bool:
        return self.severity == Severity.ERROR

    def is_warning(self) -> bool:
        return self.severity == Severity.WARNING

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()}] {self.code}: {self.message}"


@dataclass
class ValidationResult:
    """Aggregated result of one or more validation checks."""
    value:  str                           # the input that was validated
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """True only if there are no ERROR-severity issues."""
        return not any(i.is_error() for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.is_error()]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.is_warning()]

    @property
    def error_codes(self) -> list[str]:
        return [i.code for i in self.errors]

    def add(self, issue: ValidationIssue) -> "ValidationResult":
        """Append an issue and return self for chaining."""
        self.issues.append(issue)
        return self

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another result's issues into this one."""
        self.issues.extend(other.issues)
        return self

    def first_error_message(self) -> str | None:
        errs = self.errors
        return errs[0].message if errs else None

    def summary(self) -> str:
        if self.valid:
            w = len(self.warnings)
            return f"✔ valid  ({w} warning{'s' if w != 1 else ''})" if w else "✔ valid"
        return f"✘ invalid  —  {', '.join(self.error_codes)}"

    def __bool__(self) -> bool:
        return self.valid

    def __repr__(self) -> str:
        return f"ValidationResult(valid={self.valid}, issues={len(self.issues)})"


# Convenience constructor
def _err(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=Severity.ERROR)


def _warn(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=Severity.WARNING)


def _info(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=Severity.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# § 2  BRAND NAME VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

def validate_name_length(
    name: str,
    min_len: int = NAME_LENGTH_HARD_MIN,
    max_len: int = NAME_LENGTH_HARD_MAX,
    ideal_min: int = NAME_LENGTH_IDEAL_MIN,
    ideal_max: int = NAME_LENGTH_IDEAL_MAX,
) -> ValidationResult:
    """
    Validate that a brand name falls within acceptable length bounds.

    Hard limits (min_len / max_len) produce ERRORs.
    Ideal range violations produce WARNINGs.
    """
    r = ValidationResult(value=name)
    n = len(name)

    if n < min_len:
        r.add(_err("NAME_TOO_SHORT",
                   f"Name '{name}' is {n} character(s) — minimum is {min_len}."))
        return r

    if n > max_len:
        r.add(_err("NAME_TOO_LONG",
                   f"Name '{name}' is {n} characters — maximum is {max_len}."))
        return r

    if n < ideal_min:
        r.add(_warn("NAME_BELOW_IDEAL_LENGTH",
                    f"Name '{name}' ({n} chars) is shorter than ideal "
                    f"({ideal_min}–{ideal_max}). May be too short for a brand."))

    if n > ideal_max:
        r.add(_warn("NAME_ABOVE_IDEAL_LENGTH",
                    f"Name '{name}' ({n} chars) is longer than ideal "
                    f"({ideal_min}–{ideal_max}). May be harder to remember."))
    return r


def validate_name_characters(name: str) -> ValidationResult:
    """
    Validate that a brand name contains only alphabetic characters
    (no digits, spaces, hyphens, or special characters).
    """
    r = ValidationResult(value=name)

    if not name:
        r.add(_err("NAME_EMPTY", "Name cannot be empty."))
        return r

    if not name.isalpha():
        bad_chars = set(c for c in name if not c.isalpha())
        r.add(_err("NAME_INVALID_CHARACTERS",
                   f"Name '{name}' contains non-alphabetic characters: "
                   f"{sorted(bad_chars)!r}. Brand names should be letters only."))

    if name != name.lower():
        r.add(_warn("NAME_NOT_LOWERCASE",
                    f"Name '{name}' is not fully lowercase. "
                    "The engine works with lowercase internally."))
    return r


def validate_name_phonetics(name: str) -> ValidationResult:
    """
    Validate the phonetic quality of a brand name.

    Checks:
      - No forbidden bigrams (double vowels, ugly consonant pairs)
      - Consonant run length ≤ 3
      - Vowel ratio within a reasonable range
      - Does not consist entirely of consonants or vowels
    """
    r = ValidationResult(value=name)
    w = name.lower()

    # Forbidden sequences
    for seq in FORBIDDEN_SEQUENCES:
        if seq in w:
            r.add(_err("NAME_FORBIDDEN_SEQUENCE",
                       f"Name '{name}' contains forbidden phonetic sequence '{seq}'. "
                       "This pattern makes the name hard to pronounce."))
            break  # report first occurrence only

    # Consonant run
    max_run = 0
    current_run = 0
    for c in w:
        if c in CONSONANTS:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0

    if max_run > 4:
        r.add(_err("NAME_CONSONANT_CLUSTER",
                   f"Name '{name}' has {max_run} consecutive consonants. "
                   "Clusters over 4 are almost unpronounceable."))
    elif max_run > 2:
        r.add(_warn("NAME_CONSONANT_RUN",
                    f"Name '{name}' has a consonant run of {max_run}. "
                    "Runs of 3 are acceptable but may reduce clarity."))

    # Vowel check
    alpha = [c for c in w if c.isalpha()]
    if alpha:
        vowel_count = sum(1 for c in alpha if c in VOWELS)
        ratio = vowel_count / len(alpha)

        if ratio == 0:
            r.add(_err("NAME_NO_VOWELS",
                       f"Name '{name}' has no vowels — not pronounceable."))
        elif ratio < 0.20:
            r.add(_warn("NAME_LOW_VOWEL_RATIO",
                        f"Name '{name}' has only {ratio:.0%} vowels. "
                        "Low vowel ratio often indicates poor pronounceability."))
        elif ratio > 0.80:
            r.add(_warn("NAME_HIGH_VOWEL_RATIO",
                        f"Name '{name}' is {ratio:.0%} vowels. "
                        "Very vowel-heavy names can feel weak."))

    return r


def validate_name_uniqueness(
    name: str,
    existing_names: Sequence[str],
    max_distance: int = 2,
) -> ValidationResult:
    """
    Check that a name is sufficiently different from all names in
    existing_names using Levenshtein distance.

    Args:
        name:           Candidate name to check.
        existing_names: Pool of already-accepted names.
        max_distance:   Distance threshold; ≤ this = too similar.
    """
    from .levenshtein import levenshtein as _lev  # local to avoid circular

    r = ValidationResult(value=name)
    name_lower = name.lower()

    for other in existing_names:
        if other.lower() == name_lower:
            r.add(_err("NAME_EXACT_DUPLICATE",
                       f"'{name}' is identical to existing name '{other}'."))
            return r
        dist = _lev(name_lower, other.lower())
        if dist <= max_distance:
            r.add(_err("NAME_TOO_SIMILAR",
                       f"'{name}' is too similar to '{other}' "
                       f"(Levenshtein distance = {dist})."))
            return r

    return r


def validate_trademark_safety(
    name: str,
    blacklist: Sequence[str] | None = None,
    max_distance: int = 3,
) -> ValidationResult:
    """
    Check a name against a blacklist of protected / well-known brands.

    Uses both exact substring matching and Levenshtein distance.
    """
    from .levenshtein import trademark_risk  # local import

    r = ValidationResult(value=name)
    brands = list(blacklist) if blacklist is not None else list(BRAND_BLACKLIST_SEED)

    hit = trademark_risk(name, brands, low_threshold=max_distance)

    if hit.risk_level == "high":
        r.add(_err("TM_HIGH_RISK",
                   f"'{name}' is dangerously similar to '{hit.matched_brand}' "
                   f"(distance={hit.distance}). High trademark risk."))
    elif hit.risk_level == "medium":
        r.add(_warn("TM_MEDIUM_RISK",
                    f"'{name}' resembles '{hit.matched_brand}' "
                    f"(distance={hit.distance}). Possible trademark conflict."))
    elif hit.risk_level == "low":
        r.add(_info("TM_LOW_RISK",
                    f"'{name}' has minor resemblance to '{hit.matched_brand}' "
                    f"(distance={hit.distance}). Low trademark risk."))

    return r


def validate_common_word(
    name: str,
    common_words: frozenset[str] | None = None,
) -> ValidationResult:
    """
    Warn if the name is a plain common English word.

    If common_words is None, uses the WORD_FILTER singleton from
    the WordFilter class in nexagen.py / dataset_loader.py.
    """
    r = ValidationResult(value=name)
    name_lower = name.lower()

    if common_words is not None:
        if name_lower in common_words:
            r.add(_warn("NAME_COMMON_WORD",
                        f"'{name}' is a common English word. "
                        "Plain dictionary words score lower on brand uniqueness."))
    return r


# ─────────────────────────────────────────────────────────────────────────────
# § 3  DOMAIN VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

# ICANN-compatible domain label pattern (no leading/trailing hyphens,
# no double-hyphen in positions 3-4 unless it's an IDN prefix)
_DOMAIN_LABEL_RE = re.compile(
    r"^(?!-)[a-z0-9\-]{1,63}(?<!-)$",
    re.IGNORECASE,
)
_DOMAIN_FULL_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)"
    r"+[a-z]{2,}$",
    re.IGNORECASE,
)


def validate_domain_label(label: str) -> ValidationResult:
    """
    Validate a single DNS label (the part between dots).

    ICANN rules:
      - 1–63 characters
      - Alphanumeric or hyphens
      - Cannot start or end with a hyphen
      - Cannot contain consecutive hyphens in positions 3-4 (IDN prefix)
    """
    r = ValidationResult(value=label)

    if not label:
        r.add(_err("DOMAIN_LABEL_EMPTY", "Domain label cannot be empty."))
        return r

    if len(label) > 63:
        r.add(_err("DOMAIN_LABEL_TOO_LONG",
                   f"Domain label '{label}' is {len(label)} chars (max 63)."))

    if not re.match(r"^[a-z0-9\-]+$", label, re.IGNORECASE):
        bad = set(c for c in label if not re.match(r"[a-z0-9\-]", c, re.IGNORECASE))
        r.add(_err("DOMAIN_LABEL_INVALID_CHARS",
                   f"Domain label '{label}' contains invalid characters: "
                   f"{sorted(bad)!r}."))

    if label.startswith("-") or label.endswith("-"):
        r.add(_err("DOMAIN_LABEL_HYPHEN_POSITION",
                   f"Domain label '{label}' cannot start or end with a hyphen."))

    if len(label) >= 4 and label[2:4] == "--":
        r.add(_warn("DOMAIN_LABEL_IDN_PREFIX",
                    f"'{label}' has '--' at positions 3-4. "
                    "This is reserved for internationalized domains."))

    return r


def validate_domain_name(domain: str) -> ValidationResult:
    """
    Validate a full domain name including TLD (e.g. nexagen.io).
    """
    r = ValidationResult(value=domain)

    if not domain:
        r.add(_err("DOMAIN_EMPTY", "Domain name cannot be empty."))
        return r

    if "." not in domain:
        r.add(_err("DOMAIN_NO_TLD",
                   f"'{domain}' has no TLD. Domains require at least one dot."))
        return r

    parts = domain.lower().split(".")
    for part in parts:
        label_result = validate_domain_label(part)
        r.merge(label_result)

    if len(domain) > 253:
        r.add(_err("DOMAIN_TOO_LONG",
                   f"Domain '{domain}' is {len(domain)} chars — max 253."))

    return r


def validate_tld(tld: str, allowed_tlds: Sequence[str] | None = None) -> ValidationResult:
    """
    Validate a TLD string and optionally check it against a whitelist.
    """
    r = ValidationResult(value=tld)
    tld_clean = tld.lstrip(".").lower()

    if not tld_clean.isalpha():
        r.add(_err("TLD_INVALID_CHARS",
                   f"TLD '{tld}' should contain only alphabetic characters."))

    if len(tld_clean) < 2:
        r.add(_err("TLD_TOO_SHORT", f"TLD '{tld}' must be at least 2 characters."))

    if len(tld_clean) > 24:
        r.add(_warn("TLD_UNUSUAL_LENGTH",
                    f"TLD '{tld}' is {len(tld_clean)} chars — unusually long."))

    if allowed_tlds and tld_clean not in [t.lstrip(".").lower() for t in allowed_tlds]:
        r.add(_warn("TLD_NOT_IN_ALLOWED_LIST",
                    f"TLD '{tld}' is not in the configured TLD list."))

    return r


# ─────────────────────────────────────────────────────────────────────────────
# § 4  KEYWORD / INPUT VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

def validate_keyword(keyword: str) -> ValidationResult:
    """
    Validate a single keyword entered by the user as an idea/seed.

    Checks:
      - Not empty
      - Length within MAX_KEYWORD_LENGTH
      - Only printable ASCII (warns on Unicode)
      - Not purely numeric
    """
    r = ValidationResult(value=keyword)

    stripped = keyword.strip()
    if not stripped:
        r.add(_err("KEYWORD_EMPTY", "Keyword cannot be empty."))
        return r

    if len(stripped) > MAX_KEYWORD_LENGTH:
        r.add(_err("KEYWORD_TOO_LONG",
                   f"Keyword '{stripped[:20]}…' exceeds {MAX_KEYWORD_LENGTH} chars."))

    if stripped.isnumeric():
        r.add(_err("KEYWORD_NUMERIC",
                   f"Keyword '{stripped}' is purely numeric — not useful for naming."))

    # Unicode check
    try:
        stripped.encode("ascii")
    except UnicodeEncodeError:
        non_ascii = [c for c in stripped if ord(c) > 127]
        r.add(_warn("KEYWORD_NON_ASCII",
                    f"Keyword '{stripped}' contains non-ASCII characters: "
                    f"{non_ascii!r}. These will be normalized."))

    # Very short
    if len(stripped) < 2:
        r.add(_warn("KEYWORD_VERY_SHORT",
                    f"Keyword '{stripped}' is very short. "
                    "Short seeds produce limited name variety."))

    return r


def validate_keywords(keywords: list[str]) -> ValidationResult:
    """
    Validate a list of user-supplied keywords.
    Checks the list as a whole and each keyword individually.
    """
    combined = ValidationResult(value=str(keywords))

    if not keywords:
        combined.add(_err("KEYWORDS_EMPTY", "At least one keyword is required."))
        return combined

    if len(keywords) > MAX_KEYWORDS_PER_RUN:
        combined.add(_warn("KEYWORDS_TOO_MANY",
                            f"Provided {len(keywords)} keywords — max recommended "
                            f"is {MAX_KEYWORDS_PER_RUN}. Using first {MAX_KEYWORDS_PER_RUN}."))

    seen: set[str] = set()
    for kw in keywords:
        if kw.lower() in seen:
            combined.add(_warn("KEYWORD_DUPLICATE",
                               f"Duplicate keyword '{kw}' will be ignored."))
        seen.add(kw.lower())
        kw_result = validate_keyword(kw)
        combined.merge(kw_result)

    return combined


# ─────────────────────────────────────────────────────────────────────────────
# § 5  SETTINGS / CONFIG VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

def validate_count(count: int) -> ValidationResult:
    """Validate the name generation count parameter."""
    from ..config.constants import GEN_MAX_COUNT, GEN_MIN_COUNT

    r = ValidationResult(value=str(count))
    if count < GEN_MIN_COUNT:
        r.add(_err("COUNT_TOO_LOW",
                   f"Count {count} is below minimum ({GEN_MIN_COUNT})."))
    elif count > GEN_MAX_COUNT:
        r.add(_err("COUNT_TOO_HIGH",
                   f"Count {count} exceeds maximum ({GEN_MAX_COUNT})."))
    elif count > 100:
        r.add(_warn("COUNT_LARGE",
                    f"Count {count} is large — generation may take several seconds."))
    return r


def validate_length_range(min_len: int, max_len: int) -> ValidationResult:
    """Validate min/max length parameters."""
    r = ValidationResult(value=f"{min_len}-{max_len}")
    if min_len < 1:
        r.add(_err("LENGTH_MIN_INVALID", "min_len must be at least 1."))
    if max_len > NAME_LENGTH_HARD_MAX:
        r.add(_err("LENGTH_MAX_TOO_HIGH",
                   f"max_len {max_len} exceeds hard limit {NAME_LENGTH_HARD_MAX}."))
    if min_len >= max_len:
        r.add(_err("LENGTH_RANGE_INVALID",
                   f"min_len ({min_len}) must be strictly less than max_len ({max_len})."))
    return r


def validate_profile(profile: str) -> ValidationResult:
    """Validate an industry profile string."""
    r = ValidationResult(value=profile)
    choices = Profile.choices()
    if profile not in choices:
        r.add(_err("PROFILE_INVALID",
                   f"Unknown profile '{profile}'. "
                   f"Valid options: {choices}"))
    return r


def validate_style_mode(style: str) -> ValidationResult:
    """Validate a style mode string."""
    r = ValidationResult(value=style)
    choices = StyleMode.choices()
    if style not in choices:
        r.add(_err("STYLE_MODE_INVALID",
                   f"Unknown style mode '{style}'. "
                   f"Valid options: {choices}"))
    return r


def validate_score_weights(weights: dict[str, float]) -> ValidationResult:
    """
    Validate a scoring weight dict.
    Keys must be: pronounce, memorability, uniqueness, length_fit.
    Values must sum to 1.0 (± 0.001 tolerance).
    """
    r = ValidationResult(value=str(weights))
    required = {"pronounce", "memorability", "uniqueness", "length_fit"}
    present  = set(weights.keys())

    missing = required - present
    if missing:
        r.add(_err("WEIGHTS_MISSING_KEYS",
                   f"Missing score weight keys: {sorted(missing)}"))

    extra = present - required
    if extra:
        r.add(_warn("WEIGHTS_EXTRA_KEYS",
                    f"Unrecognised weight keys (ignored): {sorted(extra)}"))

    total = sum(weights.get(k, 0.0) for k in required)
    if abs(total - 1.0) > 0.001:
        r.add(_err("WEIGHTS_DO_NOT_SUM_TO_ONE",
                   f"Score weights sum to {total:.4f} — must equal 1.0 (±0.001)."))

    for key, val in weights.items():
        if not (0.0 <= val <= 1.0):
            r.add(_err("WEIGHT_OUT_OF_RANGE",
                       f"Weight for '{key}' is {val} — must be between 0.0 and 1.0."))

    return r


# ─────────────────────────────────────────────────────────────────────────────
# § 6  COMPOSITE VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

# Type alias for a validator function
ValidatorFn = Callable[[str], ValidationResult]


def validate_all(
    value: str,
    *validators: ValidatorFn,
) -> ValidationResult:
    """
    Run multiple validator functions against the same value and merge results.

    Short-circuits on the first ERROR (subsequent validators are skipped).

    Args:
        value:       The input to validate.
        *validators: Validator callables — each takes a str, returns ValidationResult.

    Returns:
        Merged ValidationResult containing all issues found.
    """
    combined = ValidationResult(value=value)
    for validator in validators:
        result = validator(value)
        combined.merge(result)
        if not result.valid:
            break  # short-circuit on hard errors
    return combined


def validate_brand_name(
    name: str,
    *,
    existing_names: Sequence[str] = (),
    blacklist: Sequence[str] | None = None,
    common_words: frozenset[str] | None = None,
    min_len: int = NAME_LENGTH_HARD_MIN,
    max_len: int = NAME_LENGTH_HARD_MAX,
    check_uniqueness: bool = True,
    check_trademark: bool = True,
    check_phonetics: bool = True,
    check_common_word: bool = True,
) -> ValidationResult:
    """
    Full brand name validation pipeline.

    Runs all applicable validators in order and returns a merged result.
    Each check can be individually disabled via keyword arguments.

    Args:
        name:             The brand name to validate.
        existing_names:   Pool of already-accepted names (for uniqueness).
        blacklist:        Known brands for trademark check.
        common_words:     Set of generic words to flag.
        min_len:          Hard minimum character length.
        max_len:          Hard maximum character length.
        check_uniqueness: Enable/disable uniqueness check.
        check_trademark:  Enable/disable trademark risk check.
        check_phonetics:  Enable/disable phonetic quality check.
        check_common_word:Enable/disable common-word warning.

    Returns:
        ValidationResult — check .valid for pass/fail, .issues for details.
    """
    result = ValidationResult(value=name)

    # 1. Characters (hard requirement — no point continuing if non-alpha)
    char_result = validate_name_characters(name)
    result.merge(char_result)
    if not char_result.valid:
        return result

    clean_name = name.lower()

    # 2. Length
    result.merge(validate_name_length(clean_name, min_len, max_len))
    if not result.valid:
        return result

    # 3. Phonetics
    if check_phonetics:
        result.merge(validate_name_phonetics(clean_name))

    # 4. Trademark safety
    if check_trademark:
        result.merge(validate_trademark_safety(clean_name, blacklist))

    # 5. Uniqueness against existing pool
    if check_uniqueness and existing_names:
        result.merge(validate_name_uniqueness(clean_name, existing_names))

    # 6. Common word warning
    if check_common_word:
        result.merge(validate_common_word(clean_name, common_words))

    return result


def batch_validate(
    names: Sequence[str],
    **kwargs,
) -> dict[str, ValidationResult]:
    """
    Validate a sequence of names and return a mapping of name → result.
    Passes all kwargs to validate_brand_name.

    Example:
        results = batch_validate(["nexagen", "google", "zxqvv"])
        for name, r in results.items():
            print(name, r.summary())
    """
    return {name: validate_brand_name(name, **kwargs) for name in names}


def filter_valid(
    names: Sequence[str],
    **kwargs,
) -> list[str]:
    """
    Return only the names that pass full validation.
    Convenience wrapper around batch_validate.
    """
    return [n for n, r in batch_validate(names, **kwargs).items() if r.valid]


# ─────────────────────────────────────────────────────────────────────────────
# § 7  DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def format_validation_result(result: ValidationResult) -> str:
    """
    Format a ValidationResult as a multi-line human-readable string.
    Suitable for CLI output.
    """
    lines = [f"  Validation for '{result.value}':"]
    if result.valid:
        lines.append("    ✔ Passed all checks")
    for issue in result.issues:
        icon = {"error": "✘", "warning": "⚠", "info": "ℹ"}[issue.severity.value]
        lines.append(f"    {icon} {issue.code}: {issue.message}")
    return "\n".join(lines)


def validation_icon(result: ValidationResult) -> str:
    """Return a single-character icon representing the result status."""
    if result.valid and not result.warnings:
        return "✔"
    if result.valid and result.warnings:
        return "⚠"
    return "✘"


def validation_color(result: ValidationResult) -> str:
    """Return the Rich hex color appropriate for the result status."""
    from ..config.constants import C_AMBER, C_GREEN, C_RED

    if not result.valid:
        return C_RED
    if result.warnings:
        return C_AMBER
    return C_GREEN
