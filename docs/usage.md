# NEXAGEN — Usage Guide

> **NEXAGEN** · Platform Naming Intelligence Engine  
> CEX-Nexagen · Developed by CyberEmpireX  
> Version 1.0.0 · https://github.com/cyberempirex/nexagen

---

## What is NEXAGEN?

NEXAGEN is a command-line tool that helps developers, founders, and creators find strong, usable names for platforms, tools, startups, and digital products.

It takes keywords you provide, expands them through a curated vocabulary and synonym system, generates candidate names using multiple linguistic strategies, scores each one on four brand quality dimensions, then checks domain and platform handle availability — all in a single interactive session.

**NEXAGEN does not generate random letter combinations.** Every name it produces starts from real vocabulary, industry terminology, and semantic relationships. The result is names that feel natural, are pronounceable, and are grounded in your product's actual domain.

---

## Installation

### From PyPI (recommended)

```bash
pip install nexagen
```

### From source

```bash
git clone https://github.com/cyberempirex/nexagen
cd nexagen
pip install -e .
```

### Development install (includes test tools)

```bash
pip install -e ".[dev]"
```

**Requirements:** Python 3.9 or later. All other dependencies (`rich`, `typer`, `httpx`, `rapidfuzz`) are installed automatically.

**Optional acceleration:** Install `rapidfuzz` to speed up all Levenshtein and similarity calculations via a C extension:

```bash
pip install rapidfuzz
```

---

## Starting NEXAGEN

### Interactive mode (default)

```bash
nexagen
```

Launches the full interactive interface with animated startup, boot sequence, and the main menu.

### Headless mode (scripts / CI)

Generate names immediately without entering the interactive menu:

```bash
nexagen --generate ai data pipeline
nexagen -g cloud security platform --count 40
nexagen --generate startup tool --profile tech --style futuristic
```

---

## CLI Flags

| Flag | Short | Description |
|---|---|---|
| `--version` | `-v` | Print version and exit |
| `--no-anim` | | Disable all animations |
| `--no-clear` | | Do not clear the screen on startup |
| `--profile PROFILE` | `-p` | Set industry profile for this session |
| `--style STYLE` | | Set naming style for this session |
| `--count N` | `-n` | Number of names to generate (1–200) |
| `--generate KW …` | `-g` | Generate from keywords and exit |
| `--no-update-check` | | Skip the GitHub update check at startup |

**Profile choices:** `tech` `ai` `security` `finance` `health` `social` `education` `document` `generic`

**Style choices:** `minimal` `futuristic` `aggressive` `soft` `technical` `luxury`

---

## Main Menu

When NEXAGEN starts, the main menu presents six options:

```
   1  Generate Names            Create brand candidates from keywords
   2  Analyze Brand Strength    Score and evaluate an existing name
   3  Domain Suggestions        Discover available domains for a name
   4  Startup Naming Report     Full intelligence report for a project

   5  About NEXAGEN             Version, ecosystem, and tool details
   6  Exit                      Quit the application
```

Enter the option number and press **Enter**.  
Press **Ctrl+C** at any sub-prompt to cancel and return to the menu.

---

## Option 1 — Generate Names

The core feature. Takes keywords and runs the full generation + scoring pipeline.

### How to use

1. Select option **1** from the menu.
2. Enter 1–8 keywords describing your product. Separate with commas or spaces:
   ```
   Keywords → ai document tool
   Keywords → cloud security platform
   Keywords → minimal note taking app
   ```
3. Optionally customise the generation settings for this run (profile, style, count).
4. NEXAGEN generates and scores candidates, then shows a ranked results table.
5. After the table, you are offered the option to export the results.

### Keyword tips

- **Be specific.** `data pipeline` produces better results than `software`.
- **Use 2–4 keywords.** More keywords expand the vocabulary more — but beyond 6 starts to dilute focus.
- **Domain-specific terms work best.** `inference`, `vector`, `embed` for AI tools. `ledger`, `trade`, `capital` for fintech.
- **Avoid filler words.** `tool`, `app`, `platform` are already baked into the generation strategies.

### What the results table shows

Each row in the results table shows:

| Column | Description |
|---|---|
| `#` | Rank by composite score |
| `Name` | Generated brand name (capitalised for display) |
| `Score` | Composite score 0–100 with visual bar |
| `Tier` | PREMIUM · STRONG · DECENT · WEAK · POOR |
| `Pron` | Pronounceability score 0–100 |
| `Mem` | Memorability score 0–100 |
| `Uniq` | Uniqueness score 0–100 |
| `TM` | Trademark risk: none · low · medium · high |
| `Syl` | Syllable count |
| `Domain` | Best available domain or top domain status |

### Score tiers

| Tier | Score | Meaning |
|---|---|---|
| ◆ PREMIUM | 90–100 | Exceptional — all metrics above threshold |
| ▲ STRONG | 75–89 | Strong candidate — good to proceed with |
| ● DECENT | 60–74 | Usable — some weak dimensions |
| ▼ WEAK | 40–59 | Problematic — significant issues |
| ✕ POOR | 0–39 | Avoid — multiple metric failures |

---

## Option 2 — Analyze Brand Strength

Evaluate an existing name or compare several candidates.

### How to use

1. Select option **2**.
2. Enter a name, or multiple names separated by commas:
   ```
   Name(s) → paperdesk
   Name(s) → paperdesk, paperflow, paperhub
   ```
3. NEXAGEN scores each name and shows:
   - A **score card** for each name (first 3 shown individually)
   - A **comparison table** for multiple names side by side

### What the score card shows

The score card for each name displays:

- Composite score with visual progress bar
- Brand tier and tier indicator
- Per-dimension bars: Pronounceability · Memorability · Uniqueness · Length Fitness
- Metrics strip: syllables · vowel ratio · TM risk · is common word · Soundex phonetic key
- Notes (e.g. "Contains awkward consonant cluster", "Exceptional brand name")

### Trademark risk levels

| Level | What it means |
|---|---|
| `none` | No known brand within Levenshtein distance 3 |
| `low` | A known brand is at edit-distance 3 |
| `medium` | A known brand is at edit-distance 2 |
| `high` | A known brand is at edit-distance ≤ 1 (very close) |

**Always verify trademarks independently before using any name.** NEXAGEN's TM risk is a proximity heuristic only — it does not replace a formal trademark search.

---

## Option 3 — Domain Suggestions

Generate domain variants for a brand name and check their availability.

### How to use

1. Select option **3**.
2. Enter the brand name:
   ```
   Brand name → nexagen
   ```
3. Choose whether to also check platform handles (GitHub, PyPI, npm).
4. NEXAGEN generates up to 40 domain variants and checks each one.

### What gets checked

**Domain variants generated:**

- `name.com` · `name.io` · `name.ai` · `name.co` · `name.dev` (preferred TLDs)
- `name` + all 40 ranked TLDs from the TLD list
- `prefix + name.tld` (e.g. `getnexagen.com`, `trynexagen.io`)
- `name + suffix.tld` (e.g. `nexagenhub.com`, `nexagenlab.io`)

**Platform handles checked:**

| Platform | Check URL |
|---|---|
| GitHub | `https://api.github.com/users/{handle}` |
| PyPI | `https://pypi.org/pypi/{package}/json` |
| npm | `https://registry.npmjs.org/{package}` |

**Availability method:** RDAP (Registry Data Access Protocol via `rdap.org`). A 404 response = FREE. A 200 response = TAKEN. Network failures = UNKNOWN.

### Domain table columns

| Column | Description |
|---|---|
| `Domain` | Full domain name |
| `Status` | FREE · TAKEN · UNKNOWN |
| `TLD` | The top-level domain |
| `Rank` | TLD desirability score 0–100 |

---

## Option 4 — Startup Naming Report

The most comprehensive mode. Runs the full pipeline in one operation.

### How to use

1. Select option **4**.
2. Enter a project or startup name (used as the report header):
   ```
   Project name → My AI Startup
   ```
3. Enter 1–6 keywords:
   ```
   Keywords → ai document workflow
   ```
4. Enter how many names to generate (default 20).
5. Watch the animated multi-step progress report build in real time.

### What the report includes

1. **Name generation** — candidates from keywords using all strategies
2. **Brand scoring** — all candidates scored on 4 dimensions
3. **Domain discovery** — domain checks for the top 5 names
4. **Platform checks** — GitHub, PyPI, npm for the best name
5. **Summary display** — ranked table + domain grid + statistics strip

### Timing

The report typically takes 15–90 seconds depending on network latency for domain checks. Disable checks for offline use:

```bash
NEXAGEN_NO_CHECKS=1 nexagen
```

---

## Export

After each operation completes, NEXAGEN offers to export results.

### Formats

| Format | Extension | Contents |
|---|---|---|
| `json` | `.json` | Full structured data with metadata envelope (version, date, count) |
| `csv` | `.csv` | Flat table with header row — compatible with Excel, pandas, Google Sheets |
| `markdown` | `.md` | Formatted report with sections per name — ready for Notion or GitHub |
| `all` | `*` | Writes all three formats simultaneously |

### File naming

```
nexagen_export_YYYYMMDD_HHMMSS.{ext}

Example:
    nexagen_export_20260305_143022.json
    nexagen_export_20260305_143022.csv
    nexagen_export_20260305_143022.md
```

### Default export directory

```
~/.nexagen/exports/
```

Override for one session:
```bash
NEXAGEN_EXPORT_DIR=/path/to/dir nexagen
```

Override permanently (edit `~/.nexagen/settings.toml`):
```toml
export_dir = "/path/to/dir"
```

---

## Settings

NEXAGEN stores your preferences in `~/.nexagen/settings.toml`. On first run the file is created with defaults.

### Edit settings

The simplest way is to edit the file directly:
```bash
nano ~/.nexagen/settings.toml
```

Or change them for one session using the quick customise prompt that appears before each generation run.

### Key settings

#### Generation

```toml
profile    = "generic"   # tech · ai · security · finance · health · social · education · document · generic
style_mode = "minimal"   # minimal · futuristic · aggressive · soft · technical · luxury
count      = 20          # names to generate per run (1–200)
min_len    = 4           # minimum name length in characters
max_len    = 8           # maximum name length in characters
use_suffixes  = true     # apply suffix strategies
use_prefixes  = true     # apply prefix strategies
use_multiword = true     # allow compound word blends
use_synonyms  = true     # expand via synonyms.txt
```

#### Scoring weights

```toml
[score_weights]
pronounce    = 0.30
memorability = 0.30
uniqueness   = 0.20
length_fit   = 0.20
```

All four weights must sum to 1.0.

#### Domain and platform checks

```toml
do_domain_checks  = true     # run RDAP domain availability checks
do_handle_checks  = true     # check platform handles
check_workers     = 12       # parallel check threads
check_timeout     = 8.0      # per-request timeout in seconds
preferred_tlds    = ["com", "io", "ai", "co", "dev"]
check_github      = true
check_pypi        = true
check_npm         = true
check_docker      = true
check_huggingface = true
```

#### Interface

```toml
animations      = true   # Rich animations
clear_on_start  = true   # clear screen on startup
show_scores     = true   # score columns in table
show_domains    = true   # domain column in table
table_row_limit = 30     # max rows shown in results table
```

#### Export

```toml
export_dir    = "~/.nexagen/exports"
auto_export   = false          # auto-export every run without prompting
export_format = "json"         # default format: json · csv · markdown · all
```

#### Logging

```toml
log_enabled = false
log_level   = "WARNING"   # DEBUG · INFO · WARNING · ERROR
log_dir     = "~/.nexagen/logs"
```

#### Cache and updates

```toml
cache_enabled     = true
cache_ttl_seconds = 3600   # 1 hour
check_for_updates = true
update_channel    = "stable"
```

---

## Environment Variables

Override settings for a single session without touching the config file. Useful for CI pipelines, Docker images, and shell scripts.

| Variable | Description | Example |
|---|---|---|
| `NEXAGEN_PROFILE` | Industry profile | `ai` |
| `NEXAGEN_STYLE` | Naming style | `futuristic` |
| `NEXAGEN_COUNT` | Names to generate | `50` |
| `NEXAGEN_NO_CHECKS` | Disable availability checks | `1` |
| `NEXAGEN_NO_ANIM` | Disable animations | `1` |
| `NEXAGEN_EXPORT_DIR` | Output directory | `/tmp/exports` |
| `NEXAGEN_LOG_LEVEL` | Log verbosity | `DEBUG` |

### Examples

```bash
# AI profile, 50 names, export to /tmp
NEXAGEN_PROFILE=ai NEXAGEN_COUNT=50 NEXAGEN_EXPORT_DIR=/tmp nexagen --generate agent

# Offline run — no domain checks, no animations
NEXAGEN_NO_CHECKS=1 NEXAGEN_NO_ANIM=1 nexagen --generate fintech tool

# Debug logging to stderr
NEXAGEN_LOG_LEVEL=DEBUG nexagen 2>nexagen.log

# Full CI-friendly headless run
NEXAGEN_PROFILE=tech NEXAGEN_COUNT=30 NEXAGEN_NO_ANIM=1 NEXAGEN_NO_CHECKS=1 \
  nexagen --generate cloud platform --style technical > names.txt
```

---

## Profiles and Styles

### Industry profiles

Profiles control which vocabulary datasets are emphasised during keyword expansion and candidate generation.

| Profile | Best for | Primary vocabulary |
|---|---|---|
| `tech` | Developer tools, APIs, infrastructure | tech_terms.txt (302 terms) |
| `ai` | Machine learning, AI, data science | ai_terms.txt (150 terms) |
| `security` | Cybersecurity, infosec, privacy | tech_terms.txt |
| `finance` | Fintech, payments, banking | business_terms.txt (226 terms) |
| `health` | Healthtech, medical, wellness | business_terms.txt |
| `social` | Social platforms, communities | business_terms.txt |
| `education` | Edtech, learning tools | business_terms.txt |
| `document` | Writing, productivity, docs | business_terms.txt |
| `generic` | General purpose | All vocabularies blended |

### Naming styles

Styles influence which mutation patterns and suffix/prefix strategies are applied.

| Style | Character | Example names |
|---|---|---|
| `minimal` | Clean, short. 4–6 chars preferred. | `nexio`, `logix`, `vorex` |
| `futuristic` | Power endings: -ex, -ix, -on, -en | `dataexon`, `vaultrix`, `fluxen` |
| `aggressive` | Hard consonants, impact-focused | `stackforge`, `gridlock`, `datacrux` |
| `soft` | Vowel endings, -ly, -fy, -io | `floatly`, `cloudify`, `notely` |
| `technical` | Compound precision, -ops, -base, -kit | `devbase`, `codeops`, `apikit` |
| `luxury` | Short, premium feel. 4–5 chars | `velox`, `aurai`, `nexo` |

---

## Use Cases

### Finding a name for a new developer tool

```bash
nexagen --profile tech --style minimal --count 40 --generate cli automation builder
```

Or interactively, choose option 1 and enter `cli automation builder` as keywords with profile `tech`.

### Naming an AI product

```bash
nexagen --profile ai --style futuristic --count 50 --generate reasoning agent model
```

### Checking if a specific name is strong enough

Choose option 2 and enter the name. Look for a score ≥ 75 (STRONG tier) before proceeding.

### Getting a complete view before committing to a name

Use option 4 (Startup Naming Report). Enter your project name, 3–5 keywords, and let the report run. It gives you a ranked table, domain availability, and platform handles in one pass.

### Automating name generation in a script

```bash
#!/bin/bash
NEXAGEN_NO_ANIM=1 NEXAGEN_NO_CHECKS=1 NEXAGEN_COUNT=30 \
  nexagen --generate "$@" --no-clear 2>/dev/null
```

---

## Files Created by NEXAGEN

```
~/.nexagen/
├── settings.toml          Your saved settings
├── history.json           Generation history (last 500 runs)
├── exports/               All exported files
├── cache/
│   └── update_check.json  GitHub update check cache
└── logs/
    └── nexagen.log        Log output (if enabled)
```

To reset completely:

```bash
rm -rf ~/.nexagen
nexagen   # will re-create with defaults
```

---

## Updating NEXAGEN

NEXAGEN checks for updates automatically at startup (once per 24 hours). When a newer version is found, a notification panel is displayed before the main menu.

To update:

```bash
pip install --upgrade nexagen
```

To disable the update check permanently:

```toml
# ~/.nexagen/settings.toml
check_for_updates = false
```

Or for one session:

```bash
nexagen --no-update-check
```

---

## Troubleshooting

### Names look random or unrelated to my keywords

- Check your profile setting — `generic` uses a blended vocabulary.
  Set `--profile ai` or `--profile tech` for more focused results.
- Use more specific keywords. `inference model` produces better results than `ai tool`.
- Try `--count 50` or more to widen the search before top results are selected.

### Domain checks are slow or all showing UNKNOWN

- Network latency to `rdap.org` varies. Run `ping rdap.org` to check connectivity.
- Increase `check_timeout` in settings (default 8 seconds).
- Reduce `check_workers` if your network cannot handle parallel requests.
- Use `NEXAGEN_NO_CHECKS=1` to skip checks entirely and just get names.

### The boot sequence fails on "Engine ready"

- Run `pip install nexagen` again to ensure all files are installed correctly.
- Check that Python can import the utils: `python -c "from nexagen.utils.text_utils import normalize"`

### Settings file is corrupt or ignored

```bash
rm ~/.nexagen/settings.toml
nexagen   # recreates with defaults
```

### Animations flicker or look broken

```bash
nexagen --no-anim
```

Or set `animations = false` in `~/.nexagen/settings.toml`.

---

## Attribution and License

NEXAGEN is developed by **CEX-Nexagen** as part of the **CyberEmpireX (CEX)** ecosystem — a collection of practical, well-engineered tools focused on intelligent automation and real-world usability.

- **License:** MIT
- **Repository:** https://github.com/cyberempirex/nexagen
- **Issues / Requests:** https://github.com/cyberempirex/nexagen/issues

If you fork or build upon this tool, please retain proper attribution to CEX-Nexagen in your documentation and source files.

**Disclaimer:** NEXAGEN provides naming suggestions and preliminary trademark proximity signals. It does not constitute legal advice. Always perform a formal trademark search before commercialising any name. The generated names are not pre-cleared for trademark use.

---

*Generate · Analyze · Validate · Discover*  
*NEXAGEN v1.0.0 · CEX-Nexagen · CyberEmpireX*
