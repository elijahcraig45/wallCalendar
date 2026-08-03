const albumArt = document.getElementById("album-art");
const backdropBlur = document.getElementById("backdrop-blur");
const trackTitle = document.getElementById("track-title");
const trackArtist = document.getElementById("track-artist");
const playPauseBtn = document.getElementById("btn-play-pause");
const shuffleBtn = document.getElementById("btn-shuffle");
const iconPlay = document.getElementById("icon-play");
const iconPause = document.getElementById("icon-pause");
const progressFill = document.getElementById("progress-fill");
const timeElapsed = document.getElementById("time-elapsed");
const timeDuration = document.getElementById("time-duration");

const miniPlayer = document.getElementById("mini-player");
const miniArt = document.getElementById("mini-art");
const miniTitle = document.getElementById("mini-title");
const miniArtist = document.getElementById("mini-artist");
const miniPlayPauseBtn = document.getElementById("mini-play-pause");
const miniIconPlay = document.getElementById("mini-icon-play");
const miniIconPause = document.getElementById("mini-icon-pause");

const nowPlayingOverlay = document.getElementById("nowplaying-overlay");

let state = { progressMs: 0, durationMs: 0, isPlaying: false, lastUpdate: Date.now() };

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

async function refreshNowPlaying() {
  const resp = await fetch("/api/spotify/now-playing");
  const data = await resp.json();

  if (!data) {
    trackTitle.textContent = "Nothing playing";
    trackArtist.textContent = "";
    albumArt.classList.add("hidden");
    backdropBlur.style.backgroundImage = "none";
    state = { progressMs: 0, durationMs: 0, isPlaying: false, lastUpdate: Date.now() };
    iconPlay.classList.remove("hidden");
    iconPause.classList.add("hidden");
    shuffleBtn.classList.remove("active");
    renderProgress();
    miniPlayer.classList.add("hidden");
    return;
  }

  trackTitle.textContent = data.track;
  trackArtist.textContent = data.artist;
  state = {
    progressMs: data.progress_ms || 0,
    durationMs: data.duration_ms || 0,
    isPlaying: data.is_playing,
    lastUpdate: Date.now(),
  };

  iconPlay.classList.toggle("hidden", state.isPlaying);
  iconPause.classList.toggle("hidden", !state.isPlaying);
  shuffleBtn.classList.toggle("active", !!data.shuffle_state);

  if (data.album_art) {
    albumArt.src = data.album_art;
    albumArt.classList.remove("hidden");
    backdropBlur.style.backgroundImage = `url(${data.album_art})`;
  } else {
    albumArt.classList.add("hidden");
    backdropBlur.style.backgroundImage = "none";
  }

  renderProgress();

  // ---- mini-player ----
  miniPlayer.classList.remove("hidden");
  miniTitle.textContent = data.track;
  miniArtist.textContent = data.artist;
  miniArt.src = data.album_art || "";
  miniIconPlay.classList.toggle("hidden", state.isPlaying);
  miniIconPause.classList.toggle("hidden", !state.isPlaying);
}

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

refreshNowPlaying();
setInterval(refreshNowPlaying, 5000);
setInterval(renderProgress, 500);

// ---------- mini-player <-> full-screen expand/collapse ----------

miniPlayPauseBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  post(state.isPlaying ? "/api/spotify/pause" : "/api/spotify/play");
});

miniPlayer.addEventListener("click", () => {
  nowPlayingOverlay.classList.remove("hidden");
});

document.getElementById("nowplaying-collapse").addEventListener("click", () => {
  nowPlayingOverlay.classList.add("hidden");
});

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

async function loadPlaylists() {
  const resp = await fetch("/api/spotify/playlists");
  const lists = await resp.json();
  renderTiles(
    document.getElementById("playlists-strip"),
    lists,
    (item) => openPlaylistDetail(item)
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
      const strip = addSearchGroup("Artists", "tile-strip");
      renderTiles(strip, data.artists, (item) => openArtistDetail(item), "artist-tile");
    }

    if (data.albums.length > 0) {
      const strip = addSearchGroup("Albums", "tile-strip");
      renderTiles(strip, data.albums, (item) => post("/api/spotify/play-context", { uri: item.uri }));
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
const deviceOverlay = document.getElementById("device-overlay");
const deviceList = document.getElementById("device-list");

const SPEAKER_ICON =
  '<svg class="device-icon" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>';

async function loadDevices() {
  const resp = await fetch("/api/spotify/devices");
  const devices = await resp.json();
  deviceList.innerHTML = "";

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
      deviceOverlay.classList.add("hidden");
      setTimeout(refreshNowPlaying, 300);
    });

    deviceList.appendChild(li);
  });
}

deviceToggle.addEventListener("click", () => {
  deviceOverlay.classList.remove("hidden");
  loadDevices();
});

document.getElementById("device-close").addEventListener("click", () => {
  deviceOverlay.classList.add("hidden");
});

deviceOverlay.addEventListener("click", (e) => {
  if (e.target === deviceOverlay) deviceOverlay.classList.add("hidden");
});

// ---------- playlist detail ----------

const playlistOverlay = document.getElementById("playlist-overlay");
const playlistImage = document.getElementById("playlist-image");
const playlistName = document.getElementById("playlist-name");
const playlistTracksEl = document.getElementById("playlist-tracks");
let currentPlaylistUri = null;

async function openPlaylistDetail(item) {
  currentPlaylistUri = item.uri;
  playlistImage.src = item.image || "";
  playlistName.textContent = item.name;
  playlistTracksEl.innerHTML = '<li class="playlist-loading">Loading...</li>';
  playlistOverlay.classList.remove("hidden");

  const playlistId = item.uri.split(":").pop();
  const resp = await fetch(`/api/spotify/playlist/${playlistId}/tracks`);
  const tracks = await resp.json();

  playlistTracksEl.innerHTML = "";
  tracks.forEach((t) => {
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

    li.addEventListener("click", () => {
      post("/api/spotify/play-context-at", { context_uri: currentPlaylistUri, track_uri: t.uri });
      playlistOverlay.classList.add("hidden");
    });

    playlistTracksEl.appendChild(li);
  });
}

document.getElementById("playlist-play-btn").addEventListener("click", () => {
  post("/api/spotify/play-context", { uri: currentPlaylistUri });
  playlistOverlay.classList.add("hidden");
});

document.getElementById("playlist-shuffle-btn").addEventListener("click", async () => {
  await post("/api/spotify/shuffle", { state: true });
  post("/api/spotify/play-context", { uri: currentPlaylistUri });
  playlistOverlay.classList.add("hidden");
});

document.getElementById("playlist-close").addEventListener("click", () => {
  playlistOverlay.classList.add("hidden");
});

playlistOverlay.addEventListener("click", (e) => {
  if (e.target === playlistOverlay) playlistOverlay.classList.add("hidden");
});

// ---------- artist detail ----------
// No radio/recommendations here - Spotify permanently killed that endpoint
// for apps without extended quota access. This shows the artist's actual
// discography instead; tap an album to play it.

const artistOverlay = document.getElementById("artist-overlay");
const artistImage = document.getElementById("artist-image");
const artistName = document.getElementById("artist-name");
const artistAlbumsEl = document.getElementById("artist-albums");

async function openArtistDetail(item) {
  artistImage.src = item.image || "";
  artistName.textContent = item.name;
  artistAlbumsEl.innerHTML = '<li class="playlist-loading">Loading...</li>';
  artistOverlay.classList.remove("hidden");

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

    li.addEventListener("click", () => {
      post("/api/spotify/play-context", { uri: a.uri });
      artistOverlay.classList.add("hidden");
    });

    artistAlbumsEl.appendChild(li);
  });
}

document.getElementById("artist-close").addEventListener("click", () => {
  artistOverlay.classList.add("hidden");
});

artistOverlay.addEventListener("click", (e) => {
  if (e.target === artistOverlay) artistOverlay.classList.add("hidden");
});
