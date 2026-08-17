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

# The desktop panel has to go before the window is placed, not after.
#
# wf-panel-pi is a layer-shell panel with an exclusive zone, so labwc subtracts
# its ~34px from the usable area that a *maximized* window is given. Under the old
# --kiosk (fullscreen) launch that didn't matter, because fullscreen ignores
# exclusive zones and covered the panel. This script now maximizes instead of
# going fullscreen (see the block below for why), so without this the wall would
# lose 34px off the top and show a taskbar strip over the clock.
#
# lwrespawn is the supervisor that restarts the panel, so it has to die first or
# the panel comes straight back. pcmanfm-pi (the desktop icons/wallpaper) is left
# alone: it sits below our window and costs nothing.
pkill -f 'lwrespawn /usr/bin/wf-panel-pi' 2>/dev/null || true
pkill -x wf-panel-pi 2>/dev/null || true

# Keeps a minimised window from becoming a blank wall.
#
# Chromium's --app title strip carries a minimise button, and one tap on it hides
# the window for good: the browser is still running, so the supervision loop below
# sees nothing wrong, and touch cannot bring it back. That is a worse failure than
# the one this script was written to prevent.
#
# It re-raises unconditionally rather than only when minimised, because nothing can
# tell us it is minimised - Chromium does not mark the document hidden (so a
# visibilitychange listener in the page never fires; that was tried), and
# `wlrctl toplevel find state:minimized` always exits 1. Unconditional is safe
# here: the kiosk is the only window, so there is no focus to steal, and this was
# measured against a live typing session - the on-screen keyboard stays up and
# keystrokes keep landing in the focused field across repeated calls.
#
# The app_id is looked up rather than hardcoded: it is derived from the URL in
# --app mode, and wlrctl's matcher does no globbing, so "app_id:chrome-*" silently
# matches nothing.
WATCHDOG_PIDFILE="${XDG_RUNTIME_DIR}/wallcal-kiosk-watchdog.pid"

# This script re-execs itself (see the end of the loop), which would otherwise
# leave a new watchdog behind on every Chromium restart until there were dozens.
if [ -f "$WATCHDOG_PIDFILE" ]; then
  kill "$(cat "$WATCHDOG_PIDFILE")" 2>/dev/null || true
  rm -f "$WATCHDOG_PIDFILE"
fi

if command -v wlrctl >/dev/null; then
  (
    while true; do
      sleep 30
      app_id="$(wlrctl toplevel list 2>/dev/null | grep -m1 '^chrome' | cut -d: -f1)"
      [ -n "$app_id" ] || continue
      # maximize is what un-minimises it; focus alone is refused for a minimised
      # window. Both are no-ops when it is already up.
      wlrctl toplevel maximize "app_id:$app_id" >/dev/null 2>&1 || true
      wlrctl toplevel focus "app_id:$app_id" >/dev/null 2>&1 || true
    done
  ) &
  echo $! > "$WATCHDOG_PIDFILE"
else
  echo "kiosk-launch: wlrctl missing - a tap on Chromium's minimise button will" >&2
  echo "kiosk-launch: blank the wall until someone SSHes in. apt install wlrctl." >&2
fi

# Supervised rather than exec'd. This used to exec Chromium, which meant anything
# that killed the browser - a crash, an OOM, or someone restarting it to pick up
# new assets - left a black screen until a human power-cycled the thing, because
# the autostart entry only ever fires at session login. A wall display is
# unattended for weeks at a time, so it has to come back on its own.
#
# It also makes `pkill chromium` a safe way to reload the wall over SSH.
while true; do
  `# Maximized, NOT fullscreen, and --app rather than --kiosk. This is the` \
  `# on-screen keyboard fix, and it is not a style preference - it is the only` \
  `# arrangement that lets the keyboard be seen at all.` \
  `#` \
  `# The flags above are necessary but were never sufficient. With --kiosk the` \
  `# keyboard was working the entire time and simply invisible: squeekboard mapped` \
  `# its 1920x360 surface, loaded the layout, and reported Visible=true, while` \
  `# nothing appeared on screen. labwc stacks a *fullscreen* window above the` \
  `# wlr-layer-shell "top" layer, which is the layer both squeekboard and wvkbd` \
  `# use. (Verified by putting a labnag on "overlay", which does draw above` \
  `# fullscreen, and on "top", which does not - and no packaged OSK offers a way` \
  `# to ask for "overlay".) So the window has to stop being fullscreen.` \
  `#` \
  `# --kiosk implies fullscreen, so it goes, and --app replaces it to keep the` \
  `# browser chrome away. Maximized rather than a fixed 1920x1080 on purpose:` \
  `# squeekboard sets an exclusive zone, so labwc shrinks a maximized window when` \
  `# the keyboard opens and the page reflows above it instead of being covered.` \
  `#` \
  `# Cost of --app: Chromium draws its own 26px title strip, which it will not` \
  `# give up (labwc SetDecorations/serverDecoration cannot remove it - the strip is` \
  `# the client's, not a decoration). deploy/labwc-rc.xml hides it from the` \
  `# taskbar and window switcher; the strip itself stays.` \
  "$CHROMIUM_BIN" \
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
    --start-maximized \
    --incognito \
    --app="$URL"

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
