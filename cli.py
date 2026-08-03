import sys

from googleapiclient.discovery import build

from app import calendar_service
from app.auth import google_auth, spotify_auth


def sign_in_google():
    email = google_auth.sign_in()
    print(f"Signed in Google account: {email}")


def sign_in_spotify():
    identifier = spotify_auth.sign_in()
    print(f"Signed in Spotify account: {identifier}")


def test():
    print("Google accounts:")
    for email in google_auth.signed_in_accounts():
        creds = google_auth.get_credentials(email)
        service = build("calendar", "v3", credentials=creds)
        calendars = service.calendarList().list().execute().get("items", [])
        names = [c["summary"] for c in calendars]
        print(f"  {email}: {len(names)} calendars -> {names}")

    print("Spotify accounts:")
    for identifier in spotify_auth.signed_in_accounts():
        sp = spotify_auth.get_client(identifier)
        me = sp.current_user()
        print(f"  {identifier}: product={me.get('product')}, display_name={me.get('display_name')}")


def calendars():
    rows = calendar_service.list_all_calendars()
    print(f"{'account':<28}{'access_role':<12}{'summary':<30}calendar_id")
    for row in rows:
        print(
            f"{row['account']:<28}{row['access_role']:<12}"
            f"{(row['summary'] or ''):<30}{row['calendar_id']}"
        )
    print(
        "\nTo hide a calendar from the wall display, add its calendar_id to "
        "excluded_calendar_ids in data/calendar_prefs.json."
    )


COMMANDS = {
    "google": sign_in_google,
    "spotify": sign_in_spotify,
    "test": test,
    "calendars": calendars,
}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python cli.py [{'|'.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
