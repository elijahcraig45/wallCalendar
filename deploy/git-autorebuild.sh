#!/usr/bin/env bash
# Run periodically by wallcalendar-autorebuild.timer, as the normal desktop
# user (not root) so pulled files/venv stay user-owned. Only the final
# restart needs root, via a sudoers rule scoped to exactly that command
# (see setup-pi.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin main --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "wallCalendar is up to date ($LOCAL)."
  exit 0
fi

echo "New commits found ($LOCAL -> $REMOTE) - pulling and rebuilding."

# A dirty working tree makes `git pull --ff-only` abort, and this runs unattended
# every 10 minutes - so without this the wall silently stops updating forever
# after anyone edits a file on the Pi to debug something (which is exactly what
# happens on an appliance you can SSH into). Stash rather than hard-reset: the
# edit is preserved and recoverable with `git stash list`, and updates resume.
if ! git diff --quiet || ! git diff --cached --quiet; then
  STAMP="autorebuild-$(date +%Y%m%d-%H%M%S)"
  echo "Working tree is dirty; stashing local changes as '$STAMP' so the update can proceed."
  git stash push --include-untracked -m "$STAMP" || {
    echo "Could not stash local changes - refusing to touch them. Fix by hand:" >&2
    git status --short >&2
    exit 1
  }
  echo "Recover them later with: git stash list / git stash show -p stash@{0}"
fi

git pull --ff-only origin main

source .venv/bin/activate
pip install -q -r requirements.txt
deactivate

sudo systemctl restart wallcalendar.service
echo "Restarted wallcalendar.service."
