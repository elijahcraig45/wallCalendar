"""Device-level settings for a wall with no desktop: touchscreen calibration, the
on-screen keyboard, and putting the kiosk window back if it gets minimised.

Everything here talks to the *session* - labwc and squeekboard - from a systemd
system service that has none of a session's environment. See _session_env().
"""

import os
import re
import subprocess
import threading

from app import preferences
from app.config import PROJECT_ROOT

RC_TEMPLATE = PROJECT_ROOT / "deploy" / "labwc-rc.xml.template"
RC_PATH = os.path.expanduser("~/.config/labwc/rc.xml")

DEFAULT_OUTPUT = "HDMI-A-1"
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

# How long a freshly applied calibration stays on trial before reverting itself.
# A wrong matrix makes the panel unusable, and the only other way back is SSH, so
# the revert has to happen without anyone being able to tap anything.
CALIBRATION_TRIAL_SECONDS = 45

_revert_timer: threading.Timer | None = None
_revert_lock = threading.Lock()
# What to go back to if the trial is not confirmed. Held alongside the timer so an
# explicit "undo now" and the timeout take exactly the same path.
_revert_to: dict | None = None


class SystemActionFailed(RuntimeError):
    pass


def _session_env() -> dict:
    """The bits of a graphical session that wallcalendar.service does not inherit.

    The unit runs as User=calendar with nothing but HOME and USER, so busctl would
    look for a session bus that isn't in its environment and wlrctl would find no
    Wayland socket. Both live at well-known paths under /run/user/<uid>.
    """
    uid = os.getuid()
    runtime = f"/run/user/{uid}"
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": runtime,
        "WAYLAND_DISPLAY": "wayland-0",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
    }


def _run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, env=_session_env()
        )
    except FileNotFoundError as exc:
        raise SystemActionFailed(f"{args[0]} is not installed on this device.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemActionFailed(f"{args[0]} did not respond.") from exc


# ---------- on-screen keyboard ----------
#
# squeekboard shows itself when a text field takes focus, which is the normal path
# and needs nothing from us. This exists for the case that focus tracking cannot
# cover: a text box inside the /browser page's cross-origin iframe, where the page
# cannot see focus at all. A manual toggle is the only way to type into those.

_OSK = ["busctl", "--user", "--", "call", "sm.puri.OSK0", "/sm/puri/OSK0", "sm.puri.OSK0"]


def keyboard_visible() -> bool:
    result = _run(
        ["busctl", "--user", "get-property", "sm.puri.OSK0", "/sm/puri/OSK0",
         "sm.puri.OSK0", "Visible"]
    )
    return result.stdout.strip().endswith("true")


def set_keyboard_visible(visible: bool) -> dict:
    result = _run([*_OSK, "SetVisible", "b", "true" if visible else "false"])
    if result.returncode != 0:
        raise SystemActionFailed(
            "The on-screen keyboard is not running. (squeekboard is started by "
            "/usr/bin/sbtest at login, and only when a touchscreen is present.)"
        )
    return {"ok": True, "visible": visible}


def _kiosk_app_id() -> str | None:
    """Chromium's Wayland app_id, read from the compositor rather than assumed.

    It is derived from the URL in --app mode ("chrome-127.0.0.1__-Default"), so
    looking it up beats hardcoding a port. Matching has to be exact: wlrctl's
    app_id matcher does no globbing or prefixing, and passing "app_id:chrome-*" or
    even "app_id:chrome" just exits 1 without saying why - which is how this
    silently did nothing at first.
    """
    result = _run(["wlrctl", "toplevel", "list"])
    for line in result.stdout.splitlines():
        app_id, _, _title = line.partition(":")
        if app_id.startswith("chrome"):
            return app_id.strip()
    return None


def restore_kiosk() -> dict:
    """Un-minimise and refocus the kiosk window.

    The routine recovery is a watchdog in deploy/kiosk-launch.sh, not this - the
    page cannot detect a minimised window (Chromium does not mark the document
    hidden when labwc minimises it) and neither can wlrctl
    (`toplevel find state:minimized` always exits 1).

    This exists as the manual escape hatch: Flask listens on the LAN, so if the
    wall ever is blank, this endpoint can be hit from a phone on the same network
    without finding an SSH client. It is also how the watchdog's behaviour is
    exercised in one call when testing.

    Depends on the window keeping its foreign-toplevel handle, so the labwc window
    rule must not set skipTaskbar - see deploy/labwc-rc.xml.template.
    """
    app_id = _kiosk_app_id()
    if app_id is None:
        return {"ok": False, "error": "The kiosk window is not visible to the compositor."}
    # Maximize first: a minimised window cannot take focus, and maximizing is what
    # un-minimises it.
    _run(["wlrctl", "toplevel", "maximize", f"app_id:{app_id}"])
    result = _run(["wlrctl", "toplevel", "focus", f"app_id:{app_id}"])
    return {"ok": result.returncode == 0, "app_id": app_id}


# ---------- powering the panel off ----------
#
# The deep stage of sleep, and deliberately NOT done from the page.
#
# Brightness and the faint-clock stage are a CSS overlay the page owns, because they
# have to respond instantly and be adjustable while you look at them. Powering the
# panel off is different: whatever turns it back on has to work when there is
# nothing on screen to tap *on*. If waking depended on our JavaScript, a page that
# had crashed or been reloaded would leave a dark wall recoverable only over SSH -
# exactly the failure mode this feature is supposed to avoid.
#
# So it is swayidle plus wlopm, at the session level: swayidle listens to labwc's
# ext_idle_notifier_v1 and fires `resume` on *any* seat input, before the page is
# involved at all. Verified on the wall - idle 10s -> panel off, one pointer event ->
# back on, and wlopm leaves the mode alone (1920x1080@60 still current afterwards),
# so the window is never reconfigured and the page never reflows.
#
# One debugging note: `grim` fails outright while the output is powered off, so a
# screenshot cannot be used to check this state.

OUTPUT_NAME = "HDMI-A-1"


def _swayidle_running() -> bool:
    # Queries about the display are read by the shell on every page, so they answer
    # rather than raise - see display_power_state.
    try:
        return _run(["pgrep", "-x", "swayidle"]).returncode == 0
    except SystemActionFailed:
        return False


def stop_display_off() -> None:
    _run(["pkill", "-x", "swayidle"])


def apply_display_off(minutes: int) -> dict:
    """(Re)start swayidle with the configured timeout. 0 disables it.

    Restarted rather than reconfigured because swayidle takes its timeouts on the
    command line. Killing it first is what makes this idempotent - two swayidles
    would both fire and fight over the output.
    """
    stop_display_off()
    if not minutes:
        return {"ok": True, "enabled": False}

    try:
        subprocess.Popen(
            [
                "swayidle",
                "-w",
                "timeout",
                str(minutes * 60),
                f"wlopm --off {OUTPUT_NAME}",
                "resume",
                f"wlopm --on {OUTPUT_NAME}",
            ],
            env=_session_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Detached, so it outlives the request and is not killed with the
            # Flask worker that happened to start it.
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        raise SystemActionFailed(
            "Could not start swayidle, so the screen will not power off. "
            "(apt install swayidle wlopm)"
        ) from exc
    return {"ok": True, "enabled": True, "minutes": minutes}


def sync_display_off_from_prefs() -> dict:
    """Called at startup and whenever the setting changes, so prefs stay the single
    source of truth for it - the same arrangement as the calibration."""
    minutes = preferences.display_settings()["display_off_minutes"]
    try:
        return apply_display_off(minutes)
    except SystemActionFailed:
        return {"ok": False, "enabled": False}


def wake_display() -> dict:
    """Force the panel back on.

    swayidle's `resume` already covers a tap, so this is the escape hatch for the
    case it cannot cover: something went wrong and the wall is dark. Flask listens
    on the LAN, so it can be hit from a phone.
    """
    result = _run(["wlopm", "--on", OUTPUT_NAME])
    return {"ok": result.returncode == 0, "output": OUTPUT_NAME}


def display_power_state() -> str | None:
    """"on" / "off", or None when wlopm cannot say.

    Answers instead of raising, deliberately. The shell reads /api/system/display on
    every page, and a 503 there is logged by Chromium as a failed resource load on
    every single page load - which is both noise in the service log and a console
    error the layout tests (rightly) treat as a regression. Same rule the Spotify
    now-playing poll follows: a shell-wide poll degrades, it does not fail.
    """
    try:
        result = _run(["wlopm"])
    except SystemActionFailed:
        return None
    for line in result.stdout.splitlines():
        if line.startswith(OUTPUT_NAME):
            return line.split()[-1]
    return None


# ---------- touchscreen calibration ----------


def touch_devices() -> list[str]:
    """Names of devices libinput reports a touch capability for."""
    result = _run(["libinput", "list-devices"], timeout=15)
    names, current = [], None
    for line in result.stdout.splitlines():
        if line.startswith("Device:"):
            current = line.split(":", 1)[1].strip()
        elif "Capabilities:" in line and "touch" in line.split(":", 1)[1] and current:
            names.append(current)
            current = None
    return names


def _outputs() -> list[str]:
    result = _run(["wlr-randr"])
    return re.findall(r"^(\S+) \"", result.stdout, re.MULTILINE)


def calibration_state() -> dict:
    prefs = preferences.load_prefs()
    stored = prefs.get("touch_calibration")
    devices = touch_devices()
    outputs = _outputs()
    return {
        "matrix": list(stored) if stored else list(IDENTITY),
        "calibrated": bool(stored),
        "device": prefs.get("touch_device") or (devices[0] if devices else None),
        "devices": devices,
        "output": prefs.get("touch_output") or (outputs[0] if outputs else DEFAULT_OUTPUT),
        "outputs": outputs,
        "on_trial": _revert_timer is not None,
        "trial_seconds": CALIBRATION_TRIAL_SECONDS,
    }


def _solve_affine(samples: list[dict]) -> tuple[float, ...]:
    """Least-squares affine map from where taps *landed* to where they were aimed.

    Each sample is {"target": [x, y], "observed": [x, y]} in output-normalised
    coordinates. x and y are independent 3-parameter fits against
    [observed_x, observed_y, 1], so this is two small normal-equation solves
    rather than anything that would justify pulling in numpy.
    """
    if len(samples) < 3:
        raise SystemActionFailed("Calibration needs at least three points.")

    rows = [(s["observed"][0], s["observed"][1], 1.0) for s in samples]

    def fit(targets: list[float]) -> list[float]:
        # Normal equations: (A^T A) c = A^T b, with A^T A a symmetric 3x3.
        ata = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
        atb = [sum(r[i] * t for r, t in zip(rows, targets)) for i in range(3)]
        return _solve3(ata, atb)

    a, b, c = fit([s["target"][0] for s in samples])
    d, e, f = fit([s["target"][1] for s in samples])
    return (a, b, c, d, e, f)


def _solve3(m: list[list[float]], v: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting on a 3x3 system."""
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            # Collinear taps (someone tapped three points in a line) leave the
            # system singular. Refusing beats emitting a matrix that collapses
            # the whole panel onto one axis.
            raise SystemActionFailed("Those points are too close to a straight line.")
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(3):
            if r == col:
                continue
            factor = a[r][col] / a[col][col]
            for k in range(col, 4):
                a[r][k] -= factor * a[col][k]
    return [a[i][3] / a[i][i] for i in range(3)]


def _compose(correction: tuple[float, ...], base: tuple[float, ...]) -> tuple[float, ...]:
    """correction ∘ base, both 2x3 affines with an implicit [0 0 1] bottom row.

    Composed rather than replaced because the samples were collected *through* the
    matrix already in force: a tap reported at (x, y) has been transformed once
    already. Treating the fit as an absolute matrix would apply the existing
    correction twice, so a second calibration pass would overshoot further every
    time instead of converging.
    """
    a, b, c, d, e, f = correction
    p, q, r, s, t, u = base
    return (
        a * p + b * s,
        a * q + b * t,
        a * r + b * u + c,
        d * p + e * s,
        d * q + e * t,
        d * r + e * u + f,
    )


def _sanity_check(matrix: tuple[float, ...]) -> None:
    """Refuse a matrix that would make the panel unusable.

    The auto-revert is the real safety net, but it costs whoever is standing there
    45 seconds of a dead touchscreen. Obvious nonsense - a fit from mis-tapped or
    duplicated points - is cheaper to reject outright.
    """
    a, b, c, d, e, f = matrix
    if not all(abs(v) < 10 for v in matrix):
        raise SystemActionFailed("That calibration came out far off - please try again.")
    if not (0.5 < abs(a) < 2.0) or not (0.5 < abs(e) < 2.0):
        raise SystemActionFailed("That calibration would stretch the screen - please try again.")
    if abs(c) > 0.5 or abs(f) > 0.5:
        raise SystemActionFailed("That calibration would shift the screen off - please try again.")
    if abs(b) > 0.5 or abs(d) > 0.5:
        raise SystemActionFailed("That calibration came out skewed - please try again.")


def render_rc_xml(matrix: tuple[float, ...] | None, device: str, output: str) -> str:
    template = RC_TEMPLATE.read_text()
    if matrix and tuple(matrix) != IDENTITY:
        values = " ".join(f"{v:.6f}" for v in matrix)
        calibration = f"\n\t\t\t<calibrationMatrix>{values}</calibrationMatrix>"
    else:
        calibration = ""
    return template.format(touch_device=device, touch_output=output, calibration=calibration)


def _write_rc_and_reload(matrix: tuple[float, ...] | None, device: str, output: str) -> None:
    os.makedirs(os.path.dirname(RC_PATH), exist_ok=True)
    with open(RC_PATH, "w") as fh:
        fh.write(render_rc_xml(matrix, device, output))

    # SIGHUP is exactly what `labwc --reconfigure` does, and unlike the CLI it
    # needs no Wayland socket - which this service does not have.
    result = _run(["pkill", "-HUP", "-x", "labwc"])
    if result.returncode != 0:
        raise SystemActionFailed("labwc is not running, so the change could not be applied.")


def sync_rc_from_prefs() -> bool:
    """Make rc.xml agree with stored prefs. Called once at startup.

    This is what stops an *unconfirmed* trial calibration from becoming permanent.
    The 45-second revert lives in a threading.Timer, so a restart during the trial
    - a deploy, `systemctl restart`, a reboot - takes the timer with it and leaves
    the trial matrix in rc.xml while prefs still say the panel is uncalibrated.

    That is worse than a stray matrix: calibration_state() would then report
    identity from prefs while the panel actually runs the stray one, so the *next*
    calibration composes against the wrong base and overshoots - the exact failure
    _compose() exists to avoid.

    Prefs are the single source of truth; rc.xml is derived. Failures are swallowed
    on purpose: a wall with no touchscreen, or a dev machine with no labwc, must
    still be able to start the server.
    """
    try:
        state = calibration_state()
        if not state["device"]:
            return False
        matrix = tuple(state["matrix"]) if state["calibrated"] else None
        _write_rc_and_reload(matrix, state["device"], state["output"])
        return True
    except (SystemActionFailed, OSError):
        return False


def apply_calibration(samples: list[dict]) -> dict:
    """Fit, apply, and arm an automatic revert.

    Returns the new matrix. Nothing is persisted to prefs until confirm_calibration()
    is called, so a calibration that makes the screen worse is undone by simply not
    being able to confirm it.
    """
    state = calibration_state()
    if not state["device"]:
        raise SystemActionFailed("No touchscreen was detected.")

    correction = _solve_affine(samples)
    matrix = _compose(correction, tuple(state["matrix"]))
    _sanity_check(matrix)

    _write_rc_and_reload(matrix, state["device"], state["output"])
    _arm_revert(state)
    return {"ok": True, "matrix": list(matrix), "trial_seconds": CALIBRATION_TRIAL_SECONDS}


def _arm_revert(previous: dict) -> None:
    global _revert_timer, _revert_to
    with _revert_lock:
        if _revert_timer is not None:
            _revert_timer.cancel()
        _revert_to = previous
        _revert_timer = threading.Timer(CALIBRATION_TRIAL_SECONDS, revert_calibration)
        _revert_timer.daemon = True
        _revert_timer.start()


def _disarm() -> dict | None:
    global _revert_timer, _revert_to
    with _revert_lock:
        if _revert_timer is not None:
            _revert_timer.cancel()
        _revert_timer, previous = None, _revert_to
        _revert_to = None
    return previous


def revert_calibration() -> dict:
    """Put back whatever was in force before the trial started.

    Reached two ways - the trial timer firing, and an explicit "undo now" tap - and
    deliberately the same code for both, because the timer is the path that has to
    work when nobody can tap anything.
    """
    previous = _disarm()
    if previous is None:
        # Nothing on trial: already reverted, confirmed, or the process restarted.
        return {"ok": True, "reverted": False}
    stored = previous["matrix"] if previous["calibrated"] else None
    _write_rc_and_reload(
        tuple(stored) if stored else None, previous["device"], previous["output"]
    )
    return {"ok": True, "reverted": True}


def confirm_calibration(matrix: list[float]) -> dict:
    _disarm()
    state = calibration_state()
    preferences.update_prefs(
        touch_calibration=[float(v) for v in matrix],
        touch_device=state["device"],
        touch_output=state["output"],
    )
    return {"ok": True}


def reset_calibration() -> dict:
    """Back to an uncalibrated panel, applied and persisted immediately.

    Not put on trial like apply is: identity is the state the screen shipped in,
    so it is the thing you reach for when a calibration went wrong, and making it
    revert itself after 45 seconds would undo the rescue.
    """
    _disarm()
    state = calibration_state()
    _write_rc_and_reload(None, state["device"], state["output"])
    preferences.update_prefs(touch_calibration=None)
    return {"ok": True, "matrix": list(IDENTITY)}
