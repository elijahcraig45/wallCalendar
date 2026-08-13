const albumArt = document.getElementById("album-art");
const backdropBlur = document.getElementById("backdrop-blur");
const trackTitle = document.getElementById("track-title");
const trackArtist = document.getElementById("track-artist");
const playPauseBtn = document.getElementById("btn-play-pause");
const shuffleBtn = document.getElementById("btn-shuffle");
const repeatBtn = document.getElementById("btn-repeat");
const iconPlay = document.getElementById("icon-play");
const iconPause = document.getElementById("icon-pause");
const iconRepeatAll = document.getElementById("icon-repeat-all");
const iconRepeatOne = document.getElementById("icon-repeat-one");
const progressContainer = document.getElementById("progress-container");
const progressBar = document.getElementById("progress-bar");
const progressFill = document.getElementById("progress-fill");
const timeElapsed = document.getElementById("time-elapsed");
const timeDuration = document.getElementById("time-duration");
const volumeRow = document.getElementById("volume-row");
const volumeSlider = document.getElementById("volume-slider");

const deviceCurrentName = document.getElementById("device-current-name");

let state = { progressMs: 0, durationMs: 0, isPlaying: false, lastUpdate: Date.now() };

// While actively dragging the seek bar or volume slider, an in-flight poll
// or the SDK's player_state_changed push shouldn't yank the control back to
// the pre-drag server value - both suppress overwriting their piece of
// `state`/the slider until this timestamp passes.
let suppressProgressUntil = 0;
let suppressVolumeUntil = 0;

function formatTime(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function renderProgress() {
  let elapsed = state.progressMs;
  if (state.isPlaying) {
    elapsed += Date.now() - state.lastUpdate;
  }
  elapsed = Math.min(elapsed, state.durationMs);
  const pct = state.durationMs ? (elapsed / state.durationMs) * 100 : 0;
  progressFill.style.width = `${pct}%`;
  timeElapsed.textContent = formatTime(elapsed);
  timeDuration.textContent = formatTime(state.durationMs);
}

function updateRepeatButton(repeatState) {
  repeatBtn.classList.toggle("active", repeatState !== "off");
  iconRepeatOne.classList.toggle("hidden", repeatState !== "track");
  iconRepeatAll.classList.toggle("hidden", repeatState === "track");
}

/* Driven by the shell's shared poller (see nav.js), not its own fetch loop -
   the rail chip and this pane render the same payload. */
function renderNowPlaying(data) {
  if (!data) {
    trackTitle.textContent = "Nothing playing";
    trackArtist.textContent = "";
    albumArt.classList.add("hidden");
    backdropBlur.style.backgroundImage = "none";
    state = { progressMs: 0, durationMs: 0, isPlaying: false, lastUpdate: Date.now() };
    iconPlay.classList.remove("hidden");
    iconPause.classList.add("hidden");
    shuffleBtn.classList.remove("active");
    updateRepeatButton("off");
    volumeRow.classList.add("hidden");
    deviceCurrentName.textContent = "Pick a speaker";
    renderProgress();
    return;
  }

  deviceCurrentName.textContent = data.device_name || "Pick a speaker";

  trackTitle.textContent = data.track;
  trackArtist.textContent = data.artist;

  // A local seek drag/tap already set state.progressMs/lastUpdate optimistically -
  // don't let a poll that lands within the suppression window stomp on it.
  if (Date.now() >= suppressProgressUntil) {
    state = {
      progressMs: data.progress_ms || 0,
      durationMs: data.duration_ms || 0,
      isPlaying: data.is_playing,
      lastUpdate: Date.now(),
    };
  } else {
    state.isPlaying = data.is_playing;
  }

  iconPlay.classList.toggle("hidden", state.isPlaying);
  iconPause.classList.toggle("hidden", !state.isPlaying);
  shuffleBtn.classList.toggle("active", !!data.shuffle_state);
  updateRepeatButton(data.repeat_state || "off");

  if (data.supports_volume === false) {
    volumeRow.classList.add("hidden");
  } else {
    volumeRow.classList.remove("hidden");
    if (Date.now() >= suppressVolumeUntil && data.volume_percent != null) {
      volumeSlider.value = data.volume_percent;
    }
  }

  if (data.album_art) {
    albumArt.src = data.album_art;
    albumArt.classList.remove("hidden");
    backdropBlur.style.backgroundImage = `url(${data.album_art})`;
  } else {
    albumArt.classList.add("hidden");
    backdropBlur.style.backgroundImage = "none";
  }

  renderProgress();
}

onNowPlaying(renderNowPlaying);

async function post(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    let message = "Something went wrong";
    try {
      const data = await resp.json();
      message = data.error || message;
    } catch (e) {
      // response body wasn't JSON - keep the generic message
    }
    showToast(message);
    return false;
  }

  setTimeout(refreshNowPlaying, 300);
  return true;
}

playPauseBtn.addEventListener("click", () => post(state.isPlaying ? "/api/spotify/pause" : "/api/spotify/play"));
document.getElementById("btn-next").addEventListener("click", () => post("/api/spotify/next"));
document.getElementById("btn-previous").addEventListener("click", () => post("/api/spotify/previous"));
shuffleBtn.addEventListener("click", () =>
  post("/api/spotify/shuffle", { state: !shuffleBtn.classList.contains("active") })
);

const NEXT_REPEAT_STATE = { off: "context", context: "track", track: "off" };
repeatBtn.addEventListener("click", () => {
  const current = repeatBtn.classList.contains("active")
    ? (iconRepeatOne.classList.contains("hidden") ? "context" : "track")
    : "off";
  const next = NEXT_REPEAT_STATE[current];
  updateRepeatButton(next); // optimistic - no drift risk like progress/volume
  post("/api/spotify/repeat", { state: next });
});

// ---------- seek/scrub ----------

let isScrubbing = false;

function seekFractionFromEvent(e) {
  const rect = progressBar.getBoundingClientRect();
  const frac = (e.clientX - rect.left) / rect.width;
  return Math.min(1, Math.max(0, frac));
}

progressContainer.addEventListener("pointerdown", (e) => {
  isScrubbing = true;
  const positionMs = seekFractionFromEvent(e) * state.durationMs;
  state.progressMs = positionMs;
  state.lastUpdate = Date.now();
  renderProgress();
});

progressContainer.addEventListener("pointermove", (e) => {
  if (!isScrubbing) return;
  const positionMs = seekFractionFromEvent(e) * state.durationMs;
  state.progressMs = positionMs;
  state.lastUpdate = Date.now();
  renderProgress();
});

progressContainer.addEventListener("pointerup", (e) => {
  if (!isScrubbing) return;
  isScrubbing = false;
  const positionMs = seekFractionFromEvent(e) * state.durationMs;
  state.progressMs = positionMs;
  state.lastUpdate = Date.now();
  renderProgress();
  suppressProgressUntil = Date.now() + 1500;
  post("/api/spotify/seek", { position_ms: Math.round(positionMs) });
});

// ---------- volume ----------

let volumeDebounce = null;

volumeSlider.addEventListener("input", () => {
  suppressVolumeUntil = Date.now() + 1500;
  clearTimeout(volumeDebounce);
  volumeDebounce = setTimeout(() => {
    post("/api/spotify/volume", { volume_percent: parseInt(volumeSlider.value, 10) });
  }, 200);
});

volumeSlider.addEventListener("change", () => {
  clearTimeout(volumeDebounce);
  post("/api/spotify/volume", { volume_percent: parseInt(volumeSlider.value, 10) });
});

// ---------- queue ----------

const queuePanel = initPane("queue-overlay", "queue-close");
const queueTracksEl = document.getElementById("queue-tracks");

document.getElementById("queue-toggle").addEventListener("click", async () => {
  queueTracksEl.innerHTML = '<li class="playlist-loading">Loading...</li>';
  queuePanel.open();

  const resp = await fetch("/api/spotify/queue");
  const data = await resp.json();

  queueTracksEl.innerHTML = "";
  if (data.current) {
    const li = document.createElement("li");
    // Its own class, not a borrowed `playlist-loading`: reusing the loading
    // style for a permanent row meant "is this list still loading?" had no
    // reliable answer, for a reader or a test.
    li.className = "queue-current";
    li.textContent = `Now playing: ${data.current.name}`;
    queueTracksEl.appendChild(li);
  }
  if (data.upcoming.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Nothing queued";
    queueTracksEl.appendChild(li);
  } else {
    data.upcoming.forEach((t) => {
      queueTracksEl.appendChild(renderTrackRow(t, () => {}));
    });
  }
});

// The now-playing pane is always on screen, so there's no mini-player to expand
// and nothing to collapse - the shell's rail chip covers the other pages.
setInterval(renderProgress, 500);

/* ---------- browse pane navigation ----------
   Detail views open beside the now-playing pane instead of as bottom sheets over
   it. initPane keeps initPanel's {open, close} shape, so every call site that
   used to drive a sheet drives a pane view unchanged - and a small stack means
   Back walks artist -> album -> home rather than always dumping you home. */

const browseBack = document.getElementById("browse-back");
const browseViews = [...document.querySelectorAll(".browse-view")];

const HOME_VIEW = "browse-home";
let activeView = HOME_VIEW;
const viewStack = [];

function showView(id) {
  activeView = id;
  browseViews.forEach((view) => view.classList.toggle("hidden", view.id !== id));
  browseBack.classList.toggle("hidden", id === HOME_VIEW);
  document.getElementById("browse-body").scrollTop = 0;
}

function initPane(viewId, closeId) {
  const pane = {
    open() {
      if (activeView !== viewId) viewStack.push(activeView);
      showView(viewId);
    },
    close() {
      showView(viewStack.pop() || HOME_VIEW);
    },
  };
  // Same responsibility initPanel had: the view's own close button dismisses it.
  const closeBtn = document.getElementById(closeId);
  if (closeBtn) closeBtn.addEventListener("click", pane.close);
  return pane;
}

browseBack.addEventListener("click", () => showView(viewStack.pop() || HOME_VIEW));

// ---------- browse tiles ----------

function renderTiles(container, items, onTap, extraClass) {
  container.innerHTML = "";
  items.forEach((item) => {
    const tile = document.createElement("div");
    tile.className = extraClass ? `tile ${extraClass}` : "tile";

    const img = document.createElement("img");
    img.src = item.image || "";
    img.alt = "";
    tile.appendChild(img);

    const label = document.createElement("div");
    label.className = "tile-label";
    label.textContent = item.name;
    tile.appendChild(label);

    tile.addEventListener("click", () => onTap(item));
    container.appendChild(tile);
  });
}

function renderQuickTiles(container, items, onTap) {
  container.innerHTML = "";
  items.forEach((item) => {
    const tile = document.createElement("div");
    tile.className = "quick-tile";

    const img = document.createElement("img");
    img.src = item.image || "";
    img.alt = "";
    tile.appendChild(img);

    const label = document.createElement("div");
    label.className = "quick-tile-label";
    label.textContent = item.name;
    tile.appendChild(label);

    tile.addEventListener("click", () => onTap(item));
    container.appendChild(tile);
  });
}

async function loadQuickAccess() {
  const resp = await fetch("/api/spotify/recently-played");
  const tracks = await resp.json();
  renderQuickTiles(
    document.getElementById("quick-access-grid"),
    tracks.slice(0, 8),
    (item) => post("/api/spotify/play-uri", { uri: item.uri })
  );
}

const LIKED_SONGS_ICON =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' fill='%231c1f26'/%3E%3Cpath fill='%231DB954' d='M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z'/%3E%3C/svg%3E";

function shuffleArray(items) {
  const result = items.slice();
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

function openLikedSongsDetail() {
  // Liked Songs has no context_uri the way playlists/albums do, so playback
  // goes through play-uris with the fetched track list directly - and
  // set_shuffle has no effect on uris-based playback, so "Shuffle" here is
  // a real client-side reorder of that list, not a server-side flag.
  let cachedTracks = [];
  openTrackListOverlay({
    title: "Liked Songs",
    image: LIKED_SONGS_ICON,
    fetchTracks: async () => {
      cachedTracks = await fetchJson("/api/spotify/liked-songs");
      return cachedTracks;
    },
    onPlayAll: () => post("/api/spotify/play-uris", { uris: cachedTracks.map((t) => t.uri) }),
    onShuffle: () =>
      post("/api/spotify/play-uris", { uris: shuffleArray(cachedTracks).map((t) => t.uri) }),
    onTrackTap: (t) =>
      post("/api/spotify/play-uris", {
        uris: cachedTracks.map((tr) => tr.uri),
        offset_uri: t.uri,
      }),
  });
}

async function loadPlaylists() {
  const resp = await fetch("/api/spotify/playlists");
  const lists = await resp.json();
  const withLiked = [{ name: "Liked Songs", image: LIKED_SONGS_ICON, __liked: true }, ...lists];
  renderTiles(
    document.getElementById("playlists-strip"),
    withLiked,
    (item) => (item.__liked ? openLikedSongsDetail() : openPlaylistDetail(item))
  );
}

loadQuickAccess();
loadPlaylists();

// ---------- persistent search ----------

const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const homeDefaultContent = document.getElementById("home-default-content");
let searchDebounce = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  const query = searchInput.value.trim();

  // The search field is in the pane's persistent header, so it can be typed into
  // while a playlist/artist/queue view is open - and results render inside the
  // home view. Without this, typing appeared to do nothing at all.
  viewStack.length = 0;
  showView(HOME_VIEW);

  if (!query) {
    searchResults.classList.add("hidden");
    homeDefaultContent.classList.remove("hidden");
    searchResults.innerHTML = "";
    return;
  }

  searchDebounce = setTimeout(async () => {
    const resp = await fetch(`/api/spotify/search?q=${encodeURIComponent(query)}`);
    const data = await resp.json();

    homeDefaultContent.classList.add("hidden");
    searchResults.classList.remove("hidden");
    searchResults.innerHTML = "";

    if (data.artists.length > 0) {
      const strip = addSearchGroup("Artists", "tile-grid");
      renderTiles(strip, data.artists, (item) => openArtistDetail(item), "artist-tile");
    }

    if (data.albums.length > 0) {
      const strip = addSearchGroup("Albums", "tile-grid");
      renderTiles(strip, data.albums, (item) => openAlbumDetail(item));
    }

    if (data.tracks.length > 0) {
      const list = addSearchGroup("Songs", "search-track-list", true);
      data.tracks.forEach((t) => {
        const li = document.createElement("li");

        const img = document.createElement("img");
        img.src = t.image || "";
        img.alt = "";
        li.appendChild(img);

        const text = document.createElement("div");
        text.className = "result-text";
        const title = document.createElement("span");
        title.className = "result-title";
        title.textContent = t.name;
        const artist = document.createElement("span");
        artist.className = "result-artist";
        artist.textContent = t.artist;
        text.appendChild(title);
        text.appendChild(artist);
        li.appendChild(text);

        li.addEventListener("click", () => post("/api/spotify/play-uri", { uri: t.uri }));

        list.appendChild(li);
      });
    }

    if (!data.tracks.length && !data.artists.length && !data.albums.length) {
      searchResults.innerHTML = '<p style="padding:16px;color:var(--text-dim)">No results</p>';
    }
  }, 300);
});

function addSearchGroup(title, contentClass, isList) {
  const section = document.createElement("div");
  section.className = contentClass === "search-track-list" ? "search-group" : "search-group tile-section";

  const h3 = document.createElement("h3");
  h3.textContent = title;
  section.appendChild(h3);

  const content = document.createElement(isList ? "ul" : "div");
  content.className = contentClass;
  section.appendChild(content);

  searchResults.appendChild(section);
  return content;
}

// ---------- Web Playback SDK ----------
// Registers this page itself as a Spotify Connect device, routing audio
// through the Pi's onboard speakers by default.

let sdkDeviceId = null;
// Set when this display has failed to become a playback target at all. The
// reasons are varied and not reliably reported (missing Widevine surfaces as an
// uncaught "No supported keysystem was found", a free account as account_error,
// no SDK script at all as nothing happening), so rather than trying to classify
// the failure this just notices that no device id ever arrived.
let sdkUnavailable = false;

setTimeout(() => {
  if (!sdkDeviceId) sdkUnavailable = true;
}, 8000);

window.onSpotifyWebPlaybackSDKReady = () => {
  const player = new Spotify.Player({
    name: "Wall Calendar",
    getOAuthToken: (cb) => {
      fetch("/api/spotify/token")
        .then((r) => r.json())
        .then((data) => cb(data.access_token));
    },
    volume: 0.8,
  });

  player.addListener("ready", ({ device_id }) => {
    sdkDeviceId = device_id;
    // Make this the default target without starting playback unprompted.
    fetch("/api/spotify/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id, play: false }),
    });
  });

  // Push-based update - much snappier than waiting for the next 5s poll
  // when the action happened on this device.
  player.addListener("player_state_changed", () => refreshNowPlaying());

  player.connect();
};

// ---------- device picker ----------

const deviceToggle = document.getElementById("device-toggle");
const devicePanel = initPane("device-overlay", "device-close");
const deviceList = document.getElementById("device-list");

const SPEAKER_ICON =
  '<svg class="device-icon" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>';

async function loadDevices() {
  const resp = await fetch("/api/spotify/devices");
  const devices = await resp.json();
  deviceList.innerHTML = "";

  // Say so plainly rather than leaving someone tapping a display that silently
  // isn't a speaker. Playing through the browser needs DRM support and a Premium
  // account; a Spotify Connect target on the Pi needs neither.
  if (sdkUnavailable) {
    const note = document.createElement("li");
    note.className = "device-note";
    note.textContent =
      "This display can't play audio itself. Pick another speaker below, " +
      "or set up Spotify Connect on the Pi (see deploy/librespot-setup.sh).";
    deviceList.appendChild(note);
  }

  if (devices.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No devices found";
    deviceList.appendChild(li);
    return;
  }

  devices.forEach((d) => {
    const li = document.createElement("li");
    if (d.is_active) li.classList.add("active");
    li.innerHTML = SPEAKER_ICON;

    const name = document.createElement("span");
    name.className = "device-name";
    name.textContent = d.id === sdkDeviceId ? `${d.name} (this display)` : d.name;
    li.appendChild(name);

    li.addEventListener("click", async () => {
      await fetch("/api/spotify/transfer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: d.id, play: true }),
      });
      devicePanel.close();
      setTimeout(refreshNowPlaying, 300);
    });

    deviceList.appendChild(li);
  });
}

[deviceToggle, document.getElementById("device-current")].forEach((el) => {
  el.addEventListener("click", () => {
    devicePanel.open();
    loadDevices();
  });
});

// ---------- track list overlay (playlists, albums, Liked Songs) ----------
// One reusable panel driven by closures, rather than a hand-copied overlay
// per source - the mechanics differ (context-based play for playlists/
// albums, uris-based play for Liked Songs, which has no context_uri) but
// the markup/lifecycle is identical.

const trackListPanel = initPane("playlist-overlay", "playlist-close");
const playlistImage = document.getElementById("playlist-image");
const playlistName = document.getElementById("playlist-name");
const playlistTracksEl = document.getElementById("playlist-tracks");
const playlistPlayBtn = document.getElementById("playlist-play-btn");
const playlistShuffleBtn = document.getElementById("playlist-shuffle-btn");

let currentTrackListActions = null;

function renderTrackRow(t, onTap) {
  const li = document.createElement("li");

  const img = document.createElement("img");
  img.src = t.image || "";
  img.alt = "";
  li.appendChild(img);

  const text = document.createElement("div");
  text.className = "result-text";
  const title = document.createElement("span");
  title.className = "result-title";
  title.textContent = t.name;
  const artist = document.createElement("span");
  artist.className = "result-artist";
  artist.textContent = t.artist;
  text.appendChild(title);
  text.appendChild(artist);
  li.appendChild(text);

  li.addEventListener("click", () => onTap(t));
  return li;
}

/* Fetches JSON and turns a non-OK response into a thrown Error carrying the
   server's own message. Without this, an error response (Spotify forbids reading
   some playlists entirely) reached .json() as an HTML page and surfaced as
   "Unexpected token '<'" with the view stuck on "Loading..." forever. */
async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`;
    try {
      const data = await resp.json();
      if (data.error) message = data.error;
    } catch (e) {
      // not JSON - keep the status-based message
    }
    throw new Error(message);
  }
  return resp.json();
}

async function openTrackListOverlay({ title, image, fetchTracks, onPlayAll, onShuffle, onTrackTap }) {
  playlistImage.src = image || "";
  playlistName.textContent = title;
  playlistTracksEl.innerHTML = '<li class="playlist-loading">Loading...</li>';
  currentTrackListActions = { onPlayAll, onShuffle };
  trackListPanel.open();

  let tracks;
  try {
    tracks = await fetchTracks();
  } catch (err) {
    playlistTracksEl.innerHTML = "";
    const li = document.createElement("li");
    li.className = "track-list-error";
    li.textContent = err.message;
    playlistTracksEl.appendChild(li);
    showToast(err.message);
    return;
  }

  playlistTracksEl.innerHTML = "";
  tracks.forEach((t) => {
    // Album tracks have no per-track image - every track on an album shares
    // the same cover art, so fall back to the overlay's own header image.
    const rowData = t.image ? t : { ...t, image };
    playlistTracksEl.appendChild(
      renderTrackRow(rowData, (track) => {
        onTrackTap(track);
        trackListPanel.close();
      })
    );
  });
}

function openPlaylistDetail(item) {
  const playlistId = item.uri.split(":").pop();
  openTrackListOverlay({
    title: item.name,
    image: item.image,
    fetchTracks: () => fetchJson(`/api/spotify/playlist/${playlistId}/tracks`),
    onPlayAll: () => post("/api/spotify/play-context", { uri: item.uri }),
    onShuffle: async () => {
      await post("/api/spotify/shuffle", { state: true });
      post("/api/spotify/play-context", { uri: item.uri });
    },
    onTrackTap: (t) => post("/api/spotify/play-context-at", { context_uri: item.uri, track_uri: t.uri }),
  });
}

function openAlbumDetail(item) {
  const albumId = item.uri.split(":").pop();
  openTrackListOverlay({
    title: item.name,
    image: item.image,
    fetchTracks: () => fetchJson(`/api/spotify/album/${albumId}/tracks`),
    onPlayAll: () => post("/api/spotify/play-context", { uri: item.uri }),
    onShuffle: async () => {
      await post("/api/spotify/shuffle", { state: true });
      post("/api/spotify/play-context", { uri: item.uri });
    },
    onTrackTap: (t) => post("/api/spotify/play-context-at", { context_uri: item.uri, track_uri: t.uri }),
  });
}

playlistPlayBtn.addEventListener("click", () => {
  currentTrackListActions?.onPlayAll();
  trackListPanel.close();
});

playlistShuffleBtn.addEventListener("click", () => {
  currentTrackListActions?.onShuffle();
  trackListPanel.close();
});

// ---------- artist detail ----------
// No radio/recommendations here - Spotify permanently killed that endpoint
// for apps without extended quota access. This shows the artist's actual
// discography instead; tap an album to open its track list.

const artistPanel = initPane("artist-overlay", "artist-close");
const artistImage = document.getElementById("artist-image");
const artistName = document.getElementById("artist-name");
const artistAlbumsEl = document.getElementById("artist-albums");

async function openArtistDetail(item) {
  artistImage.src = item.image || "";
  artistName.textContent = item.name;
  artistAlbumsEl.innerHTML = '<li class="playlist-loading">Loading...</li>';
  artistPanel.open();

  const resp = await fetch(`/api/spotify/artist/${item.id}/albums`);
  const albums = await resp.json();

  artistAlbumsEl.innerHTML = "";
  albums.forEach((a) => {
    const li = document.createElement("li");

    const img = document.createElement("img");
    img.src = a.image || "";
    img.alt = "";
    li.appendChild(img);

    const text = document.createElement("div");
    text.className = "result-text";
    const title = document.createElement("span");
    title.className = "result-title";
    title.textContent = a.name;
    text.appendChild(title);
    li.appendChild(text);

    // Deliberately not closing the artist view first: leaving it on the stack is
    // what makes Back walk album -> artist -> home.
    li.addEventListener("click", () => openAlbumDetail(a));

    artistAlbumsEl.appendChild(li);
  });
}
