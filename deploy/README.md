# Pi Kiosk Deployment

Sets up (or updates) this app on a Raspberry Pi OS Bookworm device as a
kiosk: the Flask backend runs as a systemd service, a timer periodically
pulls new commits and restarts it, and exactly two things autostart at
login - the full-screen kiosk browser and UxPlay (AirPlay mirroring).

## First-time setup

1. Flash Raspberry Pi OS **with desktop**, enable auto-login to the desktop
   (`sudo raspi-config` → System Options → Boot / Auto Login → Desktop
   Autologin) - the kiosk browser and UxPlay both need an active graphical
   session to autostart into.
2. Get this script onto the Pi. Easiest path since the private secrets repo
   needs `gh` auth anyway:
   ```bash
   gh auth login          # if not already done
   gh repo clone elijahcraig45/wallCalendar ~/calendar/wallCalendar
   cd ~/calendar/wallCalendar
   bash deploy/setup-pi.sh
   ```
3. Reboot to see the kiosk browser + UxPlay come up: `sudo reboot`

The script is interactive the first time it finds *other* autostart entries
(kiosk builds sometimes accumulate leftover autostart cruft from earlier
setup attempts) - it lists what it found, backs everything up to
`~/autostart-backup-<timestamp>/`, and asks before disabling anything.
Pass `--yes` to skip that prompt on a re-run once you've reviewed it once.

## Re-running later

Same command (`bash deploy/setup-pi.sh`) - it's idempotent: pulls latest
code instead of re-cloning, reuses the existing venv, skips the UxPlay
build if it's already installed, and only reports autostart entries it
hasn't already accounted for.

## What it sets up

| Piece | Mechanism | File |
|---|---|---|
| Flask backend | systemd system service | `/etc/systemd/system/wallcalendar.service` |
| Git auto-rebuild | systemd timer (every 10 min) + oneshot service | `wallcalendar-autorebuild.timer`/`.service` |
| Kiosk browser | XDG autostart | `~/.config/autostart/wall-calendar-kiosk.desktop` |
| UxPlay | XDG autostart | `~/.config/autostart/uxplay.desktop` |

## Spotify Connect (separate, optional)

`bash deploy/librespot-setup.sh` — installs raspotify (packaged librespot) and
enables it, making the Pi a Spotify Connect speaker. Not part of `setup-pi.sh`:
it's an independent decision about how music reaches the room, and the calendar
works without it.

```bash
bash deploy/librespot-setup.sh                        # "Wall Calendar", 320kbps, default ALSA out
bash deploy/librespot-setup.sh --name "Kitchen"       # rename the Connect target
bash deploy/librespot-setup.sh --device hw:1,0        # a USB DAC or audio HAT
```

Why bother when the app has its own player: the in-browser Web Playback SDK
needs Widevine DRM plus Premium *on the display*, and the Spotify app backing
this project is stuck in Development Mode — 25 hand-added users, 10-result
search, no radio. A Connect target has none of those limits and no UI to
maintain. The two coexist; the Pi just appears in the wall's device picker as
another speaker.

The Widevine concern is not hypothetical: driving the Music page under headless
Chromium fails with `No supported keysystem was found`, which is exactly what a
Chromium build without Widevine reports. If the SDK never registers a device,
the device picker now says so and points here rather than silently offering a
display that can't play anything.

The auto-rebuild service runs as your normal user (so pulled files/venv
stay user-owned, not root-owned) but needs to restart a root-owned
systemd service - `setup-pi.sh` grants exactly that one command via
`/etc/sudoers.d/wallcalendar-restart`, nothing broader.

## Useful commands

```bash
sudo systemctl status wallcalendar.service          # is the backend up?
journalctl -u wallcalendar.service -f               # live backend logs
sudo systemctl status wallcalendar-autorebuild.timer
journalctl -u wallcalendar-autorebuild.service -n 20  # last rebuild check
```

## Notes / known limits

- The autostart cleanup in `cleanup-autostart.sh` only touches GUI-session
  autostart mechanisms (XDG autostart `.desktop` files, wayfire.ini's
  `[autostart]` section, labwc's autostart script, crontab `@reboot`
  lines) - it deliberately never touches general systemd service
  enablement, since that also covers core OS daemons (networking, ssh,
  bluetooth) that have nothing to do with kiosk autostart and are too
  risky to touch without knowing this specific device's history.
- `/etc/rc.local`, if it has real content, is backed up but left alone
  rather than auto-edited - it's a shell script, not a list of discrete
  entries, so editing it programmatically risks breaking it. Review
  `~/autostart-backup-*/rc.local.bak` and edit it by hand if needed.
- **Neither `setup-pi.sh` nor `librespot-setup.sh` has ever run against real
  hardware.** Review the printed plan in `setup-pi.sh` Step 8 before confirming
  the autostart cleanup, especially on a Pi that already has a working kiosk
  setup you don't want to lose. `librespot-setup.sh` pipes the upstream raspotify
  installer to `sh` (as upstream documents) and rewrites `/etc/raspotify/conf`,
  keeping a `.orig` copy — read it before running it.

## If the wall stops updating

`git-autorebuild.sh` stashes local modifications before pulling, so editing a file
on the Pi no longer wedges updates permanently. Check what it set aside with:

```bash
cd ~/calendar/wallCalendar && git stash list
git stash show -p 'stash@{0}'          # inspect
git stash pop                          # or reapply
```

Note the chicken-and-egg this fix had to be dragged through: the guard lives in
the repo it updates, so a Pi already wedged by a dirty tree cannot pull the fix
that unwedges it. Clear it once by hand (`git checkout -- <file>`), after which it
self-heals.
