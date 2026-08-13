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
  # --enable-wayland-ime plus a text-input version is what makes the on-screen
  # keyboard work, and without it there is no way to type on this thing at all:
  # tapping the event Title field, or Spotify search, focused the input and nothing
  # appeared. squeekboard was installed and running the whole time, and labwc
  # supports the protocol - the missing piece was Chromium, which does not
  # advertise text-input under Wayland unless told to, so the compositor never
  # learned that a text field had focus and never asked for a keyboard.
  #
  # Both switches are present in Chromium 150 (checked against the binary rather
  # than assumed - Chromium removes switches without much ceremony).
  OZONE_ARGS="--ozone-platform=wayland --enable-wayland-ime --wayland-text-input-version=3"
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

  # Re-exec so an updated version of THIS script takes effect.
  #
  # Without it, supervision and push-to-deploy quietly fight each other: bash
  # parses the whole `while` loop up front, so a running supervisor keeps launching
  # the old command line no matter how many times Chromium is restarted. That is
  # exactly how the on-screen-keyboard flags appeared to "not work" after a
  # successful deploy - the flags were on disk and the process was still being
  # started without them.
  #
  # Guarded on the file still parsing: a syntax error mid-edit would otherwise
  # exec a broken script and leave the wall black with nothing to recover it. If it
  # doesn't parse, carry on with the version already in memory.
  if bash -n "$0" 2>/dev/null; then
    exec "$0"
  else
    echo "kiosk-launch: $0 has a syntax error; staying on the loaded version" >&2
  fi
done
