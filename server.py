import datetime as dt

from flask import Flask, jsonify, render_template, request
from spotipy.exceptions import SpotifyException

from app import calendar_service, spotify_service

app = Flask(__name__)


@app.errorhandler(SpotifyException)
def handle_spotify_exception(e):
    message = e.msg or str(e)
    if e.http_status == 404 and "NO_ACTIVE_DEVICE" in (e.reason or ""):
        message = "No active Spotify device - open the device picker and pick one."
    return jsonify({"error": message}), e.http_status or 500


@app.route("/")
def index():
    today = dt.date.today()
    return render_template("calendar.html", year=today.year, month=today.month)


@app.route("/api/calendar/<int:year>/<int:month>")
def api_calendar(year, month):
    return jsonify(calendar_service.get_month_grid(year, month))


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
