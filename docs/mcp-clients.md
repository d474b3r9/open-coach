# Using Open Coach from any MCP client

Open Coach is a standard **stdio MCP server**. Claude Code is the reference client, but the coaching rules and workflows travel with the server itself, so any MCP client with tool calling can run the coach.

## What every client gets

| Layer | How it reaches the model | Needs |
|---|---|---|
| Operating rules (read context first, methodology, watch sync, activity analysis, safety) | MCP server **instructions**, sent at connection | nothing |
| Athlete context, active plan, archived plans | Tools `get_coaching_context`, `get_active_plan`, `get_archived_plan` (also as `coach://` resources) | tool calling |
| Coaching methodology and workflows | Tool `get_coaching_guide(name)`, MCP **prompts** `onboard`, `plan-training`, `push-workout`, `analyze-run`, `daily-check`, `race-ready`, resource `coach://guide/{name}` | tool calling (prompts / resources are a bonus) |
| Follow-up actions (watch sync, training journal, Drive sync) | `next_steps` field in the results of plan-changing tools | tool calling |
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

## Tips for smaller models

- Start the conversation with the matching prompt (`/plan-training`, `/daily-check`…) when the client supports prompts; otherwise ask the model to call `get_coaching_guide` with the workflow name.
- Ask it to follow the `next_steps` returned after a plan change.
- If a model struggles with the full training plan schema, prefer `generate_training_plan` (server-side) over hand-writing a plan for `save_training_plan`.
