#!/usr/bin/env bash
# Waits for the Flask backend to actually be up, then launches Chromium
# full-screen against it. Run at graphical-session login via the
# wall-calendar-kiosk.desktop autostart entry.
set -u

URL="http://127.0.0.1:5000/"

for _ in $(seq 1 60); do
  if curl -s -o /dev/null -w '%{http_code}' "$URL" | grep -q '^200$'; then
    break
  fi
  sleep 1
done

# Package/binary name has varied across Raspberry Pi OS releases.
CHROMIUM_BIN="$(command -v chromium-browser || command -v chromium)"

# Fill these in when they're missing so the script also works when started over
# SSH for debugging, not only from an autostart entry inside a live session.
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
  export WAYLAND_DISPLAY=wayland-0
fi

# Pick the backend from what's actually running rather than letting Chromium
# guess. Raspberry Pi OS Trixie uses labwc (Wayland) and Chromium still defaults
# to the X11 backend, which fails outright with "Missing X server or $DISPLAY"
# unless Xwayland happens to be up. Native Wayland also avoids an Xwayland hop.
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  OZONE_ARGS="--ozone-platform=wayland"
elif [ -n "${DISPLAY:-}" ]; then
  OZONE_ARGS="--ozone-platform=x11"
else
  echo "kiosk-launch: no Wayland socket and no \$DISPLAY - is a desktop session running?" >&2
  exit 1
fi

# Supervised rather than exec'd. This used to exec Chromium, which meant anything
# that killed the browser - a crash, an OOM, or someone restarting it to pick up
# new assets - left a black screen until a human power-cycled the thing, because
# the autostart entry only ever fires at session login. A wall display is
# unattended for weeks at a time, so it has to come back on its own.
#
# It also makes `pkill chromium` a safe way to reload the wall over SSH.
while true; do
  "$CHROMIUM_BIN" \
    --kiosk \
    $OZONE_ARGS \
    `# Without this, Chromium asks gnome-keyring for a password store and a modal` \
    `# "Choose password for new keyring" dialog appears over the kiosk on every` \
    `# boot, waiting for a human who isn't there. The wall stores no passwords, so` \
    `# the basic (in-profile) store is the right answer, not a keyring.` \
    --password-store=basic \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --check-for-update-interval=31536000 \
    --start-fullscreen \
    --incognito \
    "$URL"

  # A clean exit still means the wall is now blank, so it restarts either way.
  # The pause keeps a persistent startup failure from becoming a spin loop that
  # eats the CPU the calendar needs.
  echo "kiosk-launch: chromium exited ($?); restarting in 3s" >&2
  sleep 3
done
