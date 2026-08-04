from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from googleapiclient.errors import HttpError

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

    return AccountError(email, "unknown", f"{email} may need reconnecting", exc)
