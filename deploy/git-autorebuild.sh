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
git pull --ff-only origin main

source .venv/bin/activate
pip install -q -r requirements.txt
deactivate

sudo systemctl restart wallcalendar.service
echo "Restarted wallcalendar.service."
