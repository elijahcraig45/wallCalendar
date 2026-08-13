"""The build the server is running, so the wall can notice it's out of date.

Pushing to main auto-deploys: the runner pulls and restarts the Flask service. But
the kiosk browser is never restarted - it has held the same page since boot - so
it kept rendering the CSS and JS it loaded days ago. The deploy looked successful
from every angle except the one that matters, which cost an hour of chasing a
theme change that had in fact shipped and simply wasn't on screen.

So the client polls this and reloads itself when the build changes.
"""

import subprocess
import time

from app.config import PROJECT_ROOT

# Watched for changes when there's no git metadata to read (a tarball deploy, or
# an editor writing straight into the tree).
_ASSET_DIRS = ("static", "templates")


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def _asset_mtime() -> int:
    latest = 0.0
    for name in _ASSET_DIRS:
        directory = PROJECT_ROOT / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
    return int(latest)


def _compute() -> str:
    """A git sha is the honest answer, but it doesn't move for uncommitted edits,
    so the asset mtime rides along. Both change on a deploy; only the mtime
    changes when working locally."""
    sha = _git_sha()
    mtime = _asset_mtime()
    return f"{sha}-{mtime}" if sha else str(mtime)


# Resolved once, at import. It has to describe the code this process is actually
# running - recomputing per request would report a deploy the running process
# hasn't picked up, and the client would reload into the same stale build forever.
BUILD = _compute()
STARTED_AT = time.time()
