# CLAUDE.md

@AGENTS.md

## Claude Code specifics

Everything above (`AGENTS.md`) applies to every agent. Claude Code adds:

- **Skills**: `.claude/skills/*` load natively (`entraineur` + the six workflows + `extract-transcript`). Other clients reach the same text through MCP prompts, `coach://guide/{name}` and `get_coaching_guide` — edit the `SKILL.md` files, never a copy.
- **Hooks** (`.claude/settings.json`, PostToolUse on `Edit|Write`): `journal_reminder_on_plan_edit.py` (journal entry after a plan/profile edit) and `skill_sync_on_code_edit.py` (update `entraineur` when coaching code changes). They only run under Claude Code; for other clients the journal reminder travels in the tools' `next_steps`.
- **Project MCP config**: `.mcp.json` (approve the project server when prompted).
