#!/usr/bin/env bash
# Finds GUI-session autostart entries other than the wall-calendar kiosk
# browser and UxPlay, and offers to back them up + disable them.
#
# Deliberately scoped to GUI-login autostart mechanisms only (XDG autostart
# .desktop files, wayfire.ini's [autostart] section, labwc's autostart
# script, crontab @reboot lines, /etc/rc.local) - NOT general systemd
# service enablement, since that also covers core OS daemons (networking,
# ssh, bluetooth, etc.) that have nothing to do with "what launches on the
# kiosk's desktop at login" and are too risky to touch programmatically
# without knowing this specific device's history. Anything found is backed
# up before being touched, never hard-deleted.
#
# Usage: bash cleanup-autostart.sh [--yes]

set -uo pipefail

AUTO_YES=false
for arg in "$@"; do
  [ "$arg" = "--yes" ] || [ "$arg" = "-y" ] && AUTO_YES=true
done

KEEP_DESKTOP_FILES=("wall-calendar-kiosk.desktop" "uxplay.desktop")
AUTOSTART_DIR="$HOME/.config/autostart"
SYSTEM_AUTOSTART_DIR="/etc/xdg/autostart"
WAYFIRE_INI="$HOME/.config/wayfire.ini"
LABWC_AUTOSTART="$HOME/.config/labwc/autostart"
BACKUP_DIR="$HOME/autostart-backup-$(date +%Y%m%d-%H%M%S)"

is_kept() {
  local name="$1"
  for keep in "${KEEP_DESKTOP_FILES[@]}"; do
    [ "$name" = "$keep" ] && return 0
  done
  return 1
}

FOUND=()

# ---- XDG autostart: user + system ----
for dir in "$AUTOSTART_DIR" "$SYSTEM_AUTOSTART_DIR"; do
  [ -d "$dir" ] || continue
  for f in "$dir"/*.desktop; do
    [ -e "$f" ] || continue
    is_kept "$(basename "$f")" && continue
    FOUND+=("desktop:$f")
  done
done

# ---- wayfire.ini [autostart] section ----
if [ -f "$WAYFIRE_INI" ] && grep -q '^\[autostart\]' "$WAYFIRE_INI"; then
  if awk '/^\[autostart\]/{f=1;next} /^\[/{f=0} f && NF' "$WAYFIRE_INI" | grep -q .; then
    FOUND+=("wayfire:$WAYFIRE_INI")
  fi
fi

# ---- labwc autostart script ----
if [ -s "$LABWC_AUTOSTART" ]; then
  FOUND+=("labwc:$LABWC_AUTOSTART")
fi

# ---- crontab @reboot ----
if crontab -l 2>/dev/null | grep -q '^@reboot'; then
  FOUND+=("cron:@reboot entries in $(whoami)'s crontab")
fi

# ---- /etc/rc.local ----
if [ -f /etc/rc.local ] && grep -vE '^\s*(#|exit 0\s*$|#!)' /etc/rc.local | grep -q '\S'; then
  FOUND+=("rc.local:/etc/rc.local")
fi

if [ ${#FOUND[@]} -eq 0 ]; then
  echo "No other GUI-session autostart entries found - only the kiosk browser and UxPlay are set up."
  exit 0
fi

echo "Found ${#FOUND[@]} other autostart-related item(s):"
for item in "${FOUND[@]}"; do
  echo "  - ${item#*:} (via ${item%%:*})"
done

if ! $AUTO_YES; then
  read -rp "Back these up to $BACKUP_DIR and disable them? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Leaving them as-is."; exit 0; }
fi

mkdir -p "$BACKUP_DIR"

for item in "${FOUND[@]}"; do
  kind="${item%%:*}"
  target="${item#*:}"
  case "$kind" in
    desktop)
      cp "$target" "$BACKUP_DIR/$(basename "$target").bak"
      if [[ "$target" == "$SYSTEM_AUTOSTART_DIR"/* ]]; then
        sudo rm -f "$target"
      else
        rm -f "$target"
      fi
      echo "Removed $target (backed up)."
      ;;
    wayfire)
      cp "$target" "$BACKUP_DIR/wayfire.ini.bak"
      awk '
        /^\[autostart\]/{print; f=1; next}
        /^\[/{f=0}
        f && NF {next}
        {print}
      ' "$target" > "$target.new" && mv "$target.new" "$target"
      echo "Cleared [autostart] entries in $target (backed up)."
      ;;
    labwc)
      cp "$target" "$BACKUP_DIR/labwc-autostart.bak"
      : > "$target"
      echo "Cleared $target (backed up)."
      ;;
    cron)
      crontab -l 2>/dev/null > "$BACKUP_DIR/crontab.bak"
      crontab -l 2>/dev/null | grep -v '^@reboot' | crontab -
      echo "Removed @reboot lines from crontab (backed up)."
      ;;
    rc.local)
      sudo cp /etc/rc.local "$BACKUP_DIR/rc.local.bak"
      echo "Left /etc/rc.local as-is (backed up for reference) - review $BACKUP_DIR/rc.local.bak"
      echo "and edit /etc/rc.local by hand; it's structurally different enough"
      echo "(a shell script, not a list of entries) that auto-editing it here"
      echo "risks breaking it."
      ;;
  esac
done

echo "Done. Backups in $BACKUP_DIR."
