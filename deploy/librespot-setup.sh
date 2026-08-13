#!/usr/bin/env bash
# Makes this Pi a Spotify Connect target, so anyone in the house can cast to it
# from the full Spotify app on their own phone, with their own account.
#
# Why this exists rather than only the in-app player: the browser-based Web
# Playback SDK needs Widevine DRM plus a Premium account, and the Spotify app
# backing this project is in Development Mode - capped at 25 hand-added users,
# with search limited to 10 results and no radio/recommendations at all. A
# Connect target has none of those limits, needs no browser DRM, and there's no
# playback UI left to maintain. The wall's own device picker still works; the Pi
# simply shows up in it as another speaker.
#
# !!! NEVER RUN AGAINST REAL HARDWARE !!!
# This script has not been executed on a Pi. Same status as setup-pi.sh. Read it
# before running it, and expect to adjust the audio device for your setup.
#
# Idempotent - safe to re-run.
#
# Usage:
#   bash deploy/librespot-setup.sh                       # defaults below
#   bash deploy/librespot-setup.sh --name "Kitchen"      # Connect device name
#   bash deploy/librespot-setup.sh --bitrate 320         # 96 | 160 | 320
#   bash deploy/librespot-setup.sh --device hw:1,0       # specific ALSA device

set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  echo "Run this as your normal user, not root/sudo - it calls sudo itself where needed." >&2
  exit 1
fi

DEVICE_NAME="Wall Calendar"
BITRATE="320"
ALSA_DEVICE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --name)    DEVICE_NAME="${2:?--name needs a value}"; shift 2 ;;
    --bitrate) BITRATE="${2:?--bitrate needs a value}"; shift 2 ;;
    --device)  ALSA_DEVICE="${2:?--device needs a value}"; shift 2 ;;
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
log "1/5 Installing raspotify"
# ---------------------------------------------------------------------------
# raspotify is a packaged librespot with a systemd unit already wired up, which
# is why it's preferred here over building librespot from source: no Rust
# toolchain on the Pi and no unit file to hand-write.
if command -v librespot >/dev/null 2>&1 || dpkg -s raspotify >/dev/null 2>&1; then
  echo "raspotify/librespot already installed - skipping install, will still rewrite config."
else
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends curl
  # The official installer adds the apt repo and installs the package.
  curl -sSL https://dtcooper.github.io/raspotify/install.sh | sudo sh
fi

# ---------------------------------------------------------------------------
log "2/5 Picking an audio output"
# ---------------------------------------------------------------------------
# Left unset by default on purpose: with no explicit device, librespot uses the
# ALSA default, which is what you want when the Pi's onboard jack or an HDMI
# display's speakers are already the system default. Override with --device when
# a USB DAC or HAT needs naming.
if [ -n "$ALSA_DEVICE" ]; then
  echo "Using ALSA device: $ALSA_DEVICE"
else
  echo "Using the system default ALSA device."
  echo "Available playback devices (for reference if you need --device):"
  aplay -l 2>/dev/null || warn "aplay not available; can't list devices."
fi

# ---------------------------------------------------------------------------
log "3/5 Writing /etc/raspotify/conf"
# ---------------------------------------------------------------------------
# Backed up rather than edited in place - the packaged conf is a documented
# template worth keeping a copy of.
if [ -f /etc/raspotify/conf ] && [ ! -f /etc/raspotify/conf.orig ]; then
  sudo cp /etc/raspotify/conf /etc/raspotify/conf.orig
  echo "Original config saved to /etc/raspotify/conf.orig"
fi

sudo mkdir -p /etc/raspotify
{
  echo "# Written by deploy/librespot-setup.sh - re-run it to regenerate."
  echo "LIBRESPOT_NAME=\"$DEVICE_NAME\""
  echo "LIBRESPOT_BITRATE=\"$BITRATE\""
  # Announce as a speaker so phones group it sensibly in the Connect picker.
  echo "LIBRESPOT_DEVICE_TYPE=\"speaker\""
  # Keeps the device listed in everyone's Connect picker even when idle;
  # otherwise it disappears from the list until something is cast to it.
  echo "LIBRESPOT_DISABLE_DISCOVERY=\"\""
  # Normalise volume so a quiet track followed by a loud one doesn't startle
  # the room - worth it on a shared speaker nobody is holding a remote for.
  echo "LIBRESPOT_ENABLE_VOLUME_NORMALISATION=\"\""
  echo "LIBRESPOT_INITIAL_VOLUME=\"60\""
  if [ -n "$ALSA_DEVICE" ]; then
    echo "LIBRESPOT_DEVICE=\"$ALSA_DEVICE\""
  fi
} | sudo tee /etc/raspotify/conf >/dev/null

# ---------------------------------------------------------------------------
log "4/5 Enabling the service"
# ---------------------------------------------------------------------------
sudo systemctl daemon-reload
sudo systemctl enable raspotify
sudo systemctl restart raspotify

# ---------------------------------------------------------------------------
log "5/5 Checking it came up"
# ---------------------------------------------------------------------------
sleep 2
if sudo systemctl is-active --quiet raspotify; then
  echo "raspotify is running as \"$DEVICE_NAME\"."
else
  warn "raspotify is not active. Check: journalctl -u raspotify -n 40"
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

Useful commands:

  sudo systemctl status raspotify
  journalctl -u raspotify -f
  sudo nano /etc/raspotify/conf      # then: sudo systemctl restart raspotify

If it never appears in the Connect picker, the usual causes are:
  - the phone is on a different VLAN/subnet (Connect discovery is link-local)
  - avahi-daemon isn't running: sudo systemctl status avahi-daemon
  - a firewall is blocking mDNS (UDP 5353)
EOF
