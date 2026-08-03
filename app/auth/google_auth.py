from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import GOOGLE_CLIENT_SECRET_FILE, GOOGLE_SCOPES
from app.token_store import list_accounts, load_token, save_token

PROVIDER = "google"


def _creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def _dict_to_creds(data: dict) -> Credentials:
    return Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )


def sign_in() -> str:
    """Opens a browser for the interactive OAuth flow. Whoever signs in there
    is whoever gets saved - there's no pre-named account list. Returns their
    email."""
    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CLIENT_SECRET_FILE), scopes=GOOGLE_SCOPES
    )
    creds = flow.run_local_server(port=0)

    oauth2 = build("oauth2", "v2", credentials=creds)
    email = oauth2.userinfo().get().execute()["email"]

    save_token(PROVIDER, email, _creds_to_dict(creds))
    return email


def get_credentials(email: str) -> Credentials:
    data = load_token(PROVIDER, email)
    if data is None:
        raise ValueError(f"No saved Google token for {email}. Run sign_in() first.")

    creds = _dict_to_creds(data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(PROVIDER, email, _creds_to_dict(creds))
    return creds


def signed_in_accounts() -> list[str]:
    return list_accounts(PROVIDER)
