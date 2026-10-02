# Contributing

Open Coach is a free, community-driven coach for athletes. Contributions of every kind are welcome: bug reports, coaching methodology, new watch platforms (COROS, Suunto, Polar…), translations, docs and code.

By participating you agree to follow the [Code of Conduct](.github/CODE_OF_CONDUCT.md).

## How to contribute

1. **Open an issue first** for anything non-trivial (new tool, new provider, new coaching rule), so the approach can be agreed before you write code. Security problems go through a [private advisory](.github/SECURITY.md), never a public issue.
2. **Fork, then branch** from `main`.
3. **Set up** the project:

   ```bash
   uv sync                           # Python 3.12, dev tools included
   uv run pre-commit install         # run the CI checks on every commit
   uv run python scripts/setup_local.py   # personal templates, gitignored
   ```

4. **Write tests** with your change. Tests never touch a real account or your real data (`tests/conftest.py` isolates storage and stubs the watch).
5. **Check** exactly what CI checks:

   ```bash
   uv run pre-commit run --all-files   # ruff, ruff format, mypy, personal-data audit
   uv run pytest
   ```

6. **Open a pull request** and fill in the template. On your first PR, the CLA bot asks you to accept the [Contributor License Agreement](CLA.md) by posting a comment; it covers all your future contributions.

### Issues and epics

- **Finding work**: `good first issue` marks small, well-scoped issues for a first contribution; `help wanted` marks everything open to contributors. Comment on an issue to claim it before you start, so two people don't work on the same thing.
- **Epics** (label `epic`) are umbrella issues for a larger goal. Their work is split into **sub-issues**, shown with a progress bar on the epic. A sub-issue that needs another one first is marked "blocked by" it: start with the unblocked ones.
- **Proposing a sub-issue**: use the **Part of an epic** template. A maintainer attaches it to the epic.
- **One pull request per sub-issue**, when possible. Link it in the PR description:
  - `Closes #<sub-issue>` for the sub-issue it completes (GitHub closes it on merge);
  - `Part of #<epic>` to show the epic it belongs to. Never `Closes #<epic>`: a maintainer closes the epic once its last sub-issue is done.

### Why a CLA?

Open Coach is licensed under the **AGPL-3.0**: it stays free for everyone, and anyone who builds on it, including as an online service, must publish their changes under the same licence. The project is also **dual-licensed**: the maintainer may offer commercial terms (for example a hosted service) to fund its development. The CLA gives the maintainer the right to include your contribution in those offers; you keep your copyright, and your contribution always remains available to everyone under the AGPL-3.0. See [CLA.md](CLA.md).

### Where things go

- Coaching rules → `.agents/skills/coaching-rules/` (generic methodology, never one athlete's data)
- MCP tools → `src/open_coach/tools/` (see `AGENTS.md` § "Adding a new MCP tool or resource")
- A new watch platform → `src/open_coach/providers/` (see `AGENTS.md` § "Watch providers"; `tests/test_provider_contract.py` is the contract to pass)
- Text the code shows to athletes → `src/open_coach/i18n.py`, in English and French

## Data separation policy

Most important rule of the project: **no personal data ever enters versioned files**, so any athlete can use it without inheriting someone else's.

**Absolute rule**: no personal data ever contaminates versioned code. The project must be forkable by any athlete without bias — there is *no* "default athlete" baked into this repo.

### Forbidden in versioned files (skills, hooks, scripts, src/, docs)

- Specific target race names
- Absolute race dates (e.g. `2031-01-01`)
- Hardcoded paces / HR / VDOT / weight
- Personal physical constraints in plain text (tendons, ankles, etc.)
- Personal preferences (gel format, weekly cap, recurring time slots)
- Email, login, password, tokens — never in clear text
- Filenames specific to one athlete (e.g. `<race-slug>-<date>.md` containing a personal race name)

### Allowed in versioned files

- Generic methodology rules (Daniels VDOT, 80/20, periodization)
- Generic coaching keywords (race, marathon, pace, threshold…)
- Architecture patterns (read profile file, graceful fallback)
- Templates with `<...>` placeholders in `plans/.templates/` and `.claude/local.example/`

### Personal data lives here (gitignored)

- `plans/` — active plan render, `athlete-profile.md`, `training-journal.md`, `references/`, `archive/` (past plans, drafts)
  - Except `plans/.templates/` which stays versioned (skeletons)
- `.claude/local/hooks.config.json` — hook overrides (extra keywords, watched filenames, custom paths)
- `~/.open-coach/` — profile.json, goals.json, plans/active.json, registries
- `~/.garth/` — Garmin tokens
- `~/.claude/projects/<project-hash>/memory/` — Claude auto-memory

### Reading personal data at runtime

- Skills read `plans/athlete-profile.md` at startup if present (instruction inside the SKILL.md, no hardcoded fallback)
- Hooks read `.claude/local/hooks.config.json` if present (`json.load` inside a silent `try/except FileNotFoundError`)
- Missing file → reasonable generic fallback, never a crash, never a hardcoded personal value

### Onboarding a fork (fresh clone)

```bash
uv sync
uv run python scripts/setup_local.py   # copy templates into plans/ and .claude/local/ (add --lang fr for French templates)
# then edit the generated files with your own values
```

### Verification

- `uv run python scripts/audit_docs.py` includes a check that greps versioned files for personal-data shapes and **fails the audit** if any leak is found.
- The default pattern list is **structural only**: home directories (`/home/<user>`, `C:\Users\<user>`), real e-mail addresses, Google Drive folder IDs, inline secrets. It never names a person, city, club or race, so it is identical on every fork. Your own markers (surname, nickname, home town, race names, …) **never enter this file**. Add them at runtime via the `OPEN_COACH_AUDIT_EXTRA_PATTERNS` env var (CSV of regex), and set it in CI as a repository secret if you run the workflow on a fork:

  ```bash
  export OPEN_COACH_AUDIT_EXTRA_PATTERNS="surname,emailpart,nickname"
  uv run python scripts/audit_docs.py
  ```

- Before any major commit, run `uv run python scripts/audit_docs.py` and fix leaks before pushing.
- The repo is written in English. `audit_docs.py` fails on French in versioned text; intentional French (bilingual skill triggers, glossary sections, legacy aliases, the `i18n.py` table, `*.fr.template.md`, tests of French parsing) is allowlisted, or mark a Python line with `# fr-ok`.
- The audit resolves the Claude memory directory automatically; override with `OPEN_COACH_MEMORY_DIR` if your memory lives elsewhere.

## Extending the project

### Adding a new MCP tool

See `AGENTS.md` § "Adding a new MCP tool or resource" — concise 5-step recipe (module under `src/open_coach/tools/`, `@mcp.tool()` decorator, `ctx.lifespan_context` for shared state, import in `server.py`, separate pure-logic from I/O wrapper).

### Adding a coaching rule

Methodology rules live in `.agents/skills/coaching-rules/`. Add the rule to the file under `references/` that matches its topic (`methodology.md`, `dsl-conventions.md`, `anti-patterns.md`), as a named section listed in that file's `## Contents`; `SKILL.md` only holds the reading cycle, the journal rules and the index of those files. Keep the rule generic: athlete-specific data belongs in `plans/athlete-profile.md`, read at runtime. Run `uv run python scripts/audit_docs.py` before committing.

### Adding a workflow skill

Workflow skills live in `.agents/skills/<name>/SKILL.md` and follow the [Agent Skills specification](https://agentskills.io/specification) (authoring rules in `AGENTS.md` § "Skills / guides architecture", checked by `tests/test_skills_spec.py`); add the name to `WORKFLOWS` and `GuideName` in `src/open_coach/guides.py` so it is also served as an MCP prompt (`tests/test_llm_portability.py` fails otherwise). They reference the `coaching-rules` skill for rules and call MCP tools to perform the work. Trigger phrases (`description:` frontmatter) should be non-overlapping with `coaching-rules` and with each other. Keep them client-neutral: call tools (`get_coaching_context`, `get_coaching_guide("…")`) rather than reading a `coach://` resource only, and never rely on a Claude-only feature — the same text is served to every MCP client.

## Commit style

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject` (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`…), imperative, with a body explaining *why* when it is not obvious. Keep messages factual about the diff: no tool-attribution footers (`Co-Authored-By: <AI tool>`, "Generated with …").
