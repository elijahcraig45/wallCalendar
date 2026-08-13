import httplib2
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from googleapiclient.errors import HttpError

# What a fetch against one account can raise. Wider than it looks: the auth layer
# wraps network trouble in TransportError, but googleapiclient's own calls go
# through httplib2, whose ServerNotFoundError (plain DNS failure - i.e. the wifi
# dropped) is not an OSError, while socket timeouts and TLS errors are. Missing
# either meant a wifi blip escaped as a 500 and the wall rendered no calendar at
# all rather than a stale one.
ACCOUNT_FETCH_ERRORS = (
    GoogleAuthError,
    HttpError,
    ValueError,
    OSError,
    httplib2.HttpLib2Error,
)

# Not GoogleAuthError.retryable: verified against the library source that
# TransportError (the canonical "just a network blip" case) is raised with
# `retryable` unset (defaults False), so it can't be the transient/permanent
# discriminator - it would misclassify exactly the case it's meant to catch.
_REAUTH_MARKERS = ("invalid_grant", "unauthorized_client")


class AccountError(Exception):
    def __init__(self, email: str, kind: str, message: str, cause: Exception):
        # kind: "needs_reauth" | "transient" | "unknown"
        super().__init__(message)
        self.email = email
        self.kind = kind
        self.message = message
        self.cause = cause

    def to_dict(self) -> dict:
        return {"account": self.email, "kind": self.kind, "message": self.message}


def classify(email: str, exc: Exception) -> AccountError:
    if isinstance(exc, RefreshError):
        if any(marker in str(exc) for marker in _REAUTH_MARKERS):
            return AccountError(
                email, "needs_reauth", f"{email} needs to be reconnected", exc
            )
        return AccountError(
            email, "transient", f"Couldn't refresh credentials for {email}", exc
        )

    if isinstance(exc, TransportError):
        return AccountError(email, "transient", f"Couldn't reach Google for {email}", exc)

    if isinstance(exc, HttpError):
        status = exc.status_code or 0
        if status in (401, 403):
            return AccountError(
                email, "needs_reauth", f"{email} needs to be reconnected", exc
            )
        if status >= 500 or status == 429:
            return AccountError(
                email, "transient", f"Google Calendar is temporarily unavailable for {email}", exc
            )
        return AccountError(email, "unknown", f"{email} may need reconnecting", exc)

    if isinstance(exc, GoogleAuthError):
        return AccountError(email, "unknown", f"{email} may need reconnecting", exc)

    # Network-shaped failures are transient by definition and say nothing about
    # the credential - telling someone to reconnect their account because the
    # wifi dropped sends them to fix the wrong thing.
    if isinstance(exc, (OSError, httplib2.HttpLib2Error)):
        return AccountError(email, "transient", "Can't reach Google - network problem", exc)

    return AccountError(email, "unknown", f"{email} may need reconnecting", exc)
