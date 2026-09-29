#!/usr/bin/env bash
# Sync running plan markdown between three endpoints:
#   - Google Drive folder (source of truth)
#   - <repo>/plans/        (read-write, bidirectional via rclone bisync)
#   - Obsidian local vault (read-only pull via rclone sync)
#
# All personal values come from environment variables. Nothing personal is
# committed in this script. See docs/drive-sync.md for setup.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [MODE] [--dry-run]

Modes (mutually exclusive):
  --project          Bidirectional sync <repo>/plans/ <-> Drive (default).
  --obsidian         One-way pull Drive -> Obsidian local (overwrites local).
  --all              Run --project then --obsidian.
  --init-project     One-time bisync baseline (rclone bisync --resync).
                     Required once per machine before first --project run.
  --init-obsidian    One-time seed Drive with current Obsidian content
                     (rclone copy --update). Run once during onboarding,
                     before switching Obsidian to read-only mode.

Options:
  --dry-run          Pass through to rclone (no changes).
  -h, --help         Show this help.

Required environment variables:
  OPEN_COACH_DRIVE_FOLDER_ID      Google Drive folder ID
  OPEN_COACH_REPO_PLANS_DIR       Absolute path to <repo>/plans/
  OPEN_COACH_OBSIDIAN_PLANS_DIR   Absolute path to local Obsidian plan dir

Optional environment variables:
  OPEN_COACH_DRIVE_REMOTE         rclone remote name (default: gdrive).
                                    Set this only if your rclone remote is named
                                    differently or you have multiple remotes.
  OPEN_COACH_BISYNC_MAX_DELETE_PCT
                                    bisync --max-delete threshold, a PERCENTAGE
                                    of files on one side (default: 50). bisync
                                    aborts if a single pass would delete more.
  OPEN_COACH_OBSIDIAN_MAX_DELETE  obsidian pull --max-delete threshold, a COUNT
                                    of files (default: 20). Deletes are moved to
                                    --backup-dir anyway, never removed outright.

Safety:
  - bisync uses --check-access (RCLONE_TEST sentinel must exist on both ends),
    --max-delete <percent> (rclone bisync semantics: % of files, not a count),
    --conflict-resolve newer.
  - obsidian sync uses --max-delete <count> (rclone sync semantics: number of
    files) and --backup-dir (timestamped sibling folder; nothing is deleted
    outright).
EOF
}

# Legacy GARMIN_COACH_* names (before the open_coach rename) are still read.
legacy_name() { printf '%s' "GARMIN_COACH_${1#OPEN_COACH_}"; }

# env_or <OPEN_COACH_NAME> <default>: value of the var, else its legacy name, else default.
env_or() {
  local name="$1" legacy
  legacy=$(legacy_name "$name")
  printf '%s' "${!name:-${!legacy:-$2}}"
}

require_env() {
  local name="$1"
  local val
  val=$(env_or "$name" "")
  if [[ -z "$val" ]]; then
    echo "ERROR: required env var $name is not set." >&2
    echo "       See docs/drive-sync.md for setup." >&2
    exit 1
  fi
  printf '%s' "$val"
}

require_rclone() {
  if ! command -v rclone >/dev/null 2>&1; then
    echo "ERROR: rclone is not installed or not in PATH." >&2
    echo "       Install via: apt install rclone | brew install rclone | choco install rclone" >&2
    exit 1
  fi
}

require_dir() {
  local label="$1"
  local path="$2"
  if [[ ! -d "$path" ]]; then
    echo "ERROR: $label does not exist or is not a directory: $path" >&2
    exit 1
  fi
}

MODE=""
DRY_RUN=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project|--obsidian|--all|--init-project|--init-obsidian)
      if [[ -n "$MODE" ]]; then
        echo "ERROR: only one mode flag allowed (got --$MODE and $1)." >&2
        exit 2
      fi
      MODE="${1#--}"
      ;;
    --dry-run)
      DRY_RUN=(--dry-run)
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

MODE="${MODE:-project}"

require_rclone
REMOTE="$(env_or OPEN_COACH_DRIVE_REMOTE "gdrive")"
FOLDER_ID=$(require_env OPEN_COACH_DRIVE_FOLDER_ID)

REMOTE_SPEC="${REMOTE}:"

# Verify the configured remote is scoped to the expected folder. Bisync needs a
# consistent path identifier across runs, and passing --drive-root-folder-id on
# CLI generates a different identifier than relying on the config — so we rely
# strictly on the remote's configured root_folder_id and validate it here.
configured_id=$(rclone config show "$REMOTE" 2>/dev/null | awk -F'= ' '/^root_folder_id/ {print $2; exit}')
if [[ "$configured_id" != "$FOLDER_ID" ]]; then
  echo "ERROR: rclone remote '$REMOTE' has root_folder_id='${configured_id:-<unset>}'." >&2
  echo "       Expected '$FOLDER_ID' (from OPEN_COACH_DRIVE_FOLDER_ID)." >&2
  echo "       Fix with: rclone config update $REMOTE root_folder_id $FOLDER_ID" >&2
  exit 1
fi

# Exclude project-local artifacts from sync. `.templates/` is versioned skeletons
# used by scripts/setup_local.py; they have no business being on Drive.
EXCLUDES=(--exclude '.templates/**')

# rclone bisync --max-delete is a PERCENTAGE of files on one side;
# rclone sync --max-delete is an absolute COUNT of files. Different semantics.
BISYNC_MAX_DELETE_PCT="$(env_or OPEN_COACH_BISYNC_MAX_DELETE_PCT "50")"
OBSIDIAN_MAX_DELETE="$(env_or OPEN_COACH_OBSIDIAN_MAX_DELETE "20")"

resolve_repo_dir() {
  REPO_DIR=$(require_env OPEN_COACH_REPO_PLANS_DIR)
  require_dir "OPEN_COACH_REPO_PLANS_DIR" "$REPO_DIR"
}

resolve_obsidian_dir() {
  OBSIDIAN_DIR=$(require_env OPEN_COACH_OBSIDIAN_PLANS_DIR)
  require_dir "OPEN_COACH_OBSIDIAN_PLANS_DIR" "$OBSIDIAN_DIR"
}

run_bisync() {
  resolve_repo_dir
  rclone bisync "$REPO_DIR" "$REMOTE_SPEC" \
    "${EXCLUDES[@]}" \
    --check-access \
    --max-delete "$BISYNC_MAX_DELETE_PCT" \
    --conflict-resolve newer \
    --conflict-loser pathname \
    --resilient \
    -v \
    "${DRY_RUN[@]}"
}

run_init_project() {
  resolve_repo_dir
  echo "Baselining bisync state (rclone bisync --resync --resync-mode newer)." >&2
  echo "Per-file the newer mtime wins; one-sided files are copied to the other side, never deleted." >&2
  rclone bisync --resync --resync-mode newer "$REPO_DIR" "$REMOTE_SPEC" \
    "${EXCLUDES[@]}" \
    --max-delete "$BISYNC_MAX_DELETE_PCT" \
    --resilient \
    -v \
    "${DRY_RUN[@]}"
}

run_obsidian_pull() {
  resolve_obsidian_dir
  local backup_parent backup_dir
  backup_parent="$(dirname "$OBSIDIAN_DIR")/$(basename "$OBSIDIAN_DIR").rclone-backup"
  backup_dir="$backup_parent/$(date +%Y%m%d-%H%M%S)"
  rclone sync "$REMOTE_SPEC" "$OBSIDIAN_DIR" \
    "${EXCLUDES[@]}" \
    --max-delete "$OBSIDIAN_MAX_DELETE" \
    --backup-dir "$backup_dir" \
    -v \
    "${DRY_RUN[@]}"
}

run_init_obsidian() {
  resolve_obsidian_dir
  echo "Seeding Drive with current Obsidian content (rclone copy --update)." >&2
  echo "This is a one-time onboarding step before switching Obsidian to read-only." >&2
  rclone copy "$OBSIDIAN_DIR" "$REMOTE_SPEC" \
    "${EXCLUDES[@]}" \
    --update \
    -v \
    "${DRY_RUN[@]}"
}

case "$MODE" in
  project)        run_bisync ;;
  obsidian)       run_obsidian_pull ;;
  all)            run_bisync; run_obsidian_pull ;;
  init-project)   run_init_project ;;
  init-obsidian)  run_init_obsidian ;;
  *)
    echo "ERROR: unhandled mode: $MODE" >&2
    exit 2
    ;;
esac
