import datetime as dt

import requests.exceptions
from flask import Flask, jsonify, redirect, render_template, request, session
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from spotipy.exceptions import SpotifyException

from app import (
    air_service,
    alerts_service,
    browser_service,
    calendar_service,
    demo_data,
    groceries_service,
    preferences,
    recipes_service,
    spotify_service,
    version,
    weather_service,
)
from app.auth import google_auth
from app.auth.errors import classify
from app.config import DEMO_MODE, FLASK_SECRET_KEY

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


@app.context_processor
def inject_globals():
    # Lets every template render the demo-mode banner without each view
    # having to remember to pass the flag through.
    # `build` cache-busts the asset URLs, so a reload after a deploy is
    # guaranteed to fetch the new CSS rather than revalidate into the old one.
    return {"demo_mode": DEMO_MODE, "build": version.BUILD}


@app.errorhandler(calendar_service.DemoModeError)
def handle_demo_mode_error(e):
    return jsonify({"error": str(e)}), 403


@app.errorhandler(spotify_service.SpotifyForbidden)
def handle_spotify_forbidden(e):
    return jsonify({"error": str(e)}), 403


@app.errorhandler(spotify_service.SpotifyNotConfigured)
def handle_spotify_not_configured(e):
    return jsonify({"error": str(e)}), 503


@app.errorhandler(requests.exceptions.HTTPError)
def handle_requests_http_error(e):
    # spotify_service calls a couple of endpoints with plain `requests` rather
    # than through spotipy, so their failures aren't SpotifyExceptions and used
    # to fall through to Flask's HTML 500 page - which the client then tried to
    # parse as JSON, turning a clear API error into "Unexpected token '<'".
    status = e.response.status_code if e.response is not None else 502
    return jsonify({"error": f"Spotify returned {status}."}), status


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


@app.route("/api/version")
def api_version():
    """What build this process is running. The wall polls this and reloads itself
    when it changes - see app/version.py for why that's necessary."""
    return jsonify({"build": version.BUILD, "started_at": version.STARTED_AT})


@app.route("/api/calendar/<int:year>/<int:month>")
def api_calendar(year, month):
    return jsonify(calendar_service.get_month_grid(year, month))


@app.route("/api/calendar/week/<int:year>/<int:month>/<int:day>")
def api_calendar_week(year, month, day):
    return jsonify(calendar_service.get_week_grid(year, month, day))


@app.route("/api/calendar/day/<int:year>/<int:month>/<int:day>")
def api_calendar_day(year, month, day):
    return jsonify(calendar_service.get_day_grid(year, month, day))


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
    labels = demo_data.labels() if DEMO_MODE else preferences.load_labels()
    return jsonify(
        [
            {"email": email, "label": labels.get(email, email)}
            for email in calendar_service.signed_in_accounts()
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


@app.route("/today")
def today_page():
    return render_template("today.html")


@app.route("/recipes")
def recipes_page():
    return render_template("recipes.html")


@app.route("/api/recipes")
def api_recipes():
    return jsonify(recipes_service.get_recipes())


@app.route("/groceries")
def groceries_page():
    return render_template("groceries.html")


@app.route("/api/groceries")
def api_groceries():
    # Never raises - see groceries_service.get_groceries(). An unconfigured or
    # unreachable list is a state in the payload, not an error, so the Today page
    # can carry the block without risking the rest of the screen.
    return jsonify(groceries_service.get_groceries())


@app.route("/api/groceries/add", methods=["POST"])
def api_groceries_add():
    return jsonify(groceries_service.add_item((request.json or {}).get("text", "")))


@app.route("/api/groceries/<item_id>/done", methods=["POST"])
def api_groceries_done(item_id):
    return jsonify(groceries_service.set_done(item_id, bool((request.json or {}).get("done"))))


@app.route("/api/groceries/<item_id>/delete", methods=["POST"])
def api_groceries_delete(item_id):
    groceries_service.remove(item_id)
    return jsonify({"ok": True})


@app.route("/api/groceries/clear-done", methods=["POST"])
def api_groceries_clear_done():
    return jsonify({"ok": True, "cleared": groceries_service.clear_done()})


# get_groceries() swallows these, but every write path above raises them, and
# without handlers they would reach Flask's HTML 500 page - which the client then
# parses as JSON, turning a clear message into "Unexpected token '<'". Same bug
# the requests.HTTPError handler above exists for.
@app.errorhandler(groceries_service.GroceriesNotConfigured)
def handle_groceries_not_configured(e):
    return jsonify({"error": str(e), "configured": False}), 503


@app.errorhandler(groceries_service.GroceriesUnavailable)
def handle_groceries_unavailable(e):
    return jsonify({"error": str(e)}), 503


@app.route("/api/weather")
def api_weather():
    # get_weather() never raises - weather is decoration and must not be able to
    # take a page down - so there's no error handling to do here.
    return jsonify(weather_service.get_weather())


@app.route("/weather")
def weather_page():
    return render_template("weather.html")


@app.route("/api/weather/alerts")
def api_weather_alerts():
    # Same contract as get_weather(): never raises, so a National Weather Service
    # outage costs you the warnings panel and nothing else on the page.
    return jsonify(alerts_service.get_alerts())


@app.route("/api/weather/air")
def api_weather_air():
    # Air quality and pollen, from two different providers. Never raises, and the
    # halves fail independently - see app/air_service.py.
    return jsonify(air_service.get_air())


@app.route("/api/weather/radar")
def api_weather_radar():
    return jsonify(alerts_service.radar_station())


@app.route("/api/browser/probe")
def api_browser_probe():
    try:
        return jsonify(browser_service.probe(request.args.get("url", "")))
    except browser_service.UnsafeUrl as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    # 5000 is the real port everywhere - the kiosk launcher and the Google OAuth
    # redirect URI are both pinned to it. PORT exists so a second instance can be
    # brought up alongside it (the layout tests run a zero-accounts one); anything
    # needing sign-in on another port must also override GOOGLE_OAUTH_REDIRECT_URI.
    import os

    # Debug is OFF by default, and that matters here rather than being a nicety.
    # This binds 0.0.0.0 on a device sitting on a household LAN, and Flask's debug
    # mode serves the Werkzeug interactive debugger - a remote code execution
    # console, PIN-gated but exposed - plus a file-watching reloader that doubles
    # the process count on a Pi. Opt in explicitly when actually debugging.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("WALLCAL_DEBUG") == "1",
    )
