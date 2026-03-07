# NEXAGEN — Architecture Reference

> **NEXAGEN** · Platform Naming Intelligence Engine  
> CEX-Nexagen · Developed by CyberEmpireX  
> Version 1.0.0 · https://github.com/cyberempirex/nexagen

---

## Overview

NEXAGEN is a command-line platform naming intelligence engine built as a modular Python package. It generates, scores, and validates brand names for digital products and platforms — then checks domain and handle availability to produce actionable naming intelligence.

The codebase follows a strict layered architecture with no circular dependencies between layers. Each layer may only import from layers below it.

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI Layer        cli/app.py · cli/menu.py · cli/commands.py    │
│                   cli/help.py                                    │
├──────────────────────────────────────────────────────────────────┤
│  UI Layer         ui/banner.py · ui/animations.py               │
│                   ui/progress.py · ui/tables.py                 │
├──────────────────────────────────────────────────────────────────┤
│  Engine Layer     engine/ · analysis/ · domains/ · checks/      │
│  (planned)        export/                                        │
├──────────────────────────────────────────────────────────────────┤
│  Utils Layer      utils/text_utils.py · utils/levenshtein.py    │
│                   utils/validators.py · utils/dataset_loader.py │
├──────────────────────────────────────────────────────────────────┤
│  Config Layer     config/constants.py · config/settings.py      │
├──────────────────────────────────────────────────────────────────┤
│  Dataset Layer    datasets/*.txt  (9 files, 3,000+ entries)     │
└──────────────────────────────────────────────────────────────────┘
```

---

## Package Structure

```
nexagen/
├── cli/
│   ├── app.py          551 lines · 1 class · 15 fns
│   ├── commands.py    1329 lines · 1 class · 38 fns
│   ├── help.py         946 lines · 0 class · 17 fns
│   └── menu.py         638 lines · 1 class · 21 fns
├── config/
│   ├── constants.py    502 lines · 7 enums · 12 fns
│   └── settings.py     580 lines · 1 class · 12 fns
├── ui/
│   ├── animations.py   694 lines · 9 classes · 29 fns
│   ├── banner.py       729 lines · 0 classes · 29 fns
│   ├── progress.py     649 lines · 11 classes · 41 fns
│   └── tables.py       730 lines · 4 dataclasses · 18 fns
├── utils/
│   ├── dataset_loader.py   838 lines · 6 classes · 33 fns
│   ├── levenshtein.py      698 lines · 2 classes · 23 fns
│   ├── text_utils.py       795 lines · 0 classes · 51 fns
│   └── validators.py       784 lines · 3 classes · 39 fns
├── datasets/
│   ├── ai_terms.txt           150 entries
│   ├── brand_blacklist.txt    365 entries
│   ├── business_terms.txt     226 entries
│   ├── common_words.txt     1,229 entries
│   ├── prefixes.txt            62 entries
│   ├── suffixes.txt           129 entries
│   ├── synonyms.txt           324 groups
│   ├── tech_terms.txt         302 entries
│   └── tlds.txt                40 entries
├── analysis/          (planned — brand_score, phonetic_analysis …)
├── checks/            (planned — github, pypi, npm, docker …)
├── domains/           (planned — domain_checker, tld_strategy …)
├── engine/            (planned — keyword, pattern, mutation …)
└── export/            (planned — csv, json, markdown, report …)
```

**Total (current):** ~8,700 lines of Python across 15 modules.

---

## Layer Reference

### Config Layer

#### `config/constants.py`

Single source of truth for every static value used project-wide.

| Constant group | Description |
|---|---|
| `TOOL_*` | Tool identity — name, version, author, repo, contact |
| `VERSION*` | Semantic version components and formatted strings |
| `C_*` | Rich hex colour constants for the cyberpunk theme |
| `DS_*` | Absolute `Path` objects pointing to every dataset file |
| `SCORE_*` | Tier threshold integers (PREMIUM=90, STRONG=75, DECENT=60, WEAK=40) |
| `WEIGHT_*` | Default scoring dimension weights (each 0.0–1.0, sum = 1.0) |
| `NAME_LENGTH_*` | Hard and ideal min/max name lengths |
| `GEN_*` | Generation limits — default count, max count, dedup threshold |
| `CHECK_*` | Network check workers, timeout, retry count |
| `ANIM_*` | Animation timing constants (frame rates, delays) |
| `TLD_SCORES` | `dict[str, int]` — 40 TLDs mapped to desirability score 0–100 |
| `FORBIDDEN_SEQUENCES` | Tuple of 40+ unpronounceable character pairs |
| `BRAND_BLACKLIST_SEED` | `frozenset[str]` — 45 seed brands for trademark checks |
| `VOWELS / CONSONANTS / RARE_CONSONANTS / STRONG_START_CONSONANTS` | Character sets used in phonetic scoring |

**Enums** (all `str, Enum` unless noted):

| Enum | Values |
|---|---|
| `Profile` | tech · ai · security · finance · health · social · education · document · generic |
| `StyleMode` | minimal · futuristic · aggressive · soft · technical · luxury |
| `BrandTier` | PREMIUM · STRONG · DECENT · WEAK · POOR |
| `TMRisk` | none · low · medium · high |
| `AvailStatus` | free · taken · unknown · skip |
| `ExportFormat` | json · csv · markdown · all |
| `MenuOption` | 1–6 (`IntEnum`) |

#### `config/settings.py`

Runtime configuration dataclass with TOML/JSON persistence.

- **File location:** `~/.nexagen/settings.toml`
- **Fallback:** `~/.nexagen/settings.json` (if no TOML library available)
- **Bootstrap:** `get_settings()` returns the module-level singleton; creates the file with defaults on first run.

**Field groups:**

| Group | Fields |
|---|---|
| Generation | `profile`, `style_mode`, `count`, `min_len`, `max_len`, `use_suffixes`, `use_prefixes`, `use_multiword`, `use_synonyms` |
| Analysis | `score_weights` (dict with `pronounce`, `memorability`, `uniqueness`, `length_fit`) |
| Network checks | `do_domain_checks`, `do_handle_checks`, `check_workers`, `check_timeout`, `preferred_tlds`, `check_github`, `check_pypi`, `check_npm`, `check_docker`, `check_huggingface` |
| UI | `animations`, `clear_on_start`, `show_scores`, `show_domains`, `show_handles`, `table_row_limit` |
| Export | `export_dir`, `auto_export`, `export_format` |
| Logging | `log_enabled`, `log_dir`, `log_level` |
| Cache | `cache_enabled`, `cache_dir`, `cache_ttl_seconds` |
| Update | `check_for_updates`, `update_channel` |

**API:**

```python
from nexagen.config.settings import get_settings, save_settings, update_setting

cfg = get_settings()          # returns Settings singleton
cfg.count = 40
save_settings(cfg)            # persist to ~/.nexagen/settings.toml
update_setting("profile", "ai")  # atomic single-field update
```

**Environment overrides** (applied each session, do not persist):

| Variable | Field |
|---|---|
| `NEXAGEN_PROFILE` | `cfg.profile` |
| `NEXAGEN_STYLE` | `cfg.style_mode` |
| `NEXAGEN_COUNT` | `cfg.count` |
| `NEXAGEN_NO_CHECKS` | `cfg.do_domain_checks = False` |
| `NEXAGEN_NO_ANIM` | `cfg.animations = False` |
| `NEXAGEN_EXPORT_DIR` | `cfg.export_dir` |
| `NEXAGEN_LOG_LEVEL` | `cfg.log_level` |

---

### Dataset Layer

Nine plain-text files installed with the package under `nexagen/datasets/`.  
Comment lines start with `#`. One entry per line. All lowercase.

| File | Entries | Format | Purpose |
|---|---|---|---|
| `common_words.txt` | 1,229 | one word per line | Generic English word filter — names matching here are penalised on uniqueness |
| `synonyms.txt` | 324 groups | `root:syn1,syn2,…` | Semantic expansion during keyword processing |
| `tech_terms.txt` | 302 | one term per line | Technology vocabulary for the `tech` / `security` profiles |
| `ai_terms.txt` | 150 | one term per line | AI/ML vocabulary for the `ai` profile |
| `business_terms.txt` | 226 | one term per line | Business vocabulary for finance / health / social profiles |
| `prefixes.txt` | 62 | one prefix per line | Domain prefix variants (`get`, `try`, `use` …) |
| `suffixes.txt` | 129 | one suffix per line | Word and domain suffix variants (`hub`, `lab`, `kit` …) |
| `tlds.txt` | 40 | one TLD per line | Ranked TLD list ordered by desirability |
| `brand_blacklist.txt` | 365 | one brand per line | Known brand names — proximity check triggers trademark risk flag |

---

### Utils Layer

#### `utils/dataset_loader.py`

Single point of truth for all dataset I/O. Every other module that needs dataset data calls this module — no direct file reads elsewhere.

**Key exports:**

```python
from nexagen.utils.dataset_loader import (
    common_words,       # → frozenset[str]
    blacklist,          # → frozenset[str]  (file + BRAND_BLACKLIST_SEED)
    synonyms,           # → dict[str, list[str]]
    tech_terms,         # → list[str]
    ai_terms,           # → list[str]
    business_terms,     # → list[str]
    prefixes,           # → list[str]
    suffixes,           # → list[str]
    tlds,               # → list[str]
    vocab_for_profile,  # (profile: str) → list[str]
    load_all,           # () → DatasetHealth  — eager load at boot
    dataset_health,     # () → DatasetHealth  — non-loading status check
    reset_registry,     # () → None  — for tests only
    WordFilter,         # singleton — .is_common(word)
    SynonymMap,         # singleton — .get(word) / .expand(words)
    BrandBlacklist,     # singleton — .risk_level(name)
)
```

**Caching:** `_DatasetRegistry` holds all loaded data per process. Each dataset path has its own `threading.Lock` to prevent duplicate loads under concurrent access.

#### `utils/text_utils.py`

51 pure functions for text manipulation and linguistic analysis. No I/O, no side effects.

Selected functions:

| Function | Returns | Description |
|---|---|---|
| `normalize(text)` | `str` | Unicode NFKD → ASCII, lowercase |
| `syllable_count(word)` | `int` | Vowel-cluster count heuristic |
| `vowel_ratio(word)` | `float` | Vowel characters / total characters |
| `max_consonant_run(word)` | `int` | Longest consecutive consonant sequence |
| `alternation_score(word)` | `float` | CVCV pattern regularity 0.0–1.0 |
| `has_forbidden_sequence(word)` | `bool` | Match against `FORBIDDEN_SEQUENCES` |
| `soundex(word)` | `str` | Soundex phonetic key |
| `brand_variants(name)` | `dict` | title / camel / kebab / domain variants |
| `starts_with_strong_consonant(word)` | `bool` | Checks `STRONG_START_CONSONANTS` |
| `has_alliteration(word)` | `bool` | First two sounds match |

#### `utils/levenshtein.py`

Full edit-distance library with optional `rapidfuzz` acceleration.

| Algorithm | Description |
|---|---|
| `levenshtein(a, b)` | Classic dynamic-programming edit distance |
| `damerau_levenshtein(a, b)` | Adds transposition operations |
| `jaro(a, b)` | Character alignment similarity 0.0–1.0 |
| `jaro_winkler(a, b, p)` | Jaro with common-prefix bonus |
| `similarity(a, b)` | Unified normalised similarity score |
| `trademark_risk(name, brands)` | Returns `TrademarkHit` — closest matching brand |
| `deduplicate(names, threshold)` | Levenshtein-based deduplication |
| `distance_matrix(names)` | Full pairwise distance matrix |
| `backend_info()` | Reports whether `rapidfuzz` acceleration is active |

If `rapidfuzz` is installed, the library delegates to it for C-level performance. Falls back to pure Python if unavailable.

#### `utils/validators.py`

39 validation functions returning `ValidationResult` (ok/warn/error with error codes).

**Validation categories:**

- **Brand name:** `validate_name_length`, `validate_name_characters`, `validate_name_phonetics`, `validate_name_uniqueness`, `validate_trademark_safety`, `validate_common_word`
- **Domain:** `validate_domain_label`, `validate_domain_name`, `validate_tld`
- **Input:** `validate_keyword`, `validate_keywords`, `validate_count`, `validate_length_range`, `validate_profile`, `validate_style_mode`, `validate_score_weights`
- **Combined:** `validate_all` — runs the full chain and merges results

---

### UI Layer

All UI modules write exclusively to a shared `Console(highlight=False, markup=True)` instance. No module calls `print()` directly.

#### `ui/banner.py`

29 functions for all screen-level rendering:

- `print_banner(animated)` — 6-line ASCII art logo with per-line gradient + typewriter slogan
- `print_main_menu()` — adaptive wide/narrow terminal menu
- `section()` / `subsection()` / `separator()` — dividers used project-wide
- `msg_ok/fail/warn/info/step/result()` — status message helpers
- `prompt_text()` / `prompt_confirm()` — input prompts wrapping `rich.prompt`
- `print_update_available()` — GitHub update notification panel
- `print_session_footer()` / `print_goodbye()` — exit sequence

#### `ui/animations.py`

9 animation classes, all inheriting from `_Animation` (background thread + `Live` render + context manager):

| Class | Use case |
|---|---|
| `Spinner` | Generic braille dots spinner |
| `DotsSpinner` | 3-dot pulse |
| `CyberSpinner` | Glitch-effect for AI operations |
| `ScanBeam` | Left-right horizontal scan for domain checks |
| `PulseBar` | Vertical block pulse for scoring |
| `BootSequence` | Multi-step animated startup checklist |

Additional helpers: `typewriter()`, `count_up()`, `reveal_names()`, `flash_success()`, context managers `live_spinner()`, `live_scan()`, `live_pulse()`.

#### `ui/progress.py`

11 classes for task progress tracking, all wrapping `rich.progress.Progress`:

| Class | Use case |
|---|---|
| `GenerationProgress` | 6-phase name generation pipeline bar |
| `AnalysisProgress` | 4 parallel dimension bars |
| `DomainCheckProgress` | Parallel scan bar + rolling result log |
| `MultiStepProgress` | Stacked bars for multi-stage reports |
| `SimpleBar` | Minimal inline bar for embedded contexts |

Custom columns: `PercentColumn`, `RateColumn`, `StatusBadge`, `PhaseColumn`.

#### `ui/tables.py`

4 result dataclasses and 8 table rendering functions:

| Dataclass | Fields |
|---|---|
| `NameResult` | name, score, tier, pronounce, memorability, uniqueness, length_fit, tm_risk, syllables, domains, platforms, profile, style, keywords |
| `DomainEntry` | domain, status, tld, tld_rank |
| `PlatformEntry` | handle, platform, status |
| `AnalysisData` | All NameResult fields + vowel_ratio, is_common, phonetic_key, notes |

Rendering: `print_names_table()`, `print_score_card()`, `print_domain_table()`, `print_platform_table()`, `print_analysis_table()`, `print_comparison_table()`, `print_startup_report_summary()`, `print_export_summary()`.

---

### CLI Layer

#### `cli/app.py`

Entry point wired to `nexagen = "nexagen.cli.app:main"` in `pyproject.toml`.

**Boot sequence (in order):**

```
1. Parse CLI flags (argparse)
2. Load and patch Settings from flags + env vars
3. If --generate: run headless generate mode and exit
4. Otherwise: NexagenApp.run()
   ├── clear_screen() (if enabled)
   ├── print_banner(animated=True)
   ├── _boot_sequence()
   │   ├── Step 1: Verify all dataset files exist
   │   ├── Step 2: GitHub update check (cached 24h)
   │   ├── Step 3: Load and validate Settings
   │   └── Step 4: Import-test utils modules
   ├── print_update_available() (if newer version found)
   ├── print_ready()
   └── _event_loop()
       └── while True:
           ├── print_banner(animated=False)
           ├── print_main_menu()
           ├── get_choice() → int
           ├── dispatch(choice) → MenuController handler
           └── [choice 6] → break → _shutdown()
```

**Update check:** Hits `https://api.github.com/repos/cyberempirex/nexagen/releases/latest`. Result cached in `~/.nexagen/cache/update_check.json` for 24 hours. Fails silently on any network error within a 5-second timeout.

**Session state** tracked on `NexagenApp`: `_names_generated`, `_checks_run`, `_exports`, `_start_time`.

#### `cli/menu.py`

`MenuController` owns all interactive prompts and flow logic.

| Method | Description |
|---|---|
| `dispatch(choice)` | Routes 1–5 to flow handlers |
| `_flow_generate()` | Keyword collection → quick customise → cmd → export offer |
| `_flow_analyze()` | Name(s) input → score cards + analysis table |
| `_flow_domains()` | Name input → platform toggle → domain/handle checks |
| `_flow_report()` | Project + keywords + count → full multi-step report |
| `_flow_about()` | Delegates to `print_about()` |
| `_quick_customise()` | In-session profile/style/count override |
| `_settings_menu()` | Full settings sub-menu (toggle animations, reset, etc.) |

#### `cli/commands.py`

All command logic — the entire generation and scoring pipeline is self-contained here. Advanced engine modules (`engine/`, `analysis/`, etc.) are imported with `try/except` so the CLI remains functional before those modules are built.

**Name generation pipeline (inside `cmd_generate_names`):**

```
keywords
  │
  ▼  _expand_keywords()
expanded seeds (up to 60)
  │  ├─ synonym lookup (synonyms.txt, 324 groups)
  │  └─ profile vocabulary sampling
  │
  ▼  _generate_candidates()
raw candidates (up to 500)
  │  ├─ Strategy 1: direct seeds
  │  ├─ Strategy 2: seed + suffix
  │  ├─ Strategy 3: prefix + seed
  │  ├─ Strategy 4: seed + seed blends
  │  ├─ Strategy 5: vocabulary sampling
  │  └─ Strategy 6: mutations (vowel-drop, power endings)
  │
  ▼  _deduplicate()
unique candidates (Levenshtein ≤ 2)
  │
  ▼  _score_name() × N  [parallelisable]
  │  ├─ _score_pronounceability()  weight 0.30
  │  ├─ _score_memorability()      weight 0.30
  │  ├─ _score_uniqueness()        weight 0.20
  │  └─ _score_length_fitness()    weight 0.20
  │
  ▼  sort by composite score DESC
top N NameResult objects
```

**Domain availability** (`cmd_domain_suggestions`): RDAP queries via `rdap.org/domain/{domain}`. HTTP 404 = free, HTTP 200 = taken, any exception = unknown. Runs in a `ThreadPoolExecutor` with up to 12 workers.

**Export** (`cmd_export`): Writes JSON (with metadata envelope), CSV (DictWriter), or Markdown (structured report). File naming: `nexagen_export_YYYYMMDD_HHMMSS.{ext}`.

#### `cli/help.py`

17 Rich-formatted help functions covering every aspect of the tool. All are independently callable — no shared state.

| Function | Content |
|---|---|
| `print_help_overview()` | All 6 menu options with descriptions |
| `print_help_generate()` | Pipeline stages, keyword rules, examples |
| `print_help_analyze()` | Scoring dimensions, tier thresholds, multi-input |
| `print_help_domains()` | Variant generation, RDAP method, platforms |
| `print_help_report()` | Report stages, inputs, timing notes |
| `print_help_settings()` | Full settings field reference by group |
| `print_help_export()` | Formats, file naming, directory override |
| `print_help_scoring()` | Full scoring formula with all factor breakdowns |
| `print_help_profiles()` | All 9 profiles with vocabulary sources |
| `print_help_cli_flags()` | argparse flags with descriptions and examples |
| `print_help_env_vars()` | 7 environment variables with values |
| `print_tip(context)` | Random context-specific tip |
| `print_keyboard_reference()` | Key bindings and navigation |

---

## Scoring Algorithm

The composite brand score is a weighted sum of four independent dimensions:

```
composite = (
    pronounce    × weight_pronounce    +   # default 0.30
    memorability × weight_memorability +   # default 0.30
    uniqueness   × weight_uniqueness   +   # default 0.20
    length_fit   × weight_length_fit       # default 0.20
)
```

All inputs and outputs are integers 0–100.

### Pronounceability

| Factor | Effect |
|---|---|
| Vowel ratio 30–55% | +20 |
| Vowel ratio 20–30% or 55–65% | +8 |
| Vowel ratio outside 20–65% | −15 |
| Max consonant run ≤ 1 | +15 |
| Max consonant run = 2 | +8 |
| Max consonant run = 3 | −5 |
| Max consonant run ≥ 4 | −20 |
| Alternation score (0–1) | × 15 bonus |
| Forbidden sequence hit | −20 |
| 2–3 syllables | +10 |
| >4 syllables | −10 |

### Memorability

| Factor | Effect |
|---|---|
| Length 4–8 chars | +20 |
| Length < ideal min | graduated penalty |
| Length > 10 chars | −3 per char |
| Strong opening consonant | +8 |
| Ends on vowel | +6 |
| Alliteration | +8 |
| 2 syllables | +12 |
| 3 syllables | +8 |

### Uniqueness

| Factor | Effect |
|---|---|
| Exact match in common_words.txt | −25 |
| Levenshtein ≤ 1 from blacklisted brand | −30 (floor 0) |
| Levenshtein ≤ 2 from blacklisted brand | −30 |
| Levenshtein ≤ 3 from blacklisted brand | −10 |
| Distance ≤ 1 from pool candidate | −30 |
| Distance = 2 from pool candidate | −15 |

### Length Fitness

| Input | Effect |
|---|---|
| Within `min_len`–`max_len` | Score = max(0, 100 − delta × 12) + 10 |
| Outside range | Penalty scales with distance from ideal midpoint |

---

## Data Flow Diagram

```
User input (keywords)
       │
       ▼
cli/menu.py  →  cli/commands.py
                     │
              ┌──────┴──────────────────────┐
              │                             │
              ▼                             ▼
  utils/dataset_loader.py        utils/text_utils.py
  (vocabulary, synonyms,         (normalize, syllable_count,
   common words, blacklist)       vowel_ratio, soundex …)
              │                             │
              └──────────────┬──────────────┘
                             │
                             ▼
                  Candidate generation (6 strategies)
                             │
                             ▼
                  utils/levenshtein.py
                  (deduplication, tm_risk)
                             │
                             ▼
                  Scoring (4 dimensions)
                             │
                             ▼
                  ui/tables.py (NameResult)
                             │
                             ▼
                  Domain checks (RDAP / urllib)
                  Platform checks (GitHub, PyPI, npm)
                             │
                             ▼
                  cli/commands.py cmd_export()
                  → ~/.nexagen/exports/
```

---

## File System Layout (Runtime)

```
~/.nexagen/
├── settings.toml          User settings (TOML)
├── settings.json          Fallback settings (JSON, no TOML lib)
├── history.json           Generation history (up to 500 entries)
├── exports/               Export output directory
│   ├── nexagen_export_20260305_143022.json
│   ├── nexagen_export_20260305_143022.csv
│   └── nexagen_export_20260305_143022.md
├── cache/
│   └── update_check.json  GitHub update check cache (TTL 24h)
└── logs/
    └── nexagen.log        File log (if log_enabled = true)
```

---

## Dependencies

**Required** (declared in `pyproject.toml`):

| Package | Version | Purpose |
|---|---|---|
| `rich` | ≥ 13.0 | All terminal UI output — tables, progress, panels, colour |
| `typer` | ≥ 0.9 | Planned CLI extension layer (currently using argparse core) |
| `httpx` | ≥ 0.27 | Planned async HTTP for domain/platform checks |
| `rapidfuzz` | ≥ 3.0 | Optional C-level Levenshtein acceleration |

**Standard library only for core logic:** `argparse`, `json`, `csv`, `concurrent.futures`, `threading`, `urllib.request`, `pathlib`, `dataclasses`, `functools`, `re`, `time`, `os`, `sys`.

**Python version:** 3.9 or later (3.10+ recommended for `match` statement support in future modules).

---

## Testing

Test files are located under `tests/`:

```
tests/
├── test_generation.py   Name generation pipeline tests
├── test_scoring.py      Scoring dimension unit tests
└── test_domains.py      Domain generation and check tests
```

Run tests:

```bash
pip install -e ".[dev]"
pytest
pytest --cov=nexagen --cov-report=term-missing
```

Coverage threshold: 60% (configured in `pyproject.toml`).

---

## Extending NEXAGEN

### Adding a new profile

1. Add the value to `Profile` in `config/constants.py`
2. Add the vocabulary mapping in `utils/dataset_loader.py` → `vocab_for_profile()`
3. Add the profile description in `cli/help.py` → `print_help_profiles()`

### Adding a new dataset

1. Place the `.txt` file in `nexagen/datasets/`
2. Add a `DS_*` path constant in `config/constants.py`
3. Register it in `_DATASET_MANIFEST` in `utils/dataset_loader.py`
4. Add a public accessor function in `utils/dataset_loader.py`

### Adding a new platform check

1. Create `nexagen/checks/{platform}_check.py`
2. Implement `check_{platform}(handle, timeout) → str` returning `"free" | "taken" | "unknown"`
3. Wire into `cli/commands.py` → `cmd_domain_suggestions()` platform task list
4. Add the settings toggle to `config/settings.py` and `cli/help.py`

---

*NEXAGEN is part of the CyberEmpireX (CEX) ecosystem.*  
*© CEX-Nexagen · MIT License · https://github.com/cyberempirex/nexagen*
