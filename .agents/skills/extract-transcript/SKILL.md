---
name: extract-transcript
description: Extracts YouTube video transcripts into plans/references/ as markdown so the entraineur methodology can cite external coaching methods. Use when the user pastes one or more YouTube URLs to import, summarize or apply a method ("extract", "transcript", "apply this method", "what do you think", "méthode", "vidéo", "qu'en penses-tu", "applique cette méthode"), or invokes /extract-transcript.
compatibility: Requires a shell, uv and network access.
metadata:
  version: "1.2.0"
---

# Skill `extract-transcript` — Import YouTube video transcripts

## 1. When to use this skill

Trigger for:
- The athlete pastes 1+ YouTube URLs and asks to extract their content
- The athlete mentions a video/method and wants to compare it with the active plan (and provides the URL)
- Explicit invocation `/extract-transcript <url1> [<url2> ...]`

Do **NOT** trigger for:
- A simple question about a video's content (no URL provided)
- A YouTube share with no coaching intent (music, film, entertainment)
- A reference to a video title without a URL — ask for the URL first

## 2. Workflow

### Step 1 — Extraction (Python script)

Run the script:

```bash
# bash / zsh
uv run python .agents/skills/extract-transcript/scripts/fetch_transcript.py <url1> [<url2> ...]
```

```powershell
# Windows venv
.venv\Scripts\python.exe .claude\skills\extract-transcript\scripts\fetch_transcript.py <url1> [<url2> ...]
```

Options:
- `--lang en|fr` — preferred caption language (default `en`). Pass `--lang fr` when the athlete speaks French or the video is in French.
- `--force` — re-extract (overwrite an existing file).

The script:
- Creates `plans/references/INDEX.md` if missing (categorised skeleton)
- Writes one `{channel-slug}-{title-slug}-{videoId}.md` file per video in `plans/references/`
- Silently skips if already present (unless `--force`)
- Looks for captions in the `--lang` language first, falls back to the other language, then to an auto-translation into `--lang` when available
- Marks `captions_type: auto|manual` in the frontmatter

If the dependency is missing, install it:

```
uv sync --extra transcripts
# or, Windows venv: .venv\Scripts\pip.exe install "youtube-transcript-api>=1.2,<2.0"
```

### Step 2 — Distillation (read by the agent)

For each freshly created transcript:

1. Read the full `.md` file
2. Distil **5 to 8 methodological pillars**:
   - Short, factual, actionable sentences
   - Prefer **principles** over precise figures (auto-transcribed figures are unreliable)
   - If a figure is quoted, add `(to be checked on the video)` when `captions_type: auto`
3. Assess **compatibility with the athlete profile**:
   - Read `plans/athlete-profile.md` and `plans/training-journal.md` if not already done in the session
   - Rate ✅ (compatible) / ⚠️ (compatible with adaptation) / ❌ (incompatible)
   - 1 line of explanation

### Step 3 — Indexing (proposal to validate)

Propose to the athlete the entry to append to `plans/references/INDEX.md`, formatted as:

```markdown
### {Channel} — "{Title}"
- **File**: [{filename}.md]({filename}.md)
- **Pillars**:
  1. ...
  2. ...
- **Compatible with athlete profile**: ✅/⚠️/❌ — {1 line}
- **Indexed**: YYYY-MM-DD
```

Place it in the appropriate section (Marathon / Ultra / Recovery / Nutrition / Strength). If the category does not exist → add one.

**Wait for validation** before writing to INDEX.md (a change potentially read by every future session of the `entraineur` skill).

### Step 4 — Logical follow-up

Once indexed, offer:
- "Do you want me to compare these pillars with the active race plan?" (read the current target race from `plans/athlete-profile.md` § Race calendar)
- If yes → apply the standard `entraineur` workflow (read profile + journal + active plan), produce a diff of proposals, **wait for validation before any plan edit**.

Reply in the athlete's language (English or French) throughout.

## 3. Tradeoffs to flag to the athlete

- **Auto-captions = noise**: no punctuation, jargon mis-transcribed ("VDOT" → "vidot"), figures often imprecise. Good for **principles**, check the video for **figures**.
- **No timestamps** in the markdown: reading stays fluent. To find a specific passage, open the video and search manually.
- **Copyright**: transcripts are stored in `plans/references/`, which is gitignored. Never commit or redistribute them.

## 4. Possible evolutions (TODO, out of scope for v1)

- **`--whisper` mode**: if auto-captions are unavailable or too degraded, download the audio via `yt-dlp` and re-transcribe locally (Whisper, ~1 GB model, +2-5 min/video).
- **URL-watcher hook**: UserPromptSubmit hook that detects a YouTube URL in a coaching context and offers extraction.
- **Vimeo / Spotify podcast support**: other sources of coaching methodologies.

## 5. Dependency

`youtube-transcript-api>=1.2,<2.0` — no API key required, no OAuth, works on Windows.

The `fetch_transcript.py` script prints a clear install instruction if the library is missing.
