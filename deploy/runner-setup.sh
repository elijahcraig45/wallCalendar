#!/usr/bin/env bash
# Registers this Pi as a self-hosted GitHub Actions runner, so pushing to main
# deploys to the wall in seconds instead of waiting up to 10 minutes for the
# polling timer.
#
# The runner only makes outbound connections, so nothing has to be exposed to the
# internet and no ports are forwarded.
#
# SECURITY - read this before running it on a public repository.
#
#   A self-hosted runner executes whatever a workflow tells it to, on this machine,
#   inside your home network. GitHub advises against pairing them with public
#   repos because a pull request from a fork would otherwise run its code here.
#
#   .github/workflows/deploy.yml is therefore triggered by `push` to main only.
#   Push events require write access to the repository, so a fork cannot trigger
#   them. That is the entire protection, and it is sufficient - as long as nobody
#   adds a `pull_request`, `pull_request_target` or `issue_comment` trigger to any
#   workflow in this repo. If that ever happens, remove the runner first.
#
#   Also worth setting once, in the repo's Settings -> Actions -> General:
#   "Require approval for all external contributors".
#
# The polling timer is deliberately left in place as a backstop: if the runner is
# down or unregistered, the wall still catches up within 10 minutes.
#
# Usage (get a token from `gh api -X POST \
#   repos/<owner>/<repo>/actions/runners/registration-token --jq .token`,
# it expires in an hour):
#
#   bash deploy/runner-setup.sh --token <REGISTRATION_TOKEN> [--version 2.336.0]

set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Run this as your normal user, not root - it calls sudo only for the service install." >&2
  exit 1
fi

REPO_URL="https://github.com/elijahcraig45/wallCalendar"
RUNNER_DIR="$HOME/actions-runner"
RUNNER_VERSION="2.336.0"
LABELS="wallcalendar"
TOKEN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --token)   TOKEN="${2:?--token needs a value}"; shift 2 ;;
    --version) RUNNER_VERSION="${2:?--version needs a value}"; shift 2 ;;
    --repo)    REPO_URL="${2:?--repo needs a value}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$TOKEN" ]; then
  echo "A registration token is required. Get one with:" >&2
  echo "  gh api -X POST repos/elijahcraig45/wallCalendar/actions/runners/registration-token --jq .token" >&2
  exit 1
fi

case "$(uname -m)" in
  aarch64|arm64) ARCH="arm64" ;;
  x86_64)        ARCH="x64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
log "1/4 Downloading the runner (linux-$ARCH, v$RUNNER_VERSION)"
# ---------------------------------------------------------------------------
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"
TARBALL="actions-runner-linux-$ARCH-$RUNNER_VERSION.tar.gz"
if [ ! -f "config.sh" ]; then
  curl -fsSL -o "$TARBALL" \
    "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$TARBALL"
  tar xzf "$TARBALL"
  rm -f "$TARBALL"
else
  echo "Runner already extracted here - reusing it."
fi

# ---------------------------------------------------------------------------
log "2/4 Registering with $REPO_URL"
# ---------------------------------------------------------------------------
if [ -f ".runner" ]; then
  echo "Already registered. Remove it first with ./config.sh remove --token <token> to re-register."
else
  # --unattended so it never prompts; --replace so re-running after a reimage
  # takes over the old registration instead of creating a duplicate.
  ./config.sh \
    --url "$REPO_URL" \
    --token "$TOKEN" \
    --name "$(hostname)" \
    --labels "$LABELS" \
    --work "_work" \
    --unattended \
    --replace
fi

# ---------------------------------------------------------------------------
log "3/4 Installing it as a service"
# ---------------------------------------------------------------------------
# svc.sh needs root to write the unit, but runs the runner as the invoking user -
# which matters, because the deploy needs that user's sudoers rule for the one
# systemctl restart, and its clone/venv ownership.
sudo ./svc.sh install "$(whoami)"
sudo ./svc.sh start
sleep 3
sudo ./svc.sh status || true

# ---------------------------------------------------------------------------
log "4/4 Done"
# ---------------------------------------------------------------------------
cat <<EOF

The runner is registered as "$(hostname)" with the label "$LABELS", which is what
.github/workflows/deploy.yml targets.

Pushing to main now deploys within seconds. The polling timer stays enabled as a
backstop for whenever the runner is down.

  Check it:      cd $RUNNER_DIR && sudo ./svc.sh status
  Its logs:      journalctl -u "actions.runner.*" -f
  Deploy logs:   journalctl -u wallcalendar-autorebuild.service -n 40
  Remove it:     cd $RUNNER_DIR && sudo ./svc.sh stop && sudo ./svc.sh uninstall
                 ./config.sh remove --token <a fresh removal token>
EOF
