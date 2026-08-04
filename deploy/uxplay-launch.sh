#!/usr/bin/env bash
# XDG autostart has no built-in restart-on-crash the way systemd does, so
# this wraps uxplay in a simple restart loop instead. Run at graphical-
# session login via the uxplay.desktop autostart entry.
set -u

while true; do
  uxplay -n "Wall Calendar"
  sleep 2
done
