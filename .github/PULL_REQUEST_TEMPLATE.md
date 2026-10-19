## What and why

<!-- What this PR changes and the problem it solves. -->

<!-- Linked issue: "Closes #<issue>" for the issue this PR completes, plus "Part of #<epic>" when it belongs to an epic. Never "Closes" an epic (see CONTRIBUTING.md, "Issues and epics"). -->
Closes #

## How it was tested

<!-- Tests added, and whether it ran against a real watch account. -->

## Changelog

<!-- One bullet per change users see (a tool or parameter, a file, an environment variable, a default, a behaviour, the layout of the docs); mark an incompatible change **Breaking**. Write None for an internal change (refactor, tests, CI). After opening the PR, `uv run python scripts/changelog.py sync` turns this block into the CHANGELOG.md section. -->
-

## Checklist

- [ ] `uv run pre-commit run --all-files` passes (ruff, format, mypy, personal-data audit)
- [ ] `uv run pytest` passes, with tests for the change
- [ ] `CHANGELOG.md` section generated from the `## Changelog` block (`uv run python scripts/changelog.py sync`), or the block says `None`
- [ ] No personal data (names, races, dates, paces, health data, credentials) — see CONTRIBUTING.md
- [ ] Vendor-specific code stays in `src/open_coach/providers/` (see AGENTS.md "Watch providers")
- [ ] I will sign the [CLA](../CLA.md) when the bot asks (first contribution only)
