"""Framing probe for the in-app browser.

The kiosk browser runs with `--kiosk`: no address bar, no back button, no tabs.
The old Web page did `window.location.href = url`, which navigated the whole
kiosk away from the app - and with no chrome there was no way back to the
calendar short of a reboot. So pages are framed instead, with the rail still on
screen.

Plenty of sites refuse to be framed (`X-Frame-Options`, or CSP
`frame-ancestors`), and a browser gives the page no way to detect that - it just
renders an empty box. Asking the server first turns "mysteriously blank" into a
sentence explaining what happened.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import requests

TIMEOUT_SECONDS = 6
# Presenting as a real browser matters: some sites serve different framing
# headers (or a bot wall) to unknown agents, which would make the probe disagree
# with what the kiosk actually gets.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class UnsafeUrl(ValueError):
    """The URL isn't something this endpoint will fetch on the caller's behalf."""


def normalize(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise UnsafeUrl("Enter an address first.")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _assert_public(url: str) -> None:
    """Refuses loopback, link-local and private addresses.

    This endpoint fetches a URL the caller supplies, from inside the house - the
    textbook shape of an SSRF hole. The wall itself is on the LAN alongside the
    Pi's own admin surfaces, so "it's only on the local network" is the reason to
    check, not a reason to skip it.
    """
    host = urlparse(url).hostname
    if not host:
        raise UnsafeUrl("That doesn't look like a web address.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise UnsafeUrl(f"Couldn't find {host}.") from None

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise UnsafeUrl("Only public websites can be opened here.")


def _frame_refusal(headers) -> str | None:
    """Why this response can't be framed, or None if it can be."""
    xfo = (headers.get("X-Frame-Options") or "").strip().lower()
    if xfo in ("deny", "sameorigin") or xfo.startswith("allow-from"):
        return "blocks being embedded"

    csp = (headers.get("Content-Security-Policy") or "").lower()
    for directive in csp.split(";"):
        directive = directive.strip()
        if not directive.startswith("frame-ancestors"):
            continue
        allowed = directive[len("frame-ancestors"):].split()
        # 'none' is an outright refusal; anything else is a whitelist that this
        # wall is not on (it would have to name our origin, which is a private
        # address no public site knows about).
        if "*" not in allowed:
            return "blocks being embedded"
    return None


def probe(raw_url: str) -> dict:
    """Returns {url, frameable, reason} - never raises for a network problem, so
    the Web page can explain the failure instead of showing a blank frame."""
    url = normalize(raw_url)
    _assert_public(url)

    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
            # Only the headers are needed. HEAD would be cheaper but plenty of
            # sites answer it with 405 or omit the framing headers entirely, so
            # this issues a GET and hangs up once the headers are in.
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        return {"url": url, "frameable": False, "reason": f"Couldn't load that page ({type(exc).__name__})."}

    try:
        # A redirect can land somewhere else entirely - re-check the final host
        # so a public URL can't be used to bounce the probe onto the LAN.
        final_url = resp.url
        _assert_public(final_url)

        if resp.status_code >= 400:
            return {"url": final_url, "frameable": False, "reason": f"That page returned an error ({resp.status_code})."}

        refusal = _frame_refusal(resp.headers)
        if refusal:
            return {"url": final_url, "frameable": False, "reason": f"This site {refusal}."}

        return {"url": final_url, "frameable": True, "reason": None}
    finally:
        resp.close()
