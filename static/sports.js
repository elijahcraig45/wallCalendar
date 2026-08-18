/* The sports page: one scoreboard, four leagues.
 *
 * sports_service normalises MLB, college football, the NFL and the Premier League
 * into a single game shape, so this renders all four with one function and knows
 * nothing about any particular sport.
 */

const sportsGames = document.getElementById("sports-games");
const sportsStatus = document.getElementById("sports-status");

let currentLeague = document.querySelector(".sports-tab")?.dataset.league || "mlb";
let sportsPollTimer = null;

/* A live game's score is the one thing on this page worth chasing. Nothing else here
   changes minute to minute, and the server caches on the same rule, so a fast poll
   with nothing in progress would just be re-reading its own cache. */
const LIVE_POLL_MS = 30000;
const IDLE_POLL_MS = 5 * 60 * 1000;

function teamRow(side, opts) {
  const row = document.createElement("div");
  row.className = "sports-team";
  if (opts.loser) row.classList.add("sports-team--loser");

  /* Team colour as a bar, never as text or a text background. ESPN hands out the
     real colours and several of them - Georgia Tech gold on this cream ground above
     all - are unreadable as text and fail the contrast sweep outright. */
  const bar = document.createElement("span");
  bar.className = "sports-team-color";
  if (side.color) bar.style.background = side.color;
  row.append(bar);

  const name = document.createElement("span");
  name.className = "sports-team-name";
  // College football only; absent everywhere else.
  if (side.rank) {
    const rank = document.createElement("span");
    rank.className = "sports-rank";
    rank.textContent = side.rank;
    name.append(rank);
  }
  name.append(document.createTextNode(side.abbr));
  row.append(name);

  if (side.record) {
    const record = document.createElement("span");
    record.className = "sports-record";
    record.textContent = side.record;
    row.append(record);
  }

  const score = document.createElement("span");
  score.className = "sports-score";
  // Blank rather than 0 before a game starts: a 0-0 that hasn't happened yet reads
  // as a scoreless game in progress.
  score.textContent = opts.started && side.score != null ? side.score : "";
  row.append(score);

  return row;
}

function gameRow(game) {
  const li = document.createElement("li");
  li.className = "sports-game";
  if (game.live) li.classList.add("sports-game--live");

  const teams = document.createElement("div");
  teams.className = "sports-teams";
  const started = game.live || game.final;
  [game.away, game.home].forEach((side) => {
    if (!side) return;
    teams.append(
      teamRow(side, { started, loser: game.final && !side.winner && side.score != null })
    );
  });
  li.append(teams);

  const meta = document.createElement("div");
  meta.className = "sports-meta";

  const detail = document.createElement("span");
  detail.className = "sports-detail";
  if (game.live) detail.classList.add("sports-detail--live");
  detail.textContent = game.detail || "";
  meta.append(detail);

  const extra = [game.broadcast, game.venue].filter(Boolean).join(" · ");
  if (extra) {
    const sub = document.createElement("span");
    sub.className = "sports-extra";
    sub.textContent = extra;
    meta.append(sub);
  }
  li.append(meta);

  return li;
}

async function loadScoreboard(league) {
  let data;
  try {
    const resp = await fetch(`/api/sports/scoreboard/${league}`);
    data = await resp.json();
  } catch (e) {
    // The endpoint answers 200-with-an-explanation, so reaching here means the wall
    // couldn't reach its own server.
    data = { available: false, errors: ["Couldn't reach the wall's own server."], games: [] };
  }

  sportsGames.innerHTML = "";

  if (!data.available) {
    sportsStatus.textContent = data.errors?.[0] || "Scores are unavailable right now.";
    scheduleSportsPoll(false);
    return;
  }

  if (!data.games.length) {
    sportsStatus.textContent = `No ${data.label} games today.`;
    scheduleSportsPoll(false);
    return;
  }

  // Says so rather than quietly showing old scores as if they were current.
  sportsStatus.textContent = data.stale
    ? "Showing the last scores that loaded - the scores service isn't answering."
    : "";

  data.games.forEach((game) => sportsGames.append(gameRow(game)));
  scheduleSportsPoll(data.has_live);
}

function scheduleSportsPoll(hasLive) {
  clearTimeout(sportsPollTimer);
  sportsPollTimer = setTimeout(
    () => loadScoreboard(currentLeague),
    hasLive ? LIVE_POLL_MS : IDLE_POLL_MS
  );
}

document.querySelectorAll(".sports-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".sports-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    currentLeague = tab.dataset.league;
    sportsStatus.textContent = "Loading…";
    loadScoreboard(currentLeague);
  });
});

loadScoreboard(currentLeague);

// The shell sends the wall home after ten idle minutes; stop polling when this page
// goes away rather than leaving a timer running against a detached document.
window.addEventListener("pagehide", () => clearTimeout(sportsPollTimer));

// Back to the first tab when the wall has been left on this page - same reason the
// calendar returns to today.
if (typeof onIdle === "function") {
  onIdle(() => {
    const first = document.querySelector(".sports-tab");
    if (first && currentLeague !== first.dataset.league) first.click();
  });
}
