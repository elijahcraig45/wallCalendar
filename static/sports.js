/* The sports page: one scoreboard, four leagues.
 *
 * sports_service normalises MLB, college football, the NFL and the Premier League
 * into a single game shape, so this renders all four with one function and knows
 * nothing about any particular sport.
 */

const sportsGames = document.getElementById("sports-games");
const sportsStatus = document.getElementById("sports-status");

const sportsNav = document.getElementById("sports-nav");
const sportsWhen = document.getElementById("sports-when");

const firstTab = document.querySelector(".sports-tab");
let currentLeague = firstTab?.dataset.league || "mlb";
let currentNav = firstTab?.dataset.nav || "date";
let currentView = "games";
// Which calendar slot ESPN called current, so "Now" has something to return to.
let homeIndex = null;
let sportsPollTimer = null;

/* How far from "now" the view is: days for the date-stepped leagues, weeks for the
   football ones. Kept as an offset rather than an absolute so "Today" is always a
   reset to zero and the server decides what current means - the wall's clock and
   ESPN's idea of the current week are not always the same thing. */
let offset = 0;

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

/* ---------- news ---------- */

function articleRow(article) {
  const li = document.createElement("li");
  li.className = "sports-article";

  const body = document.createElement("div");
  body.className = "sports-article-body";

  const headline = document.createElement("div");
  headline.className = "sports-headline";
  headline.textContent = article.headline || "";
  body.append(headline);

  if (article.description) {
    const desc = document.createElement("div");
    desc.className = "sports-desc";
    desc.textContent = article.description;
    body.append(desc);
  }

  /* Tapping expands in place rather than opening the Web tab. ESPN's
     Content-Security-Policy sets frame-ancestors to its own domains, so an article
     cannot be framed here at all - sending someone to the Web tab would hand them a
     blank frame. The full text is not in this API either, so the honest thing to
     offer is the summary plus where it came from. */
  if (article.link) {
    const source = document.createElement("div");
    source.className = "sports-source hidden";
    source.textContent = article.byline
      ? `${article.byline} · espn.com`
      : "espn.com";
    body.append(source);
    li.classList.add("sports-article--expandable");
    li.addEventListener("click", () => {
      const open = li.classList.toggle("sports-article--open");
      source.classList.toggle("hidden", !open);
    });
  }
  li.append(body);

  if (article.published) {
    const when = document.createElement("span");
    when.className = "sports-published";
    when.textContent = relativeTime(article.published);
    li.append(when);
  }
  return li;
}

/** "2h ago" / "yesterday". A wall-calendar reader wants to know if a headline is
 *  fresh, not the exact minute it was filed. */
function relativeTime(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const hours = Math.round((Date.now() - then.getTime()) / 3600000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

/* ---------- standings ---------- */

// What a "record" is depends on the sport, and it cannot be inferred from which
// fields are populated: ESPN returns a `points` stat for MLB too (a run-differential
// derived number), so preferring it whenever present labelled the Braves "13.0 pts".
let standingsSport = null;

function standingsGroup(group) {
  const li = document.createElement("li");
  li.className = "sports-standings-group";

  const heading = document.createElement("div");
  heading.className = "sports-standings-name";
  heading.textContent = group.name || "";
  li.append(heading);

  group.teams.forEach((team) => {
    const row = document.createElement("div");
    row.className = "sports-standings-row";
    // The followed teams are what this page is really for, so they are marked.
    if (followedAbbrs.has((team.abbr || "").toUpperCase())) {
      row.classList.add("sports-standings-row--mine");
    }

    const bar = document.createElement("span");
    bar.className = "sports-team-color";
    if (team.color) bar.style.background = team.color;
    row.append(bar);

    const name = document.createElement("span");
    name.className = "sports-standings-team";
    name.textContent = team.name || team.abbr;
    row.append(name);

    const record = document.createElement("span");
    record.className = "sports-standings-record";
    // Soccer has draws and points; the US sports have wins and losses.
    /* Ties are dropped when there aren't any. ESPN reports ties: "0" for baseball,
       where the concept doesn't exist, so including it unconditionally rendered the
       Braves as "74-51-0". The NFL genuinely can tie, so this keeps the column when
       the number is real rather than deciding by sport. */
    const parts = [team.wins, team.losses];
    if (team.ties && team.ties !== "0") parts.push(team.ties);
    record.textContent =
      standingsSport === "soccer" && team.points != null
        ? `${team.points} pts`
        : parts.filter((v) => v != null).join("-");
    row.append(record);

    const behind = document.createElement("span");
    behind.className = "sports-standings-behind";
    behind.textContent = team.behind && team.behind !== "-" ? `${team.behind} GB` : "";
    row.append(behind);

    li.append(row);
  });
  return li;
}

/* ---------- rankings ---------- */

function rankingRow(team) {
  const li = document.createElement("li");
  li.className = "sports-rank-row";

  const rank = document.createElement("span");
  rank.className = "sports-rank-num";
  rank.textContent = team.rank;
  li.append(rank);

  const bar = document.createElement("span");
  bar.className = "sports-team-color";
  if (team.color) bar.style.background = team.color;
  li.append(bar);

  const name = document.createElement("span");
  name.className = "sports-rank-name";
  name.textContent = team.name || team.abbr;
  li.append(name);

  const record = document.createElement("span");
  record.className = "sports-record";
  record.textContent = team.record || "";
  li.append(record);

  // Movement since last week's poll, which is the thing worth glancing at.
  if (team.previous && team.rank && team.previous !== team.rank) {
    const move = document.createElement("span");
    const up = team.previous > team.rank;
    move.className = `sports-move sports-move--${up ? "up" : "down"}`;
    move.textContent = `${up ? "▲" : "▼"}${Math.abs(team.previous - team.rank)}`;
    li.append(move);
  }
  return li;
}

/* ---------- loading ---------- */

/* For the week-stepped leagues the position is an index into ESPN's own calendar,
   not an arithmetic offset. Weeks are numbered *within* a season type, so "week 2 +
   1" is not a thing you can compute: in August it has to become preseason week 3,
   and at the end of preseason it has to roll into regular-season week 1. Walking
   their list gets all of that, plus their labels, for free. */
let calendar = [];
let weekIndex = null;

function navQuery() {
  if (currentNav === "week") {
    if (weekIndex == null || !calendar[weekIndex]) return "";
    const slot = calendar[weekIndex];
    return `?week=${slot.week}&seasontype=${slot.seasontype}`;
  }
  if (!offset) return "";
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return `?date=${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

/* Which teams to pick out of a standings table. Read once - the list only changes
   from /system, which reloads the page. */
const followedAbbrs = new Set();
fetch("/api/sports/following")
  .then((r) => r.json())
  .then((d) => (d.teams || []).forEach((t) => followedAbbrs.add((t.team.abbr || "").toUpperCase())))
  .catch(() => {});

function renderWhen(data) {
  const isGames = currentView === "games";
  sportsNav.classList.toggle("hidden", !isGames);
  if (!isGames) return;

  if (currentNav === "week") {
    const slot = calendar[weekIndex];
    /* ESPN's label, not a constructed one: it already says "Preseason Week 1",
       "Hall of Fame Weekend" and "Wild Card", where anything built here would have
       said "Week 1" for all three. */
    sportsWhen.textContent = slot ? slot.label : data.week ? `Week ${data.week}` : "";
    document.getElementById("sports-prev").disabled = weekIndex === 0;
    document.getElementById("sports-next").disabled = weekIndex === calendar.length - 1;
    document.getElementById("sports-now").classList.toggle("hidden", weekIndex === homeIndex);
    return;
  }
  if (offset === 0) {
    sportsWhen.textContent = "Today";
  } else {
    const day = new Date();
    day.setDate(day.getDate() + offset);
    sportsWhen.textContent = day.toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric",
    });
  }
  document.getElementById("sports-now").classList.toggle("hidden", offset === 0);
}

async function loadView() {
  const endpoint =
    currentView === "games"
      ? `/api/sports/scoreboard/${currentLeague}${navQuery()}`
      : `/api/sports/${currentView}/${currentLeague}`;

  let data;
  try {
    const resp = await fetch(endpoint);
    data = await resp.json();
  } catch (e) {
    // The endpoints answer 200-with-an-explanation, so reaching here means the wall
    // couldn't reach its own server.
    data = { available: false, errors: ["Couldn't reach the wall's own server."] };
  }

  sportsGames.innerHTML = "";

  // The calendar arrives with every scoreboard; adopt it the first time, and pin
  // "now" to whatever ESPN considered current on that first, unparameterised call.
  if (data.calendar?.length && !calendar.length) {
    calendar = data.calendar;
    weekIndex = calendar.findIndex(
      (c) => c.week === data.week && c.seasontype === data.season_type
    );
    if (weekIndex < 0) weekIndex = 0;
    homeIndex = weekIndex;
  }
  renderWhen(data);

  if (!data.available) {
    sportsStatus.textContent = data.errors?.[0] || "Unavailable right now.";
    scheduleSportsPoll(false);
    return;
  }

  sportsStatus.textContent = data.stale
    ? "Showing the last data that loaded - the scores service isn't answering."
    : "";

  if (currentView === "news") {
    const articles = data.articles || [];
    if (!articles.length) sportsStatus.textContent = `No ${data.label} headlines right now.`;
    articles.forEach((a) => sportsGames.append(articleRow(a)));
    scheduleSportsPoll(false);
    return;
  }

  if (currentView === "standings") {
    const groups = data.groups || [];
    standingsSport = data.sport;
    if (!groups.length) sportsStatus.textContent = "No table published yet.";
    groups.forEach((g) => sportsGames.append(standingsGroup(g)));
    scheduleSportsPoll(false);
    return;
  }

  if (currentView === "rankings") {
    const teams = data.teams || [];
    if (!teams.length) sportsStatus.textContent = "No poll published yet.";
    teams.forEach((t) => sportsGames.append(rankingRow(t)));
    scheduleSportsPoll(false);
    return;
  }

  if (!data.games.length) {
    sportsStatus.textContent =
      currentNav === "week" ? `No ${data.label} games that week.` : `No ${data.label} games that day.`;
    scheduleSportsPoll(false);
    return;
  }

  data.games.forEach((game) => sportsGames.append(gameRow(game)));
  // Only chase a live score when looking at the current slate - a past Saturday
  // never changes.
  scheduleSportsPoll(data.has_live && (currentNav === "week" ? weekIndex === homeIndex : offset === 0));
}

function scheduleSportsPoll(hasLive) {
  clearTimeout(sportsPollTimer);
  sportsPollTimer = setTimeout(
    loadView,
    hasLive ? LIVE_POLL_MS : IDLE_POLL_MS
  );
}

document.querySelectorAll(".sports-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".sports-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    currentLeague = tab.dataset.league;
    currentNav = tab.dataset.nav;
    // A week number from one league means nothing in another, and neither does a
    // date offset once the nav mode changes, so switching league starts at "now".
    offset = 0;
    calendar = [];
    weekIndex = null;
    homeIndex = null;
    document.querySelector('.sports-view-tab[data-view="rankings"]')
      .classList.toggle("hidden", tab.dataset.rankings !== "yes");
    if (currentView === "rankings" && tab.dataset.rankings !== "yes") setView("games");
    sportsStatus.textContent = "Loading…";
    loadView();
  });
});

loadView();

// The shell sends the wall home after ten idle minutes; stop polling when this page
// goes away rather than leaving a timer running against a detached document.
window.addEventListener("pagehide", () => clearTimeout(sportsPollTimer));

// Back to the first tab when the wall has been left on this page - same reason the
// calendar returns to today.
if (typeof onIdle === "function") {
  onIdle(() => {
    const first = document.querySelector(".sports-tab");
    if (first && currentLeague !== first.dataset.league) first.click();
    else if (offset !== 0 || currentView !== "games") {
      // Left on last Saturday's scores or a news list, the wall should be showing
      // today's games again by the time anyone looks at it.
      setView("games");
      offset = 0;
      weekIndex = homeIndex;
      loadView();
    }
  });
}

/* ---------- view + date navigation ---------- */

function setView(view) {
  currentView = view;
  document.querySelectorAll(".sports-view-tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === view)
  );
}

document.querySelectorAll(".sports-view-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    setView(tab.dataset.view);
    sportsStatus.textContent = "Loading…";
    loadView();
  });
});

function step(by) {
  if (currentNav === "week") {
    if (weekIndex == null) return;
    weekIndex = Math.min(calendar.length - 1, Math.max(0, weekIndex + by));
  } else {
    offset += by;
  }
  loadView();
}

document.getElementById("sports-prev").addEventListener("click", () => step(-1));
document.getElementById("sports-next").addEventListener("click", () => step(1));

document.getElementById("sports-now").addEventListener("click", () => {
  offset = 0;
  weekIndex = homeIndex;
  loadView();
});
