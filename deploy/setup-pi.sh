#!/usr/bin/env bash
# Sets up (or updates) the wall calendar kiosk on a Raspberry Pi OS Bookworm
# device: clones/updates this app + its private secrets repo, installs it as
# a systemd service, sets up a git-pull-and-rebuild timer, installs UxPlay
# (AirPlay mirroring receiver) if missing, wires up exactly two autostart
# entries (kiosk browser + UxPlay), and offers to back up/disable any other
# autostart entries it finds.
#
# Idempotent - safe to re-run. Run as the normal desktop user (NOT root);
# it calls `sudo` itself for the specific steps that need it.
#
# Usage:
#   bash deploy/setup-pi.sh                 # interactive (asks before
#                                            # touching other autostarts)
#   bash deploy/setup-pi.sh --yes           # non-interactive, auto-confirms
#                                            # the autostart cleanup

set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Run this as your normal user, not root/sudo - it calls sudo itself where needed." >&2
  exit 1
fi

AUTO_YES=false
for arg in "$@"; do
  case "$arg" in
    --yes|-y) AUTO_YES=true ;;
  esac
done

REPO_USER="elijahcraig45"
CALENDAR_ROOT="$HOME/calendar"
INSTALL_DIR="$CALENDAR_ROOT/wallCalendar"
SECRETS_DIR="$CALENDAR_ROOT/wallCalendar-secrets"
SYSTEMD_USER="$(whoami)"
DEPLOY_DIR="$INSTALL_DIR/deploy"
AUTOSTART_DIR="$HOME/.config/autostart"
BACKUP_DIR="$HOME/autostart-backup-$(date +%Y%m%d-%H%M%S)"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$1" >&2; }

# ---------------------------------------------------------------------------
log "1/8 Installing OS packages"
# ---------------------------------------------------------------------------
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  git python3-venv python3-pip curl wget \
  cmake pkg-config libssl-dev libplist-dev libavahi-compat-libdnssd-dev \
  libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
  gstreamer1.0-libav gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-alsa

# Package/binary name has varied across Raspberry Pi OS releases
# (chromium-browser vs plain chromium) - try both rather than assuming.
if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends chromium-browser \
    || sudo apt-get install -y --no-install-recommends chromium
fi

# gh isn't in Raspberry Pi OS's default apt repos - add GitHub's own repo
# (official install method) if it's missing, rather than a plain apt install
# that would silently fail to find the package.
if ! command -v gh >/dev/null 2>&1; then
  echo "Installing GitHub CLI (gh) from GitHub's own apt repo..."
  sudo mkdir -p -m 755 /etc/apt/keyrings
  wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y gh
fi

# ---------------------------------------------------------------------------
log "2/8 GitHub auth check (needed for the private secrets repo)"
# ---------------------------------------------------------------------------
if ! gh auth status >/dev/null 2>&1; then
  warn "gh is not authenticated yet."
  echo "Run 'gh auth login' now in another terminal (or here, if interactive),"
  echo "then re-run this script. Needed to clone the private wallCalendar-secrets repo."
  if [ -t 0 ]; then
    read -rp "Run 'gh auth login' now? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      gh auth login
    else
      echo "Skipping secrets clone - you'll need to place secrets manually (see README)."
    fi
  fi
fi

# ---------------------------------------------------------------------------
log "3/8 Cloning/updating repos"
# ---------------------------------------------------------------------------
mkdir -p "$CALENDAR_ROOT"

clone_or_pull() {
  local dir="$1" repo="$2"
  if [ -d "$dir/.git" ]; then
    echo "Updating $dir"
    git -C "$dir" pull --ff-only
  else
    echo "Cloning $repo into $dir"
    gh repo clone "$repo" "$dir" 2>/dev/null || git clone "https://github.com/$repo.git" "$dir"
  fi
}

clone_or_pull "$INSTALL_DIR" "$REPO_USER/wallCalendar"

if gh auth status >/dev/null 2>&1; then
  clone_or_pull "$SECRETS_DIR" "$REPO_USER/wallCalendar-secrets"
  log "Restoring secrets from wallCalendar-secrets (per its own documented restore steps)"
  mkdir -p "$INSTALL_DIR/secrets" "$INSTALL_DIR/data"
  cp -r "$SECRETS_DIR/secrets/." "$INSTALL_DIR/secrets/" 2>/dev/null || warn "no secrets/ found in wallCalendar-secrets yet"
  cp "$SECRETS_DIR/.env" "$INSTALL_DIR/.env" 2>/dev/null || warn "no .env found in wallCalendar-secrets yet"
  cp "$SECRETS_DIR/data/account_labels.json" "$INSTALL_DIR/data/account_labels.json" 2>/dev/null || warn "no data/account_labels.json found in wallCalendar-secrets yet"
else
  warn "Skipping wallCalendar-secrets clone - not authenticated. Restore secrets manually:"
  echo "  gh repo clone $REPO_USER/wallCalendar-secrets $SECRETS_DIR"
  echo "  cp -r $SECRETS_DIR/secrets $INSTALL_DIR/"
  echo "  cp $SECRETS_DIR/.env $INSTALL_DIR/.env"
  echo "  cp $SECRETS_DIR/data/account_labels.json $INSTALL_DIR/data/account_labels.json"
fi

# ---------------------------------------------------------------------------
log "4/8 Python virtualenv + dependencies"
# ---------------------------------------------------------------------------
cd "$INSTALL_DIR"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
deactivate

# ---------------------------------------------------------------------------
log "5/8 Installing UxPlay (if not already present)"
# ---------------------------------------------------------------------------
if command -v uxplay >/dev/null 2>&1; then
  echo "uxplay already installed at $(command -v uxplay) - skipping build."
else
  echo "Building UxPlay from source (no apt package for it on Raspberry Pi OS)..."
  BUILD_DIR="$(mktemp -d)"
  git clone --depth 1 https://github.com/FDH2/UxPlay.git "$BUILD_DIR/UxPlay"
  mkdir -p "$BUILD_DIR/UxPlay/build"
  (cd "$BUILD_DIR/UxPlay/build" && cmake .. && make -j"$(nproc)" && sudo make install)
  rm -rf "$BUILD_DIR"
fi

# ---------------------------------------------------------------------------
log "6/8 Backend systemd service (Flask server)"
# ---------------------------------------------------------------------------
sed \
  -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" \
  -e "s#__USER__#$SYSTEMD_USER#g" \
  "$DEPLOY_DIR/wallcalendar.service.template" | sudo tee /etc/systemd/system/wallcalendar.service >/dev/null

# ---------------------------------------------------------------------------
log "7/8 Git auto-rebuild timer"
# ---------------------------------------------------------------------------
sed \
  -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" \
  -e "s#__USER__#$SYSTEMD_USER#g" \
  "$DEPLOY_DIR/wallcalendar-autorebuild.service.template" | sudo tee /etc/systemd/system/wallcalendar-autorebuild.service >/dev/null
sudo cp "$DEPLOY_DIR/wallcalendar-autorebuild.timer" /etc/systemd/system/wallcalendar-autorebuild.timer

# Narrowly-scoped passwordless sudo rule: the autorebuild service runs git
# pull/pip install as this user (so files stay user-owned, not root-owned),
# but restarting the backend service needs root - grant exactly that, and
# nothing broader.
SUDOERS_LINE="$SYSTEMD_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart wallcalendar.service, /usr/bin/systemctl start wallcalendar.service, /usr/bin/systemctl stop wallcalendar.service"
echo "$SUDOERS_LINE" | sudo tee /etc/sudoers.d/wallcalendar-restart >/dev/null
sudo chmod 440 /etc/sudoers.d/wallcalendar-restart
sudo visudo -c -f /etc/sudoers.d/wallcalendar-restart

sudo systemctl daemon-reload
sudo systemctl enable --now wallcalendar.service
sudo systemctl enable --now wallcalendar-autorebuild.timer

# ---------------------------------------------------------------------------
log "8/8 Autostart: kiosk browser + UxPlay (and cleaning up everything else)"
# ---------------------------------------------------------------------------
mkdir -p "$AUTOSTART_DIR"
chmod +x "$DEPLOY_DIR/kiosk-launch.sh" "$DEPLOY_DIR/uxplay-launch.sh"

sed -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" \
  "$DEPLOY_DIR/wall-calendar-kiosk.desktop.template" > "$AUTOSTART_DIR/wall-calendar-kiosk.desktop"
sed -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" \
  "$DEPLOY_DIR/uxplay.desktop.template" > "$AUTOSTART_DIR/uxplay.desktop"

CLEANUP_ARGS=()
$AUTO_YES && CLEANUP_ARGS+=(--yes)
bash "$DEPLOY_DIR/cleanup-autostart.sh" "${CLEANUP_ARGS[@]}"

log "Done"
echo "Backend:      sudo systemctl status wallcalendar.service"
echo "Auto-rebuild: sudo systemctl status wallcalendar-autorebuild.timer"
echo "Logs:         journalctl -u wallcalendar.service -f"
echo "Reboot to see the kiosk browser + UxPlay autostart: sudo reboot"
