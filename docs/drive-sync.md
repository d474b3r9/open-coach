# Google Drive plan sync (optional)

A `rclone`-based sync that turns a Google Drive folder into the source of truth for your training plan markdown, while keeping the project's `plans/` directory and your local Obsidian vault aligned.

```
                  ┌─────────────────────────┐
                  │  Google Drive folder    │  ← source of truth
                  └─────────────────────────┘
                       ▲                │
              bidi     │                │  read-only
       (newer wins)    │                ▼
                  ┌─────────┐      ┌──────────┐
                  │ <repo>/ │      │ Obsidian │
                  │ plans/  │      │ vault    │
                  └─────────┘      └──────────┘
```

- `<repo>/plans/` ↔ Drive: bidirectional (`rclone bisync`, last mtime wins).
- Drive → Obsidian: one-way pull (`rclone sync`). **Local Obsidian edits are wiped on each pull** — by design. Edit through the Drive web UI or through the project, never directly in Obsidian.
- No Python/OAuth code in the project. `rclone` handles auth and tokens.

---

## 1. Install rclone

The script requires **rclone 1.66 or later** (Jan 2024) for the bisync flags `--conflict-resolve`, `--conflict-loser`, `--resilient`, `--resync-mode`. Older versions will fail with `unknown flag` errors.

### Linux / macOS — official install script (recommended)

```bash
curl https://rclone.org/install.sh | sudo bash
```

> **Why not `apt install rclone`?** Ubuntu 24.04 LTS still ships rclone 1.60 (Oct 2022), which is too old. The official script always pulls the latest stable release.

### Windows

**Option A — Chocolatey** (recommended if you already use it):

```powershell
choco install rclone
```

**Option B — Scoop**:

```powershell
scoop install rclone
```

**Option C — Manual**:

1. Download the latest `rclone-*-windows-amd64.zip` from https://rclone.org/downloads/
2. Extract somewhere stable, e.g. `C:\Program Files\rclone\`
3. Add that folder to your `PATH` (System Properties → Environment Variables → Path → Edit → New)
4. Open a new PowerShell and verify: `rclone version`

### macOS — Homebrew

```bash
brew install rclone
```

### Verify

```bash
rclone version
# Must print v1.66.x or newer.
```

## 2. Configure the Google Drive remote

This is interactive — `rclone config` prompts you through OAuth. Run it once per machine.

### 2.1. Create your own OAuth client (recommended)

Using your own OAuth client gives you a private rate-limit and removes "unverified app" friction long-term. Skip this section to start fast (use rclone's shared key by pressing Enter on `client_id>` and `client_secret>` in §2.2). You can switch later via `rclone config update gdrive client_id ... client_secret ...`.

1. Go to https://console.cloud.google.com/ (logged in with the Google account that owns the Drive folder).
2. **Create a project**: top-bar project picker → **NEW PROJECT** → name it (e.g. `rclone-perso`) → **CREATE**.
3. **Enable the Drive API**: ☰ → **APIs & Services** → **Library** → search `Google Drive API` → click → **ENABLE**.
4. **OAuth consent screen**: ☰ → **APIs & Services** → **OAuth consent screen**.
   - User Type: **External** → CREATE
   - App name: `rclone-perso`, support + dev email: your email → SAVE AND CONTINUE
   - Scopes: skip → SAVE AND CONTINUE
   - **Test users**: **ADD USERS** → your Google email (lowercase) → ADD → SAVE AND CONTINUE
   - Stay in **Testing** publishing status (do not click "Publish App" — no review needed for personal use).
5. **Create OAuth credentials**: **Credentials** → **+ CREATE CREDENTIALS** → **OAuth client ID**.
   - Application type: **Desktop app**
   - Name: `rclone`
   - CREATE → copy **Client ID** and **Client secret** from the popup.

### 2.2. Run `rclone config`

```text
$ rclone config
n/s/q> n
name> gdrive                    # default expected by the script. Override via OPEN_COACH_DRIVE_REMOTE
Storage> drive                        # or pick the number for "Google Drive"
client_id> <paste your Client ID>     # leave empty to use rclone's shared key (rate-limited)
client_secret> <paste your Client secret>
scope> 1                              # full access
service_account_file>                 # (Enter — leave empty)
Edit advanced config? y/n> n          # ⚠️ N — never Y here
Use auto config? y/n> y               # opens browser for OAuth
```

Browser flow:
- Sign in with the Google account that owns the Drive folder.
- Google warns "Google hasn't verified this app" → **Advanced** → **Go to rclone-perso (unsafe)** (it's your own app — fine).
- Approve the Drive permission → "Success! All done."

Back in the terminal:

```text
Configure this as a Shared Drive (Team Drive)? y/n> n   # n unless you actually use Workspace Team Drives
y/e/d> y                                                 # confirm
e/n/d/r/c/s/q> q                                         # quit
```

### 2.3. Verify

```bash
rclone lsd gdrive:
```

You should see your Drive root folders.

## 3. Find the plan folder ID

Open the target folder in your browser. The URL is:

```
https://drive.google.com/drive/folders/<FOLDER_ID>?usp=...
```

Copy the `<FOLDER_ID>` segment.

## 4. Scope the remote to the plan folder (required)

The script intentionally relies on the remote's configured `root_folder_id` (NOT a CLI flag) to keep `bisync` path identifiers consistent across runs. Set it once:

```bash
rclone config update gdrive root_folder_id <FOLDER_ID>
```

Verify:

```bash
rclone lsd gdrive:
# Lists ONLY the contents of the plan folder, not your full Drive root.
```

> If you skip this, the script refuses to run with an explicit error and the same fix command. **Do not also pass `--drive-root-folder-id` on the CLI** — it generates a different path identifier than the configured `root_folder_id`, which invalidates bisync state and triggers "cannot find prior listings" errors.

## 5. Set environment variables

Set these on **each machine** with the appropriate local paths.

### Linux / macOS — `~/.bashrc` or `~/.zshrc`

```bash
export OPEN_COACH_DRIVE_FOLDER_ID="<your-folder-id>"
export OPEN_COACH_REPO_PLANS_DIR="$HOME/path/to/open-coach/plans"
export OPEN_COACH_OBSIDIAN_PLANS_DIR="$HOME/path/to/your/obsidian/plans/folder"
# Optional — only if your rclone remote is not "gdrive":
# export OPEN_COACH_DRIVE_REMOTE="my-other-name"
# Optional — mass-delete guards (see §10 for the two different semantics):
# export OPEN_COACH_BISYNC_MAX_DELETE_PCT=50   # bisync: PERCENTAGE of files (default 50)
# export OPEN_COACH_OBSIDIAN_MAX_DELETE=20     # obsidian pull: COUNT of files (default 20)
```

Reload: `source ~/.bashrc`.

### Windows — PowerShell (User scope)

```powershell
setx OPEN_COACH_DRIVE_FOLDER_ID "<your-folder-id>"
setx OPEN_COACH_REPO_PLANS_DIR "C:\Users\you\path\to\open-coach\plans"
setx OPEN_COACH_OBSIDIAN_PLANS_DIR "C:\Users\you\path\to\obsidian\plans\folder"
```

> `setx` writes at User scope but is not visible in the current shell — open a new terminal afterwards.

## 6. Create the access sentinel (`RCLONE_TEST`)

The bisync mode uses `--check-access`, which requires a small sentinel file `RCLONE_TEST` in **both** ends. This is rclone's safety check — if either side appears wiped (sentinel missing), bisync refuses to run, preventing mass-delete propagation.

```bash
# Create the sentinel locally
touch "$OPEN_COACH_REPO_PLANS_DIR/RCLONE_TEST"

# And in the Drive folder
rclone touch "gdrive:RCLONE_TEST"
```

## 7. Onboarding sequence (one time)

Run these once, in order, after configuring rclone and setting env vars:

```bash
# 1. Seed Drive with the current content of your Obsidian vault.
#    This is a one-way copy — Obsidian -> Drive, no deletes.
bash scripts/drive_sync.sh --init-obsidian

# 2. Baseline the bisync state for the project.
bash scripts/drive_sync.sh --init-project

# 3. Dry-run the steady state to confirm everything looks sane.
bash scripts/drive_sync.sh --all --dry-run
```

After this, Drive holds the canonical content, the project is bisynced, and Obsidian is ready to be pulled read-only.

## 8. Daily usage

```bash
# Bidirectional project sync only:
bash scripts/drive_sync.sh --project

# Refresh Obsidian from Drive only:
bash scripts/drive_sync.sh --obsidian

# Both, in the right order (project first, then Obsidian):
bash scripts/drive_sync.sh --all

# Dry-run anything:
bash scripts/drive_sync.sh --all --dry-run
```

## 9. Optional: schedule it

The script does not auto-schedule itself. Pick whichever fits.

### Linux — systemd user timer

`~/.config/systemd/user/garmin-plan-sync.service`:

```ini
[Unit]
Description=Sync running plans with Google Drive
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=%h/.config/garmin-plan-sync.env
ExecStart=/usr/bin/bash %h/path/to/open-coach/scripts/drive_sync.sh --all
```

`~/.config/systemd/user/garmin-plan-sync.timer`:

```ini
[Unit]
Description=Run garmin-plan-sync every 30 min

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

Put your env vars in `~/.config/garmin-plan-sync.env` (no `export` keyword), then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now garmin-plan-sync.timer
journalctl --user -u garmin-plan-sync.service -n 50  # check last run
```

### Windows — Task Scheduler

Create a basic task:
- Trigger: every 30 minutes
- Action: `bash.exe -c "/c/Users/you/path/scripts/drive_sync.sh --all"` (Git Bash) or use WSL
- Make sure the User-scope env vars are visible to the task account.

## 10. Conflicts and recovery

### Bisync conflicts (project ↔ Drive)

If the same file changes on both sides between two sync runs, `--conflict-resolve newer` keeps the newer mtime and preserves the loser as `<file>.conflict-YYYYMMDD-HHMMSS`. Review and remove the `.conflict-*` file once you've merged any useful content from it.

### Obsidian sync deletions / overwrites

Each `--obsidian` run uses `--backup-dir`: any file that would have been overwritten or deleted is moved to:

```
<dirname-of-obsidian-dir>/<basename>.rclone-backup/<YYYYMMDD-HHMMSS>/
```

Example: if `OPEN_COACH_OBSIDIAN_PLANS_DIR=$HOME/path/to/obsidian/plans/folder`, backups land in `$HOME/path/to/obsidian/plans/folder.rclone-backup/<timestamp>/`. Recovery is just a copy back. The script does **not** auto-prune backups — clean up manually when comfortable.

### Mass-delete refusal

The script passes `--max-delete` to rclone in both modes, but **the flag has different semantics for the two commands**:

| Mode | rclone command | `--max-delete` meaning | Default | Override env var |
|---|---|---|---|---|
| `--project` / `--init-project` | `rclone bisync` | **percentage** of files on one side that may be deleted in a pass | `50` | `OPEN_COACH_BISYNC_MAX_DELETE_PCT` |
| `--obsidian` | `rclone sync` | absolute **count** of files that may be deleted in a pass | `20` | `OPEN_COACH_OBSIDIAN_MAX_DELETE` |

For bisync, `--check-access` (the `RCLONE_TEST` sentinel) is the primary guard against a wiped side; the percentage threshold is a second line of defence. For the Obsidian pull, every deleted or overwritten file is moved to `--backup-dir` anyway, so the count limit only guards against a surprising mass change — nothing is lost outright.

If rclone refuses a run you intended (e.g. you deliberately cleared most of a folder), run with `--dry-run` first to inspect, then raise the relevant env var temporarily for one run and put it back:

```bash
OPEN_COACH_OBSIDIAN_MAX_DELETE=200 bash scripts/drive_sync.sh --obsidian
```

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Error 403: access_denied` (Google) during OAuth | Your email isn't a Test user on the OAuth consent screen | GCP Console → OAuth consent screen → Test users → ADD USERS → your email (lowercase) |
| `Error 403: SERVICE_DISABLED — Google Drive API has not been used` | Drive API not enabled on the GCP project | Click the activation URL in the error, ENABLE, wait 30s, retry |
| `oauth2: cannot fetch token: 404 Not Found` | Bad `token_url` saved in advanced config | `rclone config delete gdrive` and redo §2.2, answering **n** to "Edit advanced config" |
| `unknown flag: --resilient` (or `--conflict-resolve`, `--resync-mode`) | rclone < 1.66 | Upgrade via the official script (§1). The script requires 1.66+ |
| `Bisync aborted: --check-access failed` | `RCLONE_TEST` missing on one end | Create the sentinels (§6) |
| `cannot find prior Path1 or Path2 listings` | First run, no baseline; OR path identifier changed since last run | Re-baseline: `bash scripts/drive_sync.sh --init-project`. Avoid mixing `--drive-root-folder-id` flag with `root_folder_id` config |
| `Drive folder ID looks empty` in `rclone ls` | `root_folder_id` not set, or `--drive-root-folder-id` was passed empty (the `VAR=val cmd "$VAR"` bash pattern silently expands `$VAR` to empty) | Inspect with `rclone config show gdrive`; re-apply §4 |
| `oauth2: token expired` | OAuth grant revoked or token cache stale | `rclone config reconnect gdrive:` |
| `--obsidian` shows tons of files in `.rclone-backup/` you didn't expect | Drive had different content than Obsidian when sync ran | Inspect, copy back if needed; re-run after merging |
| Browser doesn't open during OAuth | Headless / `xdg-open` not configured | Copy the URL printed by rclone (`http://127.0.0.1:53682/auth?state=...`) into a browser manually; or answer `n` to "Use auto config" and follow the manual flow |

## 12. Security notes

- `rclone config show <remote>` prints `client_secret`, `access_token`, and `refresh_token` in clear text. **Never paste this output in chats, screenshots, or issues.** If you do, revoke at https://myaccount.google.com/permissions and `rclone config reconnect <remote>:`.
- The `client_secret` of a Desktop OAuth client is not actually treated as sensitive by Google's threat model (it's hardcoded in distributed apps). Still, regenerate it (GCP Console → Credentials → ✏️ → RESET SECRET) if it leaks.
- The `refresh_token` IS sensitive — it grants persistent access until revoked.
- For shared environments, prefer a Service Account with a JSON key (set `service_account_file` in `rclone config`), and share the target Drive folder with the SA's email. Out of scope here for a personal setup.
