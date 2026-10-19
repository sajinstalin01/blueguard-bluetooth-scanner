#!/usr/bin/env bash
set -Eeuo pipefail

# BlueGuard Bluetooth Scanner updater
# Run from a Git clone: bash update.sh

REPO_URL="https://github.com/sajinstalin01/blueguard-bluetooth-scanner.git"
BRANCH="main"

say() { printf '\n[BlueGuard Updater] %s\n' "$*"; }
fail() { printf '\n[BlueGuard Updater] ERROR: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "Git is not installed. Install it with: sudo apt install git"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  fail "This folder is not a Git clone. Clone the repository first: git clone $REPO_URL"

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] ||
  fail "You are on branch '$CURRENT_BRANCH', not '$BRANCH'. Switch to main before updating."

ORIGIN_URL="$(git remote get-url origin 2>/dev/null || true)"
[[ -n "$ORIGIN_URL" ]] || fail "No 'origin' remote is configured."
case "$ORIGIN_URL" in
  "$REPO_URL"|https://github.com/sajinstalin01/blueguard-bluetooth-scanner|git@github.com:sajinstalin01/blueguard-bluetooth-scanner.git|ssh://git@github.com/sajinstalin01/blueguard-bluetooth-scanner.git) ;;
  *) fail "The origin remote is '$ORIGIN_URL', which is not the expected BlueGuard repository. No changes were made." ;;
esac

if [[ -n "$(git status --porcelain)" ]]; then
  fail "Local changes or untracked files were found. Commit or back them up before updating; nothing was overwritten."
fi

say "Fetching latest commits from origin/$BRANCH..."
git fetch --prune origin "$BRANCH"

REMOTE_REF="origin/$BRANCH"
git rev-parse --verify "$REMOTE_REF" >/dev/null 2>&1 ||
  fail "Could not find $REMOTE_REF after fetching."

if git diff --quiet HEAD "$REMOTE_REF" && git diff --cached --quiet HEAD "$REMOTE_REF"; then
  if [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$REMOTE_REF")" ]]; then
    say "Already up to date."
    exit 0
  fi
fi

if ! git merge-base --is-ancestor HEAD "$REMOTE_REF"; then
  fail "Local and remote histories have diverged or local commits exist. Review with 'git log --oneline --graph --decorate --all' before updating."
fi

say "Updating to the latest $BRANCH commit..."
git merge --ff-only "$REMOTE_REF"

say "Running Python syntax check..."
if [[ -f "./check.sh" ]]; then
  bash ./check.sh
else
  python3 -m py_compile blueguard.py
fi

say "Update complete."
say "Restart BlueGuard to use the updated version: bash ./run.sh"
