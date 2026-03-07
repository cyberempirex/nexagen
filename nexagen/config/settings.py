"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  NEXAGEN  ·  Platform Naming Intelligence Engine                            ║
║  config/settings.py  ·  Runtime settings with persistent user config       ║
║                                                                              ║
║  CEX-Nexagen · Developed by CyberEmpireX                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

Provides a single ``Settings`` dataclass that:
  - holds all tunable runtime parameters
  - loads from ~/.nexagen/settings.toml  (created automatically on first run)
  - falls back gracefully to defaults on any parse error
  - can be read with ``get_settings()`` from anywhere in the codebase
  - is fully serializable to JSON for export/debug
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from .constants import (
    CACHE_DIR,
    CHECK_MAX_WORKERS,
    CHECK_TIMEOUT_SEC,
    EXPORT_DIR,
    GEN_DEFAULT_COUNT,
    GEN_MAX_COUNT,
    GEN_MIN_COUNT,
    LOG_DIR,
    NAME_LENGTH_IDEAL_MAX,
    NAME_LENGTH_IDEAL_MIN,
    Profile,
    StyleMode,
    USER_SETTINGS_FILE,
    VERSION,
)

# ─────────────────────────────────────────────────────────────────────────────
# § 1  TOML COMPAT SHIM  (Python 3.9/3.10 don't have tomllib in stdlib)
# ─────────────────────────────────────────────────────────────────────────────

_TOML_READ_FN = None
_TOML_WRITE_FN = None

try:
    # Python 3.11+
    import tomllib as _tomllib  # type: ignore[import]
    _TOML_READ_FN = _tomllib.loads
except ImportError:
    try:
        import tomli as _tomllib  # type: ignore[import]
        _TOML_READ_FN = _tomllib.loads
    except ImportError:
        _TOML_READ_FN = None  # will fall back to JSON persistence

try:
    import tomli_w as _tomli_w  # type: ignore[import]
    _TOML_WRITE_FN = _tomli_w.dumps
except ImportError:
    _TOML_WRITE_FN = None

_HAS_TOML = _TOML_READ_FN is not None


# ─────────────────────────────────────────────────────────────────────────────
# § 2  SETTINGS DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Settings:
    """
    All tunable parameters for NEXAGEN.

    Attributes are grouped by subsystem. Each attribute has a sensible
    default so the tool is fully functional even with no config file.

    Usage:
        cfg = get_settings()
        cfg.generation.count = 30
        save_settings(cfg)
    """

    # ── Identity (read-only, not persisted) ───────────────────────────────────
    _version: ClassVar[str] = VERSION

    # ── Generation ────────────────────────────────────────────────────────────
    profile:         str   = Profile.GENERIC.value
    style_mode:      str   = StyleMode.MINIMAL.value
    count:           int   = GEN_DEFAULT_COUNT
    min_len:         int   = NAME_LENGTH_IDEAL_MIN
    max_len:         int   = NAME_LENGTH_IDEAL_MAX
    use_suffixes:    bool  = True
    use_prefixes:    bool  = True
    use_multiword:   bool  = True
    use_synonyms:    bool  = True

    # ── Analysis ──────────────────────────────────────────────────────────────
    score_weights: dict[str, float] = field(default_factory=lambda: {
        "pronounce":    0.30,
        "memorability": 0.30,
        "uniqueness":   0.20,
        "length_fit":   0.20,
    })

    # ── Domain checks ─────────────────────────────────────────────────────────
    do_domain_checks:  bool  = True
    do_handle_checks:  bool  = True
    check_workers:     int   = CHECK_MAX_WORKERS
    check_timeout:     float = CHECK_TIMEOUT_SEC
    preferred_tlds:    list[str] = field(default_factory=lambda: [
        "com", "io", "ai", "co", "dev"
    ])

    # ── Platform handle checks ────────────────────────────────────────────────
    check_github:      bool = True
    check_pypi:        bool = True
    check_npm:         bool = True
    check_docker:      bool = True
    check_huggingface: bool = True

    # ── UI / Display ──────────────────────────────────────────────────────────
    color_theme:     str  = "cyberpunk"     # future: allow "light", "mono"
    animations:      bool = True
    clear_on_start:  bool = True
    show_scores:     bool = True
    show_domains:    bool = True
    show_handles:    bool = True
    table_row_limit: int  = 30

    # ── Export ────────────────────────────────────────────────────────────────
    export_dir:       str   = str(EXPORT_DIR)
    auto_export:      bool  = False
    export_format:    str   = "json"        # json | csv | markdown | all

    # ── Logging ───────────────────────────────────────────────────────────────
    log_enabled:   bool = False
    log_dir:       str  = str(LOG_DIR)
    log_level:     str  = "WARNING"         # DEBUG | INFO | WARNING | ERROR

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_enabled:     bool = True
    cache_dir:         str  = str(CACHE_DIR)
    cache_ttl_seconds: int  = 3600

    # ── Auto-update ───────────────────────────────────────────────────────────
    check_for_updates: bool = True
    update_channel:    str  = "stable"      # stable | beta

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience accessors
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def export_path(self) -> Path:
        return Path(self.export_dir)

    @property
    def log_path(self) -> Path:
        return Path(self.log_dir)

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir)

    @property
    def profile_enum(self) -> Profile:
        try:
            return Profile(self.profile)
        except ValueError:
            return Profile.default()

    @property
    def style_enum(self) -> StyleMode:
        try:
            return StyleMode(self.style_mode)
        except ValueError:
            return StyleMode.default()

    # ─────────────────────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty means valid)."""
        errors: list[str] = []

        if self.profile not in Profile.choices():
            errors.append(
                f"Invalid profile '{self.profile}'. "
                f"Choose from: {Profile.choices()}"
            )

        if self.style_mode not in StyleMode.choices():
            errors.append(
                f"Invalid style_mode '{self.style_mode}'. "
                f"Choose from: {StyleMode.choices()}"
            )

        if not (GEN_MIN_COUNT <= self.count <= GEN_MAX_COUNT):
            errors.append(
                f"count must be between {GEN_MIN_COUNT} and {GEN_MAX_COUNT}, "
                f"got {self.count}."
            )

        if self.min_len >= self.max_len:
            errors.append(
                f"min_len ({self.min_len}) must be less than "
                f"max_len ({self.max_len})."
            )

        weight_sum = sum(self.score_weights.values())
        if abs(weight_sum - 1.0) > 0.001:
            errors.append(
                f"score_weights must sum to 1.0, got {weight_sum:.3f}."
            )

        if self.check_workers < 1 or self.check_workers > 64:
            errors.append("check_workers must be between 1 and 64.")

        return errors

    # ─────────────────────────────────────────────────────────────────────────
    # Serialization
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation (JSON-serializable)."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """
        Build a Settings instance from a dict, ignoring unknown keys
        and filling missing keys with defaults.
        """
        defaults = cls()
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known_fields}
        # merge: defaults first, then what was loaded
        merged = {**defaults.to_dict(), **filtered}
        return cls(**merged)

    @classmethod
    def from_json(cls, text: str) -> "Settings":
        return cls.from_dict(json.loads(text))


# ─────────────────────────────────────────────────────────────────────────────
# § 3  PERSISTENCE — TOML (preferred) or JSON (fallback)
# ─────────────────────────────────────────────────────────────────────────────

_SETTINGS_FILE_TOML = USER_SETTINGS_FILE          # ~/.nexagen/settings.toml
_SETTINGS_FILE_JSON = USER_SETTINGS_FILE.with_suffix(".json")


def _ensure_dirs() -> None:
    """Create all ~/.nexagen sub-directories silently."""
    for d in (
        USER_SETTINGS_FILE.parent,
        EXPORT_DIR,
        CACHE_DIR,
        LOG_DIR,
    ):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def _write_settings_json(cfg: Settings, path: Path) -> None:
    try:
        path.write_text(cfg.to_json(), encoding="utf-8")
    except OSError as exc:
        warnings.warn(f"[nexagen] Could not save settings: {exc}", stacklevel=3)


def _write_settings_toml(cfg: Settings, path: Path) -> None:
    """Write settings as a hand-built TOML string (no external deps needed)."""
    d = cfg.to_dict()
    lines: list[str] = [
        "# NEXAGEN settings file  —  auto-generated, safe to edit",
        f"# Version: {VERSION}",
        "",
    ]
    for key, val in d.items():
        if isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, (int, float)):
            lines.append(f"{key} = {val}")
        elif isinstance(val, list):
            items = ", ".join(
                f'"{v}"' if isinstance(v, str) else str(v) for v in val
            )
            lines.append(f"{key} = [{items}]")
        elif isinstance(val, dict):
            lines.append(f"\n[{key}]")
            for k2, v2 in val.items():
                if isinstance(v2, (int, float)):
                    lines.append(f"  {k2} = {v2}")
                else:
                    lines.append(f'  {k2} = "{v2}"')
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        warnings.warn(f"[nexagen] Could not save settings: {exc}", stacklevel=3)


def _read_toml_simple(text: str) -> dict[str, Any]:
    """
    Minimal hand-rolled TOML reader — handles flat key=value and [table].
    Covers every key written by _write_settings_toml.
    Falls back to the external tomllib/tomli if available.
    """
    if _TOML_READ_FN is not None:
        return _TOML_READ_FN(text)

    result: dict[str, Any] = {}
    current_table: dict[str, Any] = result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            table_name = line[1:-1].strip()
            current_table = {}
            result[table_name] = current_table
            continue
        if "=" not in line:
            continue
        key, _, raw_val = line.partition("=")
        key = key.strip()
        raw_val = raw_val.strip()
        # bool
        if raw_val in ("true", "false"):
            current_table[key] = raw_val == "true"
        # string
        elif raw_val.startswith('"') and raw_val.endswith('"'):
            current_table[key] = raw_val[1:-1].replace('\\"', '"')
        # list
        elif raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1].strip()
            if not inner:
                current_table[key] = []
            else:
                items = [i.strip().strip('"') for i in inner.split(",")]
                current_table[key] = items
        # number
        else:
            try:
                if "." in raw_val:
                    current_table[key] = float(raw_val)
                else:
                    current_table[key] = int(raw_val)
            except ValueError:
                current_table[key] = raw_val  # store as string

    return result


# ─────────────────────────────────────────────────────────────────────────────
# § 4  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

# Module-level singleton — loaded once per process
_SETTINGS_CACHE: Settings | None = None


def get_settings() -> Settings:
    """
    Return the current runtime Settings singleton.

    Load order:
      1. ~/.nexagen/settings.toml   (primary)
      2. ~/.nexagen/settings.json   (JSON fallback)
      3. Built-in defaults           (if neither exists or both fail)

    The loaded instance is cached for the lifetime of the process.
    Call ``reload_settings()`` to force re-read from disk.
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE
    _SETTINGS_CACHE = _load_settings()
    return _SETTINGS_CACHE


def reload_settings() -> Settings:
    """Force a re-read of the settings file and return the new instance."""
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None
    return get_settings()


def save_settings(cfg: Settings | None = None) -> None:
    """
    Persist settings to ~/.nexagen/settings.toml.

    Args:
        cfg: Settings instance to save. Defaults to ``get_settings()``.
    """
    global _SETTINGS_CACHE
    _ensure_dirs()
    cfg = cfg or get_settings()
    _write_settings_toml(cfg, _SETTINGS_FILE_TOML)
    _SETTINGS_CACHE = cfg


def reset_settings() -> Settings:
    """
    Delete the user config file and return fresh defaults.
    Useful for 'restore defaults' UI option.
    """
    global _SETTINGS_CACHE
    for path in (_SETTINGS_FILE_TOML, _SETTINGS_FILE_JSON):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    _SETTINGS_CACHE = Settings()
    return _SETTINGS_CACHE


def update_setting(key: str, value: Any) -> Settings:
    """
    Update a single top-level setting key, validate, and persist.

    Args:
        key:   Attribute name on the Settings dataclass.
        value: New value (will be coerced to the correct type).

    Returns:
        The updated Settings singleton.

    Raises:
        KeyError:   if key does not exist on Settings.
        ValueError: if the updated settings fail validation.
    """
    cfg = get_settings()
    if not hasattr(cfg, key):
        raise KeyError(f"Unknown setting: '{key}'")
    setattr(cfg, key, value)
    errors = cfg.validate()
    if errors:
        raise ValueError(f"Invalid settings after update: {errors}")
    save_settings(cfg)
    return cfg


def settings_summary() -> str:
    """Return a compact human-readable summary of active settings."""
    cfg = get_settings()
    lines = [
        f"  Profile        : {cfg.profile}",
        f"  Style          : {cfg.style_mode}",
        f"  Count          : {cfg.count}",
        f"  Length range   : {cfg.min_len} – {cfg.max_len}",
        f"  Domain checks  : {'on' if cfg.do_domain_checks else 'off'}",
        f"  Handle checks  : {'on' if cfg.do_handle_checks else 'off'}",
        f"  Animations     : {'on' if cfg.animations else 'off'}",
        f"  Auto-export    : {'on' if cfg.auto_export else 'off'}",
        f"  Update checks  : {'on' if cfg.check_for_updates else 'off'}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# § 5  INTERNAL LOADER
# ─────────────────────────────────────────────────────────────────────────────

def _load_settings() -> Settings:
    """Internal — attempt to load from disk, return defaults on any failure."""
    _ensure_dirs()

    # Try TOML first
    if _SETTINGS_FILE_TOML.exists():
        try:
            text = _SETTINGS_FILE_TOML.read_text(encoding="utf-8")
            data = _read_toml_simple(text)
            cfg = Settings.from_dict(data)
            errors = cfg.validate()
            if errors:
                warnings.warn(
                    f"[nexagen] Settings validation issues "
                    f"(using defaults): {errors}",
                    stacklevel=2,
                )
                return Settings()
            return cfg
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"[nexagen] Failed to parse settings.toml ({exc}), "
                "using defaults.",
                stacklevel=2,
            )

    # Try JSON fallback
    if _SETTINGS_FILE_JSON.exists():
        try:
            text = _SETTINGS_FILE_JSON.read_text(encoding="utf-8")
            cfg = Settings.from_json(text)
            errors = cfg.validate()
            if errors:
                return Settings()
            return cfg
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"[nexagen] Failed to parse settings.json ({exc}), "
                "using defaults.",
                stacklevel=2,
            )

    # First run — create default settings file
    defaults = Settings()
    _write_settings_toml(defaults, _SETTINGS_FILE_TOML)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# § 6  ENVIRONMENT VARIABLE OVERRIDES
# ─────────────────────────────────────────────────────────────────────────────

def apply_env_overrides(cfg: Settings) -> Settings:
    """
    Apply NEXAGEN_* environment variable overrides to a Settings instance.
    Useful for CI, scripting, and Docker usage.

    Supported:
        NEXAGEN_PROFILE      → cfg.profile
        NEXAGEN_STYLE        → cfg.style_mode
        NEXAGEN_COUNT        → cfg.count  (int)
        NEXAGEN_NO_CHECKS    → cfg.do_domain_checks = False
        NEXAGEN_NO_ANIM      → cfg.animations = False
        NEXAGEN_EXPORT_DIR   → cfg.export_dir
        NEXAGEN_LOG_LEVEL    → cfg.log_level
    """
    env = os.environ

    if (v := env.get("NEXAGEN_PROFILE")):
        if v in Profile.choices():
            cfg.profile = v

    if (v := env.get("NEXAGEN_STYLE")):
        if v in StyleMode.choices():
            cfg.style_mode = v

    if (v := env.get("NEXAGEN_COUNT")):
        try:
            cfg.count = int(v)
        except ValueError:
            pass

    if env.get("NEXAGEN_NO_CHECKS"):
        cfg.do_domain_checks  = False
        cfg.do_handle_checks  = False

    if env.get("NEXAGEN_NO_ANIM"):
        cfg.animations = False

    if (v := env.get("NEXAGEN_EXPORT_DIR")):
        cfg.export_dir = v

    if (v := env.get("NEXAGEN_LOG_LEVEL")):
        if v.upper() in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg.log_level = v.upper()

    return cfg
