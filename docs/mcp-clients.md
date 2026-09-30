# Using Open Coach from any MCP client

Open Coach is a standard **stdio MCP server**. Claude Code is the reference client, but the coaching rules and workflows travel with the server itself, so any MCP client with tool calling can run the coach.

## What every client gets

| Layer | How it reaches the model | Needs |
|---|---|---|
| Operating rules (read context first, methodology, watch sync, activity analysis, safety) | MCP server **instructions**, sent at connection | nothing |
| Athlete context, active plan, archived plans | Tools `get_coaching_context`, `get_active_plan`, `get_archived_plan` (also as `coach://` resources) | tool calling |
| Coaching methodology and workflows | Tool `get_coaching_guide(name)`, MCP **prompts** `onboard`, `plan-training`, `push-workout`, `analyze-run`, `daily-check`, `race-ready`, resources `skill://<name>/SKILL.md` (MCP Skills extension URIs); the catalog sits in the server instructions and in the tool description | tool calling (prompts / resources are a bonus) |
| Follow-up actions (watch sync, training journal, Drive sync) | `next_steps` field in the results of plan-changing tools | tool calling |
| Skills as native skills (repo open in the client) | `.agents/skills/` ([Agent Skills](https://agentskills.io) standard): Codex, Gemini CLI, Cursor, Copilot; Claude Code via the `.claude/skills` symlink | file access |
| Repo conventions for coding agents | `AGENTS.md` (read natively by Codex, Cursor, GitHub Copilot; Gemini CLI via `.gemini/settings.json`; Claude Code via `CLAUDE.md` → `@AGENTS.md`) | file access |

Clients that do not read resources or prompts lose nothing: the tools return the same content. Clients without file access (desktop and web chats) skip the markdown athlete profile and journal in `plans/` and work from `get_coaching_context`.

## Server command

Every config below launches the same command (stdio):

```bash
uv run --directory /absolute/path/to/open-coach open-coach
```

`open-coach` is the console script declared in `pyproject.toml` (equivalent: `uv run python -m open_coach`). Run `uv sync` once in the repo first.

Credentials: `GARMIN_EMAIL` / `GARMIN_PASSWORD` are only needed for the first Garmin login (the token cache in `~/.garth/` is reused afterwards); `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` are optional. Pass them through the client's `env` block or export them in the shell that starts the client.

## Project configs shipped in the repo

Open the repository as your workspace and these are picked up automatically:

| Client | File | Notes |
|---|---|---|
| Claude Code | `.mcp.json` | Approve the project server when prompted. Skills and hooks load natively. |
| Cursor | `.cursor/mcp.json` | Uses `${workspaceFolder}` and `${env:…}`. Enable the server in Settings → MCP. |
| Gemini CLI | `.gemini/settings.json` | Also sets `AGENTS.md` as the context file. Start `gemini` from the repo root. Prompts show up as slash commands. |

## Other clients

### OpenAI Codex (CLI / IDE)

`~/.codex/config.toml`:

```toml
[mcp_servers.open-coach]
command = "uv"
args = ["run", "--directory", "/absolute/path/to/open-coach", "open-coach"]
# Codex does not forward your whole environment to MCP servers:
env_vars = ["GARMIN_EMAIL", "GARMIN_PASSWORD", "STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET"]
```

If your Codex version does not know `env_vars`, use an `env = { GARMIN_EMAIL = "…" }` table instead. Codex reads `AGENTS.md` from the repo on its own.

### VS Code (GitHub Copilot agent mode)

`.vscode/mcp.json` (the folder is gitignored in this repo, so create it locally):

```json
{
  "servers": {
    "open-coach": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "${workspaceFolder}", "open-coach"],
      "env": {
        "GARMIN_EMAIL": "${env:GARMIN_EMAIL}",
        "GARMIN_PASSWORD": "${env:GARMIN_PASSWORD}"
      }
    }
  }
}
```

### Claude Desktop, and other desktop / chat clients

Clients launched outside the repo need absolute paths — including the path to `uv` itself when the client does not inherit your shell `PATH` (`which uv`):

```json
{
  "mcpServers": {
    "open-coach": {
      "command": "/absolute/path/to/uv",
      "args": ["run", "--directory", "/absolute/path/to/open-coach", "open-coach"]
    }
  }
}
```

### Local models (Ollama, LM Studio…) through an MCP-capable front end

Any front end that speaks MCP over stdio works with the command above. Pick a model with reliable tool calling; the server keeps its payloads small (`compact=True` by default on the raw watch payloads) and publishes full JSON schemas for structured inputs (training plan, workout), so the model never has to guess a structure.

## Checking the connection

Ask the model: *"What is today's date according to the coach?"* It should call `get_coaching_context` (or read `coach://context`). If it answers without a tool call, the server is not connected: run `uv run open-coach` in a terminal to see startup errors, and `uv run python scripts/smoke_mcp.py` for an end-to-end check.

## Skills: standards followed and known limits

The coaching guides are **Agent Skills** and the server exposes them following the skills-over-MCP patterns of 2026:

| Standard | What it covers here |
|---|---|
| [Agent Skills specification](https://agentskills.io/specification) (open standard, adopted by Codex, Gemini CLI, Copilot, Cursor, Claude Code and others) | `SKILL.md` frontmatter (`name`, `description`, `compatibility`, `metadata`), body under 500 lines, references one level deep. Checked by `tests/test_skills_spec.py`. |
| [`.agents/skills/` convention](https://agentskills.io/client-implementation/adding-skills-support) | Cross-client location of the skills; `.claude/skills` is a symlink to it for Claude Code. |
| [MCP Skills extension (SEP-2640)](https://modelcontextprotocol.io/extensions/skills/overview) | Skills served as `skill://<name>/SKILL.md` resources (plus `_manifest` and supporting files), through FastMCP's `SkillProvider`. |
| Catalog in an always-loaded tool description ([skills-mcp](https://github.com/StacklokLabs/skills-mcp)) and in the system prompt ([Agent Skills client guide](https://agentskills.io/client-implementation/adding-skills-support)) | The guide catalog (name + what/when) sits in the `get_coaching_guide` description and in the server instructions. |
| [Anthropic skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | Third-person descriptions with trigger phrases, `## Contents` on long references, copyable checklists, client-neutral wording. |

Known limits:

- **Windows and the `.claude/skills` symlink.** Git checks symlinks out as plain text files unless `core.symlinks` is enabled, and creating them needs Developer Mode (or an elevated shell). Without it, Claude Code sees no skills; the other clients are unaffected (they read `.agents/skills/` or go through the MCP server). Fix before cloning, or re-checkout after enabling it:

  ```powershell
  git config --global core.symlinks true   # with Windows Developer Mode on
  git clone https://github.com/d474b3r9/open-coach.git
  ```

- **`skills/list` and `skills/get` are not implemented.** SEP-2640 also defines these JSON-RPC methods (discovery with file digests). FastMCP does not provide them yet and very few clients call them ([client matrix](https://modelcontextprotocol.io/extensions/client-matrix)); the `skill://` resources, prompts and `get_coaching_guide` cover the same need meanwhile. To be added once FastMCP supports them.
- **Loading a guide is never guaranteed.** No client forces a model to load a skill: the model decides from the catalog. The catalog in the instructions and in the tool description makes it much more likely, but a weaker model can still skip it. When it matters, start with the workflow prompt (`/plan-training`…) or ask for `get_coaching_guide` explicitly — and when changing a skill, try it on a few representative requests with the models you actually use, as the best practices recommend.

## Tips for smaller models

- Start the conversation with the matching prompt (`/plan-training`, `/daily-check`…) when the client supports prompts; otherwise ask the model to call `get_coaching_guide` with the workflow name.
- Ask it to follow the `next_steps` returned after a plan change.
- If a model struggles with the full training plan schema, prefer `generate_training_plan` (server-side) over hand-writing a plan for `save_training_plan`.
