"""Bluetooth pairing and connection for a wall with no desktop.

The wall boots straight into the kiosk browser, so there is no settings applet and
no tray icon: without this, pairing a speaker means SSH-ing in. Everything here is
reachable from /system.

Why bluetoothctl and not python-dbus: pairing over org.bluez requires a registered
pairing *agent*, which means a D-Bus mainloop running in a thread alongside Flask.
bluetoothctl already is that agent - it registers one for the lifetime of the
command - so shelling out gets correct pairing behaviour for free. The venv also
has no `dbus` module (it is a system package, and the venv does not use system
site-packages), so python-dbus would be a new dependency on top of that.

Verified on the wall (BlueZ 5.82, Raspberry Pi OS Trixie): the `calendar` user can
scan, read state, and change adapter settings without sudo and without being in the
`bluetooth` group - Debian's D-Bus policy already allows it. If a future image
tightens that, the symptom is every call failing with "Failed to ...
org.bluez.Error.NotAuthorized", and the fix is `usermod -aG bluetooth calendar`
plus a restart of wallcalendar.service (group membership is read at process start).

Known limit: only devices that pair without a passkey ("Just Works" - speakers,
headphones, most trackpads) can be paired from here. A device that wants a
displayed or typed PIN needs an interactive agent, which this deliberately is not.
"""

import re
import subprocess
import threading
import time

from app import preferences

# Long enough for a speaker that was only just put into pairing mode to show up,
# short enough that the page's poll doesn't look stuck. The scan runs on a
# background thread, so this is not a request timeout.
SCAN_SECONDS = 15

# How often the reconnect loop wakes up. A connect attempt costs about nothing -
# measured at ~0s on the wall whether it succeeds or fails - so this is about being
# polite with the radio, not about CPU.
RECONNECT_INTERVAL_SECONDS = 60

# The first pass runs sooner than the interval. Measured on the wall: after a reboot
# BlueZ leaves a trusted speaker disconnected, so waiting a full minute meant a
# minute of silence for no reason. Not zero either - the adapter is still coming up
# while Flask is already serving, and a connect attempt against an unpowered adapter
# just burns the first backoff step.
RECONNECT_FIRST_PASS_SECONDS = 15

# A device that is simply switched off will fail every single time. Rather than
# paging it once a minute forever, each consecutive failure doubles how many cycles
# are skipped before the next try, up to this cap. A success resets it, so a speaker
# that comes on is picked up within a minute of the next due attempt.
RECONNECT_MAX_BACKOFF_CYCLES = 8

# bluetoothctl colourises even when stdout is a pipe.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_DEVICE_LINE = re.compile(r"^Device ([0-9A-F:]{17}) (.*)$", re.MULTILINE)

# A scan is a single shared piece of hardware state, so it is tracked per-process
# rather than per-request: two overlapping scans would stop each other's
# discovery when the first one exits.
_scan_lock = threading.Lock()
_scan_until = 0.0

# One adapter, so one action at a time. Without this the reconnect loop could fire a
# connect in the middle of a user's pairing attempt and the two would fight over the
# same hardware.
_action_lock = threading.Lock()

# MAC -> {"failures": n, "skip": cycles-left}, for the backoff above. In memory on
# purpose: after a restart it is right to try everything once.
_reconnect_state: dict[str, dict] = {}
_reconnect_thread: threading.Thread | None = None


class BluetoothUnavailable(RuntimeError):
    """bluetoothctl is missing, or there is no adapter to talk to."""


def _run(args: list[str], timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # bluez not installed
        raise BluetoothUnavailable("Bluetooth tools are not installed on this device.") from exc
    except subprocess.TimeoutExpired as exc:
        raise BluetoothUnavailable("Bluetooth is not responding.") from exc
    # bluetoothctl exits 0 for most failures and reports them on stdout, so the
    # return code is not a reliable success signal - callers check the text.
    return _ANSI.sub("", result.stdout + result.stderr)


def _looks_unnamed(mac: str, name: str) -> bool:
    """True when bluetoothctl had no name and fell back to the address.

    A scan in a house picks up dozens of phones and BLE beacons that only ever
    show up as their own MAC. Listing them makes the real speaker impossible to
    find on a wall-sized list, so they are filtered out.
    """
    return name.replace("-", ":").upper() == mac.upper()


def _mac_set(subcommand: str) -> set[str]:
    out = _run(["devices", subcommand], timeout=15)
    return {m.group(1).upper() for m in _DEVICE_LINE.finditer(out)}


def _info_flags(mac: str) -> dict:
    """Paired/Bonded/Trusted/Connected for one device, from `bluetoothctl info`.

    Needed because `devices Paired` does not mean what it looks like. Measured on
    the wall's own speaker (BlueZ 5.82): `devices Paired` listed nothing at all
    while `info` on the same device reported `Paired: yes` - the filter appears to
    track *bonding*, and this speaker pairs without storing a link key
    (`Bonded: no`). Reading the flags per device is the only accurate way.
    """
    out = _run(["info", mac], timeout=15)

    def flag(key: str) -> bool:
        return re.search(rf"^\s*{key}:\s*yes\s*$", out, re.MULTILINE) is not None

    return {
        "paired": flag("Paired"),
        "bonded": flag("Bonded"),
        "trusted": flag("Trusted"),
        "connected": flag("Connected"),
    }


def adapter() -> dict:
    out = _run(["show"], timeout=15)
    if "No default controller" in out or not out.strip():
        raise BluetoothUnavailable("No Bluetooth adapter found.")

    def flag(key: str) -> bool:
        return re.search(rf"^\s*{key}:\s*yes\s*$", out, re.MULTILINE) is not None

    name = re.search(r"^\s*(?:Alias|Name):\s*(.+)$", out, re.MULTILINE)
    address = re.search(r"Controller ([0-9A-F:]{17})", out)
    return {
        "address": address.group(1) if address else None,
        "name": name.group(1).strip() if name else "Bluetooth",
        "powered": flag("Powered"),
        "discoverable": flag("Discoverable"),
        "pairable": flag("Pairable"),
        "scanning": scanning(),
    }


def devices() -> list[dict]:
    """Everything BlueZ knows about, annotated with what state it is in.

    Two tiers on purpose. The wall's *own* devices get an `info` call each, because
    that is the only place the flags are accurate (see _info_flags). Everything else
    - the thirty phones and beacons a scan picks up in a house - gets the cheap
    treatment, since by definition none of them is paired or trusted. That keeps
    this at one subprocess per device we actually care about, typically one or two,
    rather than 40 per poll.
    """
    # Union of all three filters: any of them is evidence the device is ours, and
    # none of them alone is reliable.
    ours = _mac_set("Trusted") | _mac_set("Paired") | _mac_set("Bonded") | _mac_set("Connected")

    found = []
    for match in _DEVICE_LINE.finditer(_run(["devices"], timeout=15)):
        mac, name = match.group(1).upper(), match.group(2).strip()
        unnamed = _looks_unnamed(mac, name)
        # An unnamed device is only worth showing if it is one of ours already -
        # then hiding it would make it impossible to disconnect or forget.
        if unnamed and mac not in ours:
            continue

        if mac in ours:
            flags = _info_flags(mac)
        else:
            flags = {"paired": False, "bonded": False, "trusted": False, "connected": False}

        found.append(
            {
                "address": mac,
                "name": name if not unnamed else mac,
                # "Ours": set up on this wall, and the thing the UI should offer to
                # connect rather than pair. Trust is the marker that persists - this
                # speaker reports Paired: no whenever it is disconnected.
                "known": mac in ours,
                **flags,
            }
        )

    # Connected first, then ours, then the rest - the useful ones stay at the top of
    # a list that grows every time anyone walks past with a phone.
    found.sort(key=lambda d: (not d["connected"], not d["known"], d["name"].lower()))
    return found


def scanning() -> bool:
    return time.monotonic() < _scan_until


def start_scan() -> bool:
    """Kick off discovery on a background thread.

    Returns False if a scan is already running. `bluetoothctl scan on` holds
    discovery only for as long as the process lives, which is why this blocks a
    thread for SCAN_SECONDS instead of firing and forgetting.
    """
    global _scan_until
    with _scan_lock:
        if scanning():
            return False
        _scan_until = time.monotonic() + SCAN_SECONDS

    def run():
        global _scan_until
        try:
            _run(["--timeout", str(SCAN_SECONDS), "scan", "on"], timeout=SCAN_SECONDS + 10)
        except BluetoothUnavailable:
            pass
        finally:
            # Let the UI stop showing "scanning" even if the command died early.
            _scan_until = 0.0

    threading.Thread(target=run, daemon=True, name="bt-scan").start()
    return True


# bluetoothctl reports success in different words per verb, and exits 0 either way,
# so there is nothing to do but match the text. Measured against BlueZ 5.82 rather
# than guessed - "remove" was the trap: it answers "Device has been removed", which
# contains neither "successful" nor "succeeded", so a shared check on those two made
# every successful Forget report a failure while the device disappeared anyway.
_SUCCESS_TEXT = {
    "pair": ("pairing successful",),
    "connect": ("connection successful",),
    "disconnect": ("successful disconnected", "disconnection successful"),
    "trust": ("succeeded",),
    "remove": ("device has been removed",),
}


def _action(verb: str, mac: str, timeout: int = 30) -> dict:
    out = _run([verb, mac], timeout=timeout)
    lowered = out.lower()
    expected = _SUCCESS_TEXT.get(verb, ("successful", "succeeded"))
    ok = any(text in lowered for text in expected)
    if not ok:
        # bluetoothctl's failures are one line of prose on stdout; surface it
        # rather than a generic message, because "org.bluez.Error.AuthenticationFailed"
        # vs "not available" mean very different things to whoever is standing there.
        reason = next(
            (
                line.strip()
                for line in out.splitlines()
                if "Failed" in line or "not available" in line
            ),
            None,
        )
        return {"ok": False, "error": reason or f"Could not {verb} that device."}
    return {"ok": True}


def pair(mac: str) -> dict:
    """Pair, then trust, then connect - the sequence a speaker actually needs.

    Trusting matters on an unattended wall: without it BlueZ asks for
    authorisation on every reconnect, and there is nobody to answer, so the
    speaker silently stops coming back after a power cycle.
    """
    with _action_lock:
        result = _action("pair", mac, timeout=45)
        if not result["ok"]:
            return result
        _action("trust", mac, timeout=15)
        _clear_optout(mac)
        return _action("connect", mac, timeout=30)


def connect(mac: str) -> dict:
    with _action_lock:
        # Connecting by hand cancels a previous deliberate disconnect, so
        # auto-reconnect starts looking after this device again.
        _clear_optout(mac)
        _reconnect_state.pop(mac.upper(), None)
        return _action("connect", mac, timeout=30)


def disconnect(mac: str) -> dict:
    with _action_lock:
        # Remembered, because otherwise the reconnect loop would undo this within
        # the minute and "Disconnect" would look broken. Cleared by connecting or
        # pairing the device again.
        _set_optout(mac)
        return _action("disconnect", mac, timeout=20)


def forget(mac: str) -> dict:
    with _action_lock:
        _clear_optout(mac)
        _reconnect_state.pop(mac.upper(), None)
        return _action("remove", mac, timeout=20)


# ---------- auto-reconnect ----------
#
# BlueZ does not cover this. Trusting a device only makes the wall *accept* an
# incoming connection, and the [Policy] reconnect plugin only retries after an
# unexpected disconnect of an already-connected device. Neither covers the case that
# actually happens in a kitchen: the speaker was off, and now it is on.
#
# Whether the speaker or the wall initiates is up to the speaker's firmware, and
# plenty of them just sit and wait, so the wall has to reach out.


def _optouts() -> set[str]:
    return {m.upper() for m in preferences.load_prefs().get("bluetooth_optout", [])}


def _set_optout(mac: str) -> None:
    preferences.update_prefs(bluetooth_optout=sorted(_optouts() | {mac.upper()}))


def _clear_optout(mac: str) -> None:
    preferences.update_prefs(bluetooth_optout=sorted(_optouts() - {mac.upper()}))


def autoconnect_enabled() -> bool:
    # On by default: a wall speaker that needs a trip to a settings page every time
    # it is switched on is not much better than no speaker.
    return bool(preferences.load_prefs().get("bluetooth_autoconnect", True))


def set_autoconnect(enabled: bool) -> dict:
    preferences.update_prefs(bluetooth_autoconnect=bool(enabled))
    if enabled:
        # Don't make someone wait out a backoff they just re-enabled.
        _reconnect_state.clear()
    return {"ok": True, "enabled": bool(enabled)}


def reconnect_once(force: bool = False) -> list[dict]:
    """One pass: try to connect every trusted, disconnected device.

    Returns what it attempted, which is what makes this testable without a speaker.
    Skips devices the user deliberately disconnected, and devices still inside their
    backoff window.

    `force` ignores the backoff, and is what a person asking for a reconnect *now*
    gets. Without it the manual path was silently swallowed: the background loop had
    already tried and failed against a switched-off speaker, so a "try now" tap
    landed inside the backoff window and answered "attempted nothing" - which reads
    exactly like a broken button.
    """
    if not autoconnect_enabled():
        return []

    try:
        if not adapter()["powered"]:
            return []
        # Trusted, not connected. Deliberately NOT `paired`: this wall's speaker
        # pairs without bonding, so BlueZ reports Paired: no for exactly as long as
        # it is disconnected - which is precisely when a reconnect is wanted. Gating
        # on paired made this find nothing at all, every time. Trust is what
        # survives, and it is set by pair(), so it means "we set this up".
        candidates = [d for d in devices() if d["trusted"] and not d["connected"]]
    except BluetoothUnavailable:
        return []

    optouts = _optouts()
    attempted = []
    for device in candidates:
        mac = device["address"]
        if mac in optouts:
            continue

        state = _reconnect_state.setdefault(mac, {"failures": 0, "skip": 0})
        if force:
            # A person asking now outranks the backoff, and clears it so the
            # background loop resumes from a clean slate either way.
            state["failures"] = 0
            state["skip"] = 0
        elif state["skip"] > 0:
            state["skip"] -= 1
            continue

        with _action_lock:
            result = _action("connect", mac, timeout=30)
        if result["ok"]:
            _reconnect_state.pop(mac, None)
        else:
            # 1st failure skips 1 cycle, then 2, 4, 8... capped.
            state["skip"] = min(2 ** state["failures"], RECONNECT_MAX_BACKOFF_CYCLES)
            state["failures"] += 1
        attempted.append({"address": mac, "name": device["name"], **result})

    return attempted


def start_autoconnect() -> bool:
    """Start the reconnect loop. Called once at server startup.

    Idempotent, and never lets an exception escape: a wall with no adapter at all
    must still be able to start the server, and a background loop that dies takes
    auto-reconnect with it for the life of the process.
    """
    global _reconnect_thread
    if _reconnect_thread is not None and _reconnect_thread.is_alive():
        return False

    def loop():
        delay = RECONNECT_FIRST_PASS_SECONDS
        while True:
            time.sleep(delay)
            delay = RECONNECT_INTERVAL_SECONDS
            try:
                reconnect_once()
            except Exception:
                pass

    _reconnect_thread = threading.Thread(target=loop, daemon=True, name="bt-autoconnect")
    _reconnect_thread.start()
    return True


def set_powered(on: bool) -> dict:
    return _action_setting("power", on)


def set_discoverable(on: bool) -> dict:
    """Make the wall visible to other devices.

    Off by default and never left on: pairing a speaker only needs *us* to scan,
    so being discoverable is pure exposure - anything in range of the kitchen can
    see the wall and try to pair with it. The timeout is set alongside so that a
    forgotten toggle turns itself off.
    """
    if on:
        _run(["discoverable-timeout", str(SCAN_SECONDS * 12)], timeout=10)
    return _action_setting("discoverable", on)


def _action_setting(name: str, on: bool) -> dict:
    out = _run([name, "on" if on else "off"], timeout=15).lower()
    if "succeeded" in out or "new_settings" in out:
        return {"ok": True}
    return {"ok": False, "error": f"Could not turn {name} {'on' if on else 'off'}."}
