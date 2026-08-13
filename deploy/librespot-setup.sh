#!/usr/bin/env bash
# Makes this Pi a Spotify Connect target, so anyone in the house can cast to it
# from the full Spotify app on their own phone, with their own account.
#
# Why this exists rather than only the in-app player: the browser-based Web
# Playback SDK needs Widevine DRM plus a Premium account, and the Spotify app
# backing this project is in Development Mode - capped at 25 hand-added users,
# with search limited to 10 results and no radio/recommendations at all. A
# Connect target has none of those limits, needs no browser DRM, and playback
# survives a page reload - which matters here, because the wall reloads itself
# whenever a deploy lands.
#
# Run on real hardware (Pi 5, Raspberry Pi OS Trixie) and verified there.
#
# Idempotent - safe to re-run.
#
# Usage:
#   bash deploy/librespot-setup.sh                       # defaults below
#   bash deploy/librespot-setup.sh --name "Kitchen"      # Connect device name
#   bash deploy/librespot-setup.sh --bitrate 160         # 96 | 160 | 320
#   bash deploy/librespot-setup.sh --backend alsa        # if you have no PipeWire

set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Run this as your normal user, not root/sudo - it calls sudo itself where needed," >&2
  echo "and the service it installs is a USER service that has to belong to you." >&2
  exit 1
fi

DEVICE_NAME="Wall Calendar"
BITRATE="320"
BACKEND="pulseaudio"

while [ $# -gt 0 ]; do
  case "$1" in
    --name)    DEVICE_NAME="${2:?--name needs a value}"; shift 2 ;;
    --bitrate) BITRATE="${2:?--bitrate needs a value}"; shift 2 ;;
    --backend) BACKEND="${2:?--backend needs a value}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

case "$BITRATE" in
  96|160|320) ;;
  *) echo "--bitrate must be 96, 160 or 320 (got '$BITRATE')" >&2; exit 1 ;;
esac

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$1" >&2; }

# ---------------------------------------------------------------------------
log "1/6 Checking there is somewhere for the audio to go"
# ---------------------------------------------------------------------------
# Worth checking first, because the answer is not obvious: a Pi 5 has no 3.5mm
# jack at all, so on this build the only output is HDMI - which works only if the
# attached display actually accepts audio. The ViewSonic TD2230 here does
# (ELD reports "speakers [0x1] FL/FR"); plenty of monitors don't, and then this
# whole script buys you nothing until a USB DAC or Bluetooth speaker is added.
if ls /proc/asound/card*/eld* >/dev/null 2>&1; then
  if grep -qE 'speakers[[:space:]]+\[0x[1-9a-f]' /proc/asound/card*/eld* 2>/dev/null; then
    echo "HDMI display reports speakers - audio has somewhere to go."
  else
    warn "No HDMI sink reports speakers. Check for a USB DAC or Bluetooth output,"
    warn "otherwise librespot will run happily and you will hear nothing."
  fi
fi
aplay -l 2>/dev/null | grep '^card' || warn "aplay lists no cards at all."

# ---------------------------------------------------------------------------
log "2/6 Installing the librespot binary"
# ---------------------------------------------------------------------------
# From raspotify's apt repo, which packages librespot with no Rust toolchain
# needed. The repo is added with an explicitly pinned key rather than the
# upstream `curl ... | sudo sh` one-liner: piping a remote script straight into a
# root shell is a lot of trust to place in a URL for something this easy to do
# properly. Same pattern setup-pi.sh already uses for the GitHub CLI.
if ! command -v librespot >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends curl gnupg
  sudo mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://dtcooper.github.io/raspotify/key.asc \
    | sudo gpg --dearmor -o /etc/apt/keyrings/raspotify.gpg
  sudo chmod go+r /etc/apt/keyrings/raspotify.gpg
  echo "deb [signed-by=/etc/apt/keyrings/raspotify.gpg] https://dtcooper.github.io/raspotify raspotify main" \
    | sudo tee /etc/apt/sources.list.d/raspotify.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends raspotify
else
  echo "librespot already installed - $(librespot --version 2>&1 | head -1)"
fi

# ---------------------------------------------------------------------------
log "3/6 Disabling raspotify's own system service"
# ---------------------------------------------------------------------------
# The package ships a SYSTEM service, and that cannot work on this setup: PipeWire
# runs in the logged-in user's session, and a system unit has no access to that
# user's socket. It would either be silent, or - with the ALSA backend - take
# exclusive hold of the HDMI device and fight Chromium for it.
# Masked rather than merely disabled so a package upgrade doesn't re-enable it.
if systemctl list-unit-files raspotify.service >/dev/null 2>&1; then
  sudo systemctl disable --now raspotify >/dev/null 2>&1 || true
  sudo systemctl mask raspotify >/dev/null 2>&1 || true
  echo "raspotify.service disabled and masked."
fi

# ---------------------------------------------------------------------------
log "4/6 Installing a user service"
# ---------------------------------------------------------------------------
mkdir -p "$HOME/.config/systemd/user" "$HOME/.cache/librespot"

# Flags are the ones librespot 0.8 actually accepts, checked against
# `librespot --help` on the machine rather than assumed - the option names have
# moved between versions, and a wrong one here means the service simply won't
# start.
cat > "$HOME/.config/systemd/user/librespot.service" <<UNIT
[Unit]
Description=librespot (Spotify Connect target for the wall)
# PipeWire lives in this same user session; without it there is no sink to open.
After=pipewire.service pipewire-pulse.service
Wants=pipewire-pulse.service

[Service]
Type=simple
# The pulseaudio backend talks to pipewire-pulse, so librespot SHARES the output
# with Chromium rather than claiming it exclusively, and its volume lands in the
# same mixer as everything else on the machine.
ExecStart=/usr/bin/librespot \\
  --name "$DEVICE_NAME" \\
  --backend $BACKEND \\
  --device-type speaker \\
  --bitrate $BITRATE \\
  --enable-volume-normalisation \\
  --initial-volume 55 \\
  --cache %h/.cache/librespot \\
  --cache-size-limit 512M
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now librespot

# ---------------------------------------------------------------------------
log "5/6 Making it survive without a login"
# ---------------------------------------------------------------------------
# The kiosk session means this user is normally logged in anyway, but lingering
# keeps the user service running across session restarts rather than only while
# someone is "at" the machine.
sudo loginctl enable-linger "$USER"

# ---------------------------------------------------------------------------
log "6/6 Checking it came up"
# ---------------------------------------------------------------------------
sleep 3
if systemctl --user is-active --quiet librespot; then
  echo "librespot is running as \"$DEVICE_NAME\"."
  PORT="$(sudo ss -tlnp 2>/dev/null | grep -o 'librespot.*' >/dev/null && \
    sudo ss -tlnp 2>/dev/null | awk '/librespot/ {print $4}' | head -1 || true)"
  [ -n "${PORT:-}" ] && echo "Listening for Connect on ${PORT}."
else
  warn "librespot is not active. Check: journalctl --user -u librespot -n 40"
fi

if ! systemctl is-active --quiet avahi-daemon; then
  warn "avahi-daemon is not running - Connect discovery is mDNS, so phones won't"
  warn "see this device until it is: sudo systemctl enable --now avahi-daemon"
fi

cat <<EOF

Done. What to expect:

  - Open Spotify on a phone on the same network, start playing something, then
    use the Connect (speaker) button and pick "$DEVICE_NAME".
  - The wall's own device picker (Music -> speaker icon) will also list it, so
    playback started from the wall can be sent to it.
  - Anyone can use it with their own account. No Development Mode user list, no
    Premium requirement on the *display*, no browser DRM involved.
    (Spotify Connect itself still requires the caster to have Premium.)
  - Because playback is no longer in the browser tab, it survives page reloads -
    including the automatic one that follows a deploy.

Useful commands:

  systemctl --user status librespot
  journalctl --user -u librespot -f
  \$EDITOR ~/.config/systemd/user/librespot.service   # then: systemctl --user restart librespot

If it never appears in the Connect picker, the usual causes are:
  - the phone is on a different VLAN/subnet (Connect discovery is link-local)
  - avahi-daemon isn't running: systemctl status avahi-daemon
  - a firewall is blocking mDNS (UDP 5353)
EOF
