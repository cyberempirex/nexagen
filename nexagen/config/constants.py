"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  config/constants.py  ·  Static constants for the entire project            ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
║  Part of the CyberEmpireX (CEX) Ecosystem                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

All project-wide constants are defined here.
Nothing in this module should ever change at runtime.
Import only what you need to avoid circular dependency issues.
"""

from __future__ import annotations

from enum import Enum, IntEnum, unique
from pathlib import Path
from typing import Final, FrozenSet, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# § 1  IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

TOOL_NAME: Final[str]       = "NEXAGEN"
TOOL_TAGLINE: Final[str]    = "Platform Naming Intelligence Engine"
TOOL_AUTHOR: Final[str]     = "CEX-Nexagen"
TOOL_ECOSYSTEM: Final[str]  = "CyberEmpireX (CEX)"
TOOL_REPO: Final[str]       = "https://github.com/cyberempirex/nexagen"
TOOL_DOCS: Final[str]       = "https://github.com/cyberempirex/nexagen/blob/main/docs/usage.md"
# Contact / community
TOOL_CONTACT = "https://t.me/CyberEmpireXChat"
VERSION_MAJOR: Final[int]   = 1
VERSION_MINOR: Final[int]   = 0
VERSION_PATCH: Final[int]   = 0
VERSION: Final[str]         = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
VERSION_TAG: Final[str]     = f"v{VERSION}"
VERSION_FULL: Final[str]    = f"{TOOL_NAME} {VERSION_TAG} · {TOOL_AUTHOR}"

SLOGAN: Final[str]          = "Generate · Analyze · Validate · Discover"
DISCLAIMER: Final[str]      = (
    "NEXAGEN is provided as-is for research and creative use. "
    "Final responsibility for name selection rests with the user."
)

# ─────────────────────────────────────────────────────────────────────────────
# § 2  FILESYSTEM PATHS
# ─────────────────────────────────────────────────────────────────────────────

# Root of the installed package
PKG_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# Sub-directories
DATASETS_DIR: Final[Path]   = PKG_ROOT / "datasets"
CONFIG_DIR: Final[Path]     = PKG_ROOT / "config"
EXPORT_DIR: Final[Path]     = Path.home() / ".nexagen" / "exports"
CACHE_DIR: Final[Path]      = Path.home() / ".nexagen" / "cache"
LOG_DIR: Final[Path]        = Path.home() / ".nexagen" / "logs"

# Dataset files
DS_COMMON_WORDS: Final[Path]      = DATASETS_DIR / "common_words.txt"
DS_SYNONYMS: Final[Path]          = DATASETS_DIR / "synonyms.txt"
DS_BRAND_BLACKLIST: Final[Path]   = DATASETS_DIR / "brand_blacklist.txt"
DS_PREFIXES: Final[Path]          = DATASETS_DIR / "prefixes.txt"
DS_SUFFIXES: Final[Path]          = DATASETS_DIR / "suffixes.txt"
DS_TECH_TERMS: Final[Path]        = DATASETS_DIR / "tech_terms.txt"
DS_AI_TERMS: Final[Path]          = DATASETS_DIR / "ai_terms.txt"
DS_BUSINESS_TERMS: Final[Path]    = DATASETS_DIR / "business_terms.txt"
DS_TLDS: Final[Path]              = DATASETS_DIR / "tlds.txt"

# User settings file (written on first run)
USER_SETTINGS_FILE: Final[Path]   = Path.home() / ".nexagen" / "settings.toml"
USER_HISTORY_FILE: Final[Path]    = Path.home() / ".nexagen" / "history.json"

# ─────────────────────────────────────────────────────────────────────────────
# § 3  TERMINAL / UI THEME  (hex colours used by Rich)
# ─────────────────────────────────────────────────────────────────────────────

# Primary palette
C_BANNER:  Final[str] = "#9b59b6"   # vivid purple   — banner / logo
C_ACCENT:  Final[str] = "#00d2d3"   # bright cyan    — headings / borders
C_WHITE:   Final[str] = "#f0f0f0"   # near-white     — primary text
C_GRAY:    Final[str] = "#7f8c8d"   # medium grey    — muted / hints
C_DARK:    Final[str] = "#2c3e50"   # dark blue-grey — panel backgrounds

# Status colours
C_GREEN:   Final[str] = "#2ecc71"   # success / available / strong
C_AMBER:   Final[str] = "#f39c12"   # warning / taken / medium
C_RED:     Final[str] = "#e74c3c"   # error / danger / unavailable
C_BLUE:    Final[str] = "#3498db"   # info / progress

# Accent extras
C_GOLD:    Final[str] = "#f1c40f"   # premium / top score
C_TEAL:    Final[str] = "#1abc9c"   # domain / network
C_PINK:    Final[str] = "#fd79a8"   # creative / soft mode
C_PURPLE:  Final[str] = "#6c5ce7"   # AI / analysis

# Score tier colours  (aligned with BrandTier below)
TIER_COLORS: Final[dict[str, str]] = {
    "PREMIUM": C_GOLD,
    "STRONG":  C_GREEN,
    "DECENT":  C_ACCENT,
    "WEAK":    C_AMBER,
    "POOR":    C_RED,
}

# ─────────────────────────────────────────────────────────────────────────────
# § 4  SCORING THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

# Brand score tiers  (composite 0-100)
SCORE_PREMIUM: Final[int] = 90
SCORE_STRONG:  Final[int] = 75
SCORE_DECENT:  Final[int] = 60
SCORE_WEAK:    Final[int] = 40
SCORE_POOR:    Final[int] = 0

# Component score weights (must sum to 1.0)
WEIGHT_PRONOUNCE:    Final[float] = 0.30
WEIGHT_MEMORABILITY: Final[float] = 0.30
WEIGHT_UNIQUENESS:   Final[float] = 0.20
WEIGHT_LENGTH_FIT:   Final[float] = 0.20

# Length scoring
NAME_LENGTH_IDEAL_MIN: Final[int] = 4
NAME_LENGTH_IDEAL_MAX: Final[int] = 8
NAME_LENGTH_HARD_MIN:  Final[int] = 2
NAME_LENGTH_HARD_MAX:  Final[int] = 20

# Uniqueness scoring
UNIQUENESS_LEVENSHTEIN_MIN_DISTANCE: Final[int] = 2  # below = duplicate
COMMON_WORD_PENALTY: Final[int]                 = 20
ENGLISH_WORD_PENALTY: Final[int]                = 15

# Phonetic scoring
PHONETIC_FORBIDDEN_BONUS:   Final[int] = -20  # per forbidden sequence
PHONETIC_CONSONANT_RUN_MAX: Final[int] = 2    # max consecutive consonants
PHONETIC_VOWEL_TRANS_BONUS: Final[int] = 4    # per vowel-consonant transition

# Trademark / collision risk thresholds
TM_HIGH_RISK_DISTANCE:   Final[int] = 1
TM_MEDIUM_RISK_DISTANCE: Final[int] = 2
TM_LOW_RISK_DISTANCE:    Final[int] = 3

# ─────────────────────────────────────────────────────────────────────────────
# § 5  NAME GENERATION LIMITS
# ─────────────────────────────────────────────────────────────────────────────

GEN_DEFAULT_COUNT:    Final[int] = 20
GEN_MAX_COUNT:        Final[int] = 200
GEN_MIN_COUNT:        Final[int] = 5
GEN_MAX_CANDIDATES:   Final[int] = 500   # internal pool before dedup + filter
GEN_DEDUP_THRESHOLD:  Final[int] = 2     # Levenshtein distance threshold

# ─────────────────────────────────────────────────────────────────────────────
# § 6  DOMAIN INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────

# TLD ranking scores  (higher = better for brand)
TLD_SCORES: Final[dict[str, int]] = {
    "com":       100,
    "io":         85,
    "ai":         82,
    "co":         78,
    "dev":        74,
    "app":        70,
    "tech":       68,
    "cloud":      65,
    "build":      62,
    "tools":      60,
    "run":        58,
    "systems":    56,
    "net":        54,
    "org":        50,
    "online":     45,
    "site":       43,
    "digital":    42,
    "works":      40,
    "world":      38,
    "space":      36,
    "center":     34,
    "group":      32,
    "software":   30,
    "platform":   28,
    "solutions":  26,
    "services":   24,
    "network":    22,
    "hub":        50,
    "labs":       55,
    "link":       40,
    "studio":     48,
    "agency":     35,
    "design":     40,
    "health":     45,
    "finance":    45,
    "xyz":        20,
    "me":         30,
    "ly":         28,
    "gg":         25,
    "so":         22,
}

# Domain check endpoints
RDAP_BASE_URL:   Final[str] = "https://rdap.org/domain"
GITHUB_API_URL:  Final[str] = "https://api.github.com/users"
PYPI_API_URL:    Final[str] = "https://pypi.org/pypi"
NPM_API_URL:     Final[str] = "https://registry.npmjs.org"
DOCKER_API_URL:  Final[str] = "https://hub.docker.com/v2/users"
HF_BASE_URL:     Final[str] = "https://huggingface.co"

# Parallel check workers
CHECK_MAX_WORKERS: Final[int]   = 12
CHECK_TIMEOUT_SEC: Final[float] = 8.0
CHECK_RETRY_COUNT: Final[int]   = 2

# ─────────────────────────────────────────────────────────────────────────────
# § 7  PHONETICS / LINGUISTICS
# ─────────────────────────────────────────────────────────────────────────────

VOWELS: Final[FrozenSet[str]] = frozenset("aeiou")
CONSONANTS: Final[FrozenSet[str]] = frozenset("bcdfghjklmnpqrstvwxyz")

RARE_CONSONANTS: Final[FrozenSet[str]] = frozenset("qxzjv")

# Forbidden phonetic sequences (adjacent letters that look/sound bad)
FORBIDDEN_SEQUENCES: Final[Tuple[str, ...]] = (
    "aa", "ee", "ii", "oo", "uu",     # double vowels
    "ww", "yy", "vv", "hh", "jj",     # rare double consonants
    "qq", "xx", "zz", "kk", "pp",     # hard double consonants
    "tt", "gg", "dd", "bb", "ff", "cc",
    "wq", "qw", "vq", "qv",           # unpronounceable pairs
    "bx", "cx", "fx", "gx", "hx",     # x-combinations
    "jx", "kx", "lx", "mx", "nx",
    "px", "rx", "sx", "tx", "vx",
    "wx", "zx", "xb", "xc", "xd",
    "xf", "xg", "xh", "xj", "xk",
    "xl", "xm", "xn", "xp", "xq",
    "xr", "xs", "xt", "xv", "xw",
)

# Syllable patterns used in generation
SYLLABLE_PATTERNS: Final[Tuple[str, ...]] = (
    "CVC", "CV", "VC", "CVCV", "VCVC",
)

# Preferred start consonants (strong, memorable)
STRONG_START_CONSONANTS: Final[FrozenSet[str]] = frozenset("bdfgkprstvz")

# ─────────────────────────────────────────────────────────────────────────────
# § 8  PROFILE IDENTIFIERS
# ─────────────────────────────────────────────────────────────────────────────

@unique
class Profile(str, Enum):
    """Industry / use-case profiles that guide name generation."""
    TECH       = "tech"
    AI         = "ai"
    SECURITY   = "security"
    FINANCE    = "finance"
    HEALTH     = "health"
    SOCIAL     = "social"
    EDUCATION  = "education"
    DOCUMENT   = "document"
    GENERIC    = "generic"

    @classmethod
    def choices(cls) -> list[str]:
        return [p.value for p in cls]

    @classmethod
    def default(cls) -> "Profile":
        return cls.GENERIC


@unique
class StyleMode(str, Enum):
    """Visual / linguistic style applied to generated names."""
    MINIMAL    = "minimal"
    FUTURISTIC = "futuristic"
    AGGRESSIVE = "aggressive"
    SOFT       = "soft"
    TECHNICAL  = "technical"
    LUXURY     = "luxury"

    @classmethod
    def choices(cls) -> list[str]:
        return [s.value for s in cls]

    @classmethod
    def default(cls) -> "StyleMode":
        return cls.MINIMAL


# ─────────────────────────────────────────────────────────────────────────────
# § 9  BRAND SCORE TIER
# ─────────────────────────────────────────────────────────────────────────────

@unique
class BrandTier(str, Enum):
    """Human-readable tier derived from composite brand score."""
    PREMIUM = "PREMIUM"    # 90-100  ◆
    STRONG  = "STRONG"     # 75-89   ▲
    DECENT  = "DECENT"     # 60-74   ●
    WEAK    = "WEAK"       # 40-59   ▼
    POOR    = "POOR"       # 0-39    ✕

    # Unicode indicator characters
    INDICATORS: dict[str, str] = {}  # populated below

    @classmethod
    def from_score(cls, score: int) -> "BrandTier":
        if score >= SCORE_PREMIUM:
            return cls.PREMIUM
        elif score >= SCORE_STRONG:
            return cls.STRONG
        elif score >= SCORE_DECENT:
            return cls.DECENT
        elif score >= SCORE_WEAK:
            return cls.WEAK
        return cls.POOR

    @property
    def indicator(self) -> str:
        return _TIER_INDICATORS[self]

    @property
    def color(self) -> str:
        return TIER_COLORS[self.value]


_TIER_INDICATORS: Final[dict[BrandTier, str]] = {
    BrandTier.PREMIUM: "◆",
    BrandTier.STRONG:  "▲",
    BrandTier.DECENT:  "●",
    BrandTier.WEAK:    "▼",
    BrandTier.POOR:    "✕",
}


# ─────────────────────────────────────────────────────────────────────────────
# § 10  TRADEMARK RISK LEVEL
# ─────────────────────────────────────────────────────────────────────────────

@unique
class TMRisk(str, Enum):
    """Trademark conflict risk levels."""
    NONE   = "none"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"

    @property
    def color(self) -> str:
        mapping = {
            "none":   C_GREEN,
            "low":    C_TEAL,
            "medium": C_AMBER,
            "high":   C_RED,
        }
        return mapping[self.value]

    @classmethod
    def from_distance(cls, dist: int | None) -> "TMRisk":
        if dist is None:
            return cls.NONE
        if dist <= TM_HIGH_RISK_DISTANCE:
            return cls.HIGH
        if dist <= TM_MEDIUM_RISK_DISTANCE:
            return cls.MEDIUM
        if dist <= TM_LOW_RISK_DISTANCE:
            return cls.LOW
        return cls.NONE


# ─────────────────────────────────────────────────────────────────────────────
# § 11  AVAILABILITY STATUS
# ─────────────────────────────────────────────────────────────────────────────

@unique
class AvailStatus(str, Enum):
    """Domain / platform handle availability status."""
    FREE    = "free"
    TAKEN   = "taken"
    UNKNOWN = "unknown"
    SKIP    = "skip"      # check was disabled by user

    @property
    def icon(self) -> str:
        return {
            "free":    "✔",
            "taken":   "✘",
            "unknown": "?",
            "skip":    "—",
        }[self.value]

    @property
    def color(self) -> str:
        return {
            "free":    C_GREEN,
            "taken":   C_RED,
            "unknown": C_GRAY,
            "skip":    C_GRAY,
        }[self.value]


# ─────────────────────────────────────────────────────────────────────────────
# § 12  EXPORT FORMATS
# ─────────────────────────────────────────────────────────────────────────────

@unique
class ExportFormat(str, Enum):
    JSON     = "json"
    CSV      = "csv"
    MARKDOWN = "markdown"
    ALL      = "all"

    @property
    def extension(self) -> str:
        return {
            "json":     ".json",
            "csv":      ".csv",
            "markdown": ".md",
            "all":      "",
        }[self.value]


# ─────────────────────────────────────────────────────────────────────────────
# § 13  MAIN MENU OPTION IDS
# ─────────────────────────────────────────────────────────────────────────────

@unique
class MenuOption(IntEnum):
    GENERATE_NAMES  = 1
    ANALYZE_BRAND   = 2
    DOMAIN_SUGGEST  = 3
    STARTUP_REPORT  = 4
    ABOUT           = 5
    EXIT            = 6


# ─────────────────────────────────────────────────────────────────────────────
# § 14  KNOWN BRAND BLACKLIST  (built-in seed, extended by dataset file)
# ─────────────────────────────────────────────────────────────────────────────

BRAND_BLACKLIST_SEED: Final[FrozenSet[str]] = frozenset([
    "google", "amazon", "facebook", "apple", "microsoft",
    "netflix", "spotify", "twitter", "linkedin", "youtube",
    "github", "stripe", "paypal", "shopify", "dropbox",
    "slack", "notion", "figma", "vercel", "openai",
    "anthropic", "meta", "uber", "lyft", "airbnb",
    "tesla", "nvidia", "intel", "adobe", "oracle",
    "salesforce", "hubspot", "zoom", "twilio", "discord",
    "reddit", "pinterest", "snapchat", "tiktok", "bytedance",
    "alibaba", "tencent", "samsung", "sony", "ibm",
])


# ─────────────────────────────────────────────────────────────────────────────
# § 15  HTTP HEADERS  (used by domain/platform checkers)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        f"Nexagen/{VERSION} (Platform Naming Engine; "
        "+https://github.com/cyberempirex/nexagen)"
    ),
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
}


# ─────────────────────────────────────────────────────────────────────────────
# § 16  ANIMATION / DISPLAY TIMINGS  (seconds)
# ─────────────────────────────────────────────────────────────────────────────

ANIM_BANNER_DELAY:    Final[float] = 0.03   # per banner line
ANIM_CHAR_TYPEWRITER: Final[float] = 0.025  # typewriter effect per char
ANIM_SPINNER_SPEED:   Final[float] = 0.1    # spinner frame interval
ANIM_PROGRESS_MIN:    Final[float] = 0.5    # min display time for progress bar
ANIM_SCREEN_CLEAR_PAUSE: Final[float] = 0.1 # after cls before banner

# ─────────────────────────────────────────────────────────────────────────────
# § 17  MISC LIMITS / SAFETY
# ─────────────────────────────────────────────────────────────────────────────

MAX_KEYWORD_LENGTH:    Final[int] = 40
MAX_KEYWORDS_PER_RUN:  Final[int] = 10
MAX_EXPORT_FILE_SIZE:  Final[int] = 50 * 1024 * 1024  # 50 MB
HISTORY_MAX_ENTRIES:   Final[int] = 500
CACHE_TTL_SECONDS:     Final[int] = 3600  # 1 hour for domain check cache

# ─────────────────────────────────────────────────────────────────────────────
# § 18  AUTO-UPDATE
# ─────────────────────────────────────────────────────────────────────────────

UPDATE_CHECK_URL:     Final[str]   = (
    "https://api.github.com/repos/cyberempirex/nexagen/releases/latest"
)
UPDATE_CHECK_TIMEOUT: Final[float] = 5.0   # seconds — fail silently if slow
UPDATE_CACHE_FILE:    Final[Path]  = CACHE_DIR / "update_check.json"
UPDATE_CACHE_TTL:     Final[int]   = 86400  # 24 hours between checks
