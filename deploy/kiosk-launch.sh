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

exec "$CHROMIUM_BIN" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  --start-fullscreen \
  --incognito \
  "$URL"
