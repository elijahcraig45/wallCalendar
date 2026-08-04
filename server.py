import datetime as dt

from flask import Flask, jsonify, redirect, render_template, request, session
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from spotipy.exceptions import SpotifyException

from app import calendar_service, preferences, spotify_service
from app.auth import google_auth
from app.auth.errors import classify
from app.config import FLASK_SECRET_KEY

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


@app.errorhandler(SpotifyException)
def handle_spotify_exception(e):
    message = e.msg or str(e)
    if e.http_status == 404 and "NO_ACTIVE_DEVICE" in (e.reason or ""):
        message = "No active Spotify device - open the device picker and pick one."
    return jsonify({"error": message}), e.http_status or 500


@app.errorhandler(HttpError)
def handle_google_http_error(e):
    return jsonify({"error": e.reason or str(e)}), e.status_code or 500


@app.errorhandler(GoogleAuthError)
def handle_google_auth_error(e):
    # Covers create/update/delete-event's unguarded get_credentials() call -
    # unlike the isolated kiosk-grid fetch path, a single user-initiated
    # action failing loudly here is correct, not something to swallow.
    err = classify("", e)
    status = 401 if err.kind == "needs_reauth" else 502
    return jsonify({"error": err.message}), status


@app.route("/")
def index():
    today = dt.date.today()
    return render_template("calendar.html", year=today.year, month=today.month)


@app.route("/api/calendar/<int:year>/<int:month>")
def api_calendar(year, month):
    return jsonify(calendar_service.get_month_grid(year, month))


@app.route("/api/calendar/week/<int:year>/<int:month>/<int:day>")
def api_calendar_week(year, month, day):
    return jsonify(calendar_service.get_week_grid(year, month, day))


@app.route("/api/calendar/agenda")
def api_calendar_agenda():
    from_str = request.args.get("from")
    from_date = dt.date.fromisoformat(from_str) if from_str else dt.date.today()
    num_days = int(request.args.get("days", 30))
    return jsonify(calendar_service.get_agenda(from_date, num_days))


@app.route("/api/calendar/refresh", methods=["POST"])
def api_calendar_refresh():
    # Bypasses the 5-minute cache TTL for a manual pull of latest events -
    # e.g. a change made directly in Google Calendar on someone's phone
    # wouldn't otherwise show up here until the cache naturally expired.
    calendar_service.invalidate_cache()
    return jsonify({"ok": True})


@app.route("/auth/google/start")
def google_auth_start():
    auth_url, state = google_auth.build_auth_url()
    session["google_oauth_state"] = state
    reauth_email = request.args.get("reauth")
    if reauth_email:
        session["google_reauth_email"] = reauth_email
    else:
        session.pop("google_reauth_email", None)
    return redirect(auth_url)


@app.route("/auth/google/callback")
def google_auth_callback():
    # Popped at the very top, before any early-return branch, so it can
    # never leak into a later unrelated sign-in (e.g. abandoning a
    # "Reconnect" attempt for one account, then adding a different one).
    expected_reauth = session.pop("google_reauth_email", None)

    if request.args.get("error"):
        return redirect(f"/accounts?error={request.args['error']}")

    expected_state = session.pop("google_oauth_state", None)
    if not expected_state or request.args.get("state") != expected_state:
        return redirect("/accounts?error=state_mismatch")

    try:
        email = google_auth.finish_auth(request.url, expected_state)
    except Exception:
        return redirect("/accounts?error=auth_failed")

    calendar_service.invalidate_cache()
    if expected_reauth and expected_reauth != email:
        return redirect(f"/accounts?signed_in={email}&mismatch={expected_reauth}")
    return redirect(f"/accounts?signed_in={email}")


@app.route("/accounts")
def accounts_page():
    return render_template("accounts.html")


@app.route("/api/calendar/accounts")
def api_calendar_accounts():
    labels = preferences.load_labels()
    return jsonify(
        [
            {"email": email, "label": labels.get(email, email)}
            for email in google_auth.signed_in_accounts()
        ]
    )


@app.route("/api/calendar/accounts/health")
def api_calendar_accounts_health():
    return jsonify(calendar_service.check_accounts_health())


@app.route("/api/calendar/accounts/<email>/label", methods=["POST"])
def api_calendar_account_label(email):
    preferences.set_account_label(email, request.json["label"])
    return jsonify({"ok": True})


@app.route("/api/calendar/accounts/<email>/remove", methods=["POST"])
def api_calendar_account_remove(email):
    google_auth.remove_account(email)
    calendar_service.invalidate_cache()
    return jsonify({"ok": True})


@app.route("/api/calendar/calendars")
def api_calendar_calendars():
    writable_only = request.args.get("writable_only") == "true"
    prefs = preferences.load_prefs()
    calendars, errors = calendar_service.list_all_calendars(writable_only=writable_only)
    return jsonify(
        {
            "calendars": calendars,
            "excluded_calendar_ids": prefs.get("excluded_calendar_ids", []),
            "errors": errors,
        }
    )


@app.route("/api/calendar/calendars/visibility", methods=["POST"])
def api_calendar_calendars_visibility():
    data = request.json
    preferences.set_calendar_excluded(data["calendar_id"], data["excluded"])
    calendar_service.invalidate_cache()
    return jsonify({"ok": True})


@app.route("/api/calendar/events", methods=["POST"])
def api_calendar_create_event():
    data = request.json
    result = calendar_service.create_event(
        account=data["account"],
        calendar_id=data["calendar_id"],
        time_zone=data["time_zone"],
        title=data["title"],
        location=data.get("location") or None,
        description=data.get("description") or None,
        all_day=data["all_day"],
        start=data["start"],
        end=data["end"],
        recurrence_freq=data.get("recurrence_freq", "none"),
        recurrence_until=data.get("recurrence_until") or None,
        guests=data.get("guests", []),
    )
    return jsonify({"ok": True, "event_id": result["id"]})


@app.route("/api/calendar/event")
def api_calendar_get_event():
    # Query params, not path segments - real calendar ids commonly contain
    # "#" (e.g. en.usa#holiday@group.v.calendar.google.com), which breaks
    # URL path parsing.
    result = calendar_service.get_event(
        account=request.args["account"],
        calendar_id=request.args["calendar_id"],
        event_id=request.args["event_id"],
    )
    return jsonify(result)


@app.route("/api/calendar/events/update", methods=["POST"])
def api_calendar_update_event():
    data = request.json
    result = calendar_service.update_event(
        account=data["account"],
        calendar_id=data["calendar_id"],
        event_id=data["event_id"],
        time_zone=data["time_zone"],
        title=data["title"],
        location=data.get("location") or None,
        description=data.get("description") or None,
        all_day=data["all_day"],
        start=data["start"],
        end=data["end"],
        recurrence_freq=data.get("recurrence_freq", "none"),
        recurrence_until=data.get("recurrence_until") or None,
        guests=data.get("guests", []),
    )
    return jsonify({"ok": True, "event_id": result["id"]})


@app.route("/api/calendar/events/delete", methods=["POST"])
def api_calendar_delete_event():
    data = request.json
    calendar_service.delete_event(
        account=data["account"],
        calendar_id=data["calendar_id"],
        event_id=data["event_id"],
        notify_guests=data.get("notify_guests", False),
    )
    return jsonify({"ok": True})


@app.route("/spotify")
def spotify_page():
    return render_template("spotify.html")


@app.route("/api/spotify/now-playing")
def api_spotify_now_playing():
    return jsonify(spotify_service.now_playing())


@app.route("/api/spotify/play", methods=["POST"])
def api_spotify_play():
    spotify_service.play()
    return jsonify({"ok": True})


@app.route("/api/spotify/pause", methods=["POST"])
def api_spotify_pause():
    spotify_service.pause()
    return jsonify({"ok": True})


@app.route("/api/spotify/next", methods=["POST"])
def api_spotify_next():
    spotify_service.next_track()
    return jsonify({"ok": True})


@app.route("/api/spotify/previous", methods=["POST"])
def api_spotify_previous():
    spotify_service.previous_track()
    return jsonify({"ok": True})


@app.route("/api/spotify/search")
def api_spotify_search():
    return jsonify(spotify_service.search(request.args.get("q", "")))


@app.route("/api/spotify/recently-played")
def api_spotify_recently_played():
    return jsonify(spotify_service.recently_played())


@app.route("/api/spotify/playlists")
def api_spotify_playlists():
    return jsonify(spotify_service.playlists())


@app.route("/api/spotify/play-uri", methods=["POST"])
def api_spotify_play_uri():
    spotify_service.play_uri(request.json["uri"])
    return jsonify({"ok": True})


@app.route("/api/spotify/play-context", methods=["POST"])
def api_spotify_play_context():
    spotify_service.play_context(request.json["uri"])
    return jsonify({"ok": True})


@app.route("/api/spotify/playlist/<playlist_id>/tracks")
def api_spotify_playlist_tracks(playlist_id):
    return jsonify(spotify_service.playlist_tracks(playlist_id))


@app.route("/api/spotify/artist/<artist_id>/albums")
def api_spotify_artist_albums(artist_id):
    return jsonify(spotify_service.artist_albums(artist_id))


@app.route("/api/spotify/play-context-at", methods=["POST"])
def api_spotify_play_context_at():
    data = request.json
    spotify_service.play_context_at(data["context_uri"], data["track_uri"])
    return jsonify({"ok": True})


@app.route("/api/spotify/shuffle", methods=["POST"])
def api_spotify_shuffle():
    spotify_service.set_shuffle(request.json["state"])
    return jsonify({"ok": True})


@app.route("/api/spotify/seek", methods=["POST"])
def api_spotify_seek():
    spotify_service.seek(request.json["position_ms"])
    return jsonify({"ok": True})


@app.route("/api/spotify/volume", methods=["POST"])
def api_spotify_volume():
    spotify_service.set_volume(request.json["volume_percent"])
    return jsonify({"ok": True})


@app.route("/api/spotify/repeat", methods=["POST"])
def api_spotify_repeat():
    spotify_service.set_repeat(request.json["state"])
    return jsonify({"ok": True})


@app.route("/api/spotify/queue")
def api_spotify_queue():
    return jsonify(spotify_service.queue())


@app.route("/api/spotify/liked-songs")
def api_spotify_liked_songs():
    return jsonify(spotify_service.liked_songs())


@app.route("/api/spotify/album/<album_id>/tracks")
def api_spotify_album_tracks(album_id):
    return jsonify(spotify_service.album_tracks(album_id))


@app.route("/api/spotify/play-uris", methods=["POST"])
def api_spotify_play_uris():
    data = request.json
    spotify_service.play_uris(data["uris"], data.get("offset_uri"))
    return jsonify({"ok": True})


@app.route("/api/spotify/token")
def api_spotify_token():
    # Handed directly to the Web Playback SDK, which runs client-side and
    # manages its own auth header - this is the one endpoint that exposes
    # a real bearer token to the browser, acceptable since this only ever
    # serves the household's own kiosk on the local network.
    return jsonify({"access_token": spotify_service.get_access_token()})


@app.route("/api/spotify/devices")
def api_spotify_devices():
    return jsonify(spotify_service.devices())


@app.route("/api/spotify/transfer", methods=["POST"])
def api_spotify_transfer():
    data = request.json
    spotify_service.transfer_playback(data["device_id"], data.get("play", True))
    return jsonify({"ok": True})


@app.route("/browser")
def browser_page():
    return render_template("browser.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
