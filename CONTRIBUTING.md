# Contributing to Nexagen

> **NEXAGEN** · CEX-Nexagen · Developed by CyberEmpireX

Thank you for your interest in contributing to Nexagen.

Nexagen is part of the **CEX (CyberEmpireX)** ecosystem — a collection of
practical, well-engineered tools focused on intelligent automation, structured
data, and real-world usability. Community contributions help improve
stability, expand datasets, refine algorithms, and push the engine toward
becoming the most capable platform naming intelligence tool available.

---

## Ways to Contribute

Every meaningful improvement is welcome. You can contribute by:

- Improving name generation algorithms or linguistic logic
- Expanding datasets — prefixes, suffixes, industry terms, synonyms
- Improving domain intelligence and TLD strategies
- Adding new platform availability checks
- Improving CLI interface, menus, or terminal UX
- Improving scoring models — phonetics, memorability, uniqueness
- Writing or improving tests
- Fixing bugs or performance issues
- Improving documentation

---

## Before You Start

Please take a few minutes to understand the project:

- Read `docs/architecture.md` to understand the module structure
- Review the existing dataset format in `nexagen/datasets/`
- Run the tool locally before making changes
- Make sure your idea does not duplicate existing functionality

If you are planning a large change, open an issue first to discuss it.
Small fixes and dataset improvements can be submitted directly as pull requests.

---

## Folder Structure

Nexagen follows a strict modular structure. Please do not reorganize folders
or move files between modules without prior discussion.

```
nexagen/
├── cli/          — interface, menus, commands
├── engine/       — name generation and transformation
├── analysis/     — scoring, phonetics, uniqueness
├── domains/      — domain generation, ranking, checking
├── checks/       — platform availability checks
├── datasets/     — curated data files (.txt)
├── ui/           — visual output, tables, banners
├── export/       — JSON, CSV, Markdown exporters
├── config/       — settings, constants
└── utils/        — shared helpers and loaders
```

Each module has a defined responsibility. Keep new code within the correct
module and avoid creating cross-dependencies between unrelated modules.

---

## Code Standards

All contributions must follow these standards:

**1. Clean and readable code**
Write code that another developer can understand without needing comments on
every line. Use clear variable names and logical structure.

**2. Modular design**
Each function should do one thing. Avoid writing long functions that mix
multiple responsibilities.

**3. No unnecessary dependencies**
Do not introduce new third-party packages unless absolutely necessary and
clearly justified in your pull request.

**4. Backward compatibility**
Do not break existing features. If your change modifies an existing interface,
document the change clearly and update any affected tests.

**5. Type hints**
Use Python type hints for all function signatures.

**6. Tests**
Add tests for any significant new functionality. Place tests in the `tests/`
directory following the existing naming convention.

---

## Dataset Contributions

Dataset files live in `nexagen/datasets/` and follow a strict format:

```
# Comment lines start with #
word
another_word
third_word
```

Rules for all dataset files:

- One entry per line
- Lowercase only
- No spaces within entries
- No punctuation
- No duplicate entries
- No invented or artificial words
- No brand names or trademarks

When adding new words to an existing dataset, place them within the
appropriate category section. Do not mix categories.

When creating a new dataset file, include a header comment block that
describes the file's purpose, format, and category coverage.

---

## Pull Request Process

1. **Fork** the repository
2. **Create a branch** with a descriptive name:
   ```
   feature/improve-domain-ranking
   fix/phonetic-score-edge-case
   dataset/expand-ai-terms
   docs/update-architecture
   ```
3. **Implement your changes** following the standards above
4. **Test your changes** locally — ensure existing tests still pass
5. **Submit a pull request** with a clear title and description that explains:
   - What the change does
   - Why it is needed
   - How it was tested

Pull requests that break existing tests, introduce unnecessary dependencies,
or lack a clear description will not be merged until these issues are resolved.

---

## Credit and Attribution

Nexagen is original work created under the **CEX-Nexagen** identity,
developed by **CyberEmpireX**.

If you fork, reuse, or redistribute Nexagen code:

- The original `LICENSE` file must remain intact and unmodified
- The copyright notice must not be removed or altered
- Proper attribution to **CEX-Nexagen (CyberEmpireX)** must be preserved
  in all forks and redistributions
- Contributions must not remove, overwrite, or obscure author credits

This ensures fair and lasting recognition of the original work and the
contributors who helped build it.

---

## Conduct

All contributors are expected to:

- Communicate respectfully in issues and pull requests
- Provide constructive and specific feedback
- Collaborate professionally and in good faith
- Focus on improving the tool, not personal agendas

---

## Questions

If you have a question about the architecture, a dataset, or a potential
contribution, open a GitHub issue with the label `question` and describe
what you are trying to understand.

---

Thank you for helping improve Nexagen.

*NEXAGEN · CEX-Nexagen · Developed by CyberEmpireX*
*Generate · Analyze · Validate · Discover*
