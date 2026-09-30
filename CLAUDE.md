# CLAUDE.md

@AGENTS.md

## Claude Code specifics

Everything above (`AGENTS.md`) applies to every agent. Claude Code adds:

- **Skills**: `.claude/skills` is a symlink to `.agents/skills/` (the cross-client location, [Agent Skills standard](https://agentskills.io)); Claude Code loads them natively through it. Edit the files under `.agents/skills/`. On Windows the symlink needs `git config core.symlinks true` and Developer Mode, otherwise Claude Code sees no skills.
- **Hooks** (`.claude/settings.json`, PostToolUse on `Edit|Write`): `journal_reminder_on_plan_edit.py` (journal entry after a plan/profile edit) and `skill_sync_on_code_edit.py` (update `coaching-rules` when coaching code changes). They only run under Claude Code; for other clients the journal reminder travels in the tools' `next_steps`.
- **Project MCP config**: `.mcp.json` (approve the project server when prompted).
