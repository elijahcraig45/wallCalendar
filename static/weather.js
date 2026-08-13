/* Weather chip + panel, shell-wide.
 *
 * Also the source of sunrise/sunset for the night-dimming behaviour, so the wall
 * dims with the actual season rather than a hardcoded hour.
 */

/* Simple line icons rather than emoji: emoji render at wildly different sizes and
   styles depending on the installed font, and Raspberry Pi OS's emoji coverage is
   not the Mac's. These are the same weight as the rail icons. */
const WEATHER_ICONS = {
  clear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 1v3M12 20v3M1 12h3M20 12h3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M19.8 4.2l-2.1 2.1M6.3 17.7l-2.1 2.1"/></g></svg>',
  partly: '<svg viewBox="0 0 24 24"><circle cx="8.5" cy="8" r="3.6" fill="currentColor"/><path d="M10 19h7.5a3.5 3.5 0 0 0 .3-7 5 5 0 0 0-9.6 1.2A3.4 3.4 0 0 0 10 19z" fill="currentColor" opacity="0.85"/></svg>',
  cloudy: '<svg viewBox="0 0 24 24"><path d="M7 19h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 19z" fill="currentColor"/></svg>',
  fog: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 18h16M6 21.5h12"/></g></svg>',
  drizzle: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 17.5v2M15 17.5v2"/></g></svg>',
  rain: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8.5 17v4M12 17v4M15.5 17v4"/></g></svg>',
  sleet: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 17.5v3M15 17.5v3M12 18l0 .01"/></g><circle cx="12" cy="19.5" r="1.3" fill="currentColor"/></svg>',
  snow: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><g fill="currentColor"><circle cx="9" cy="18.5" r="1.3"/><circle cx="12.5" cy="21" r="1.3"/><circle cx="16" cy="18.5" r="1.3"/></g></svg>',
  storm: '<svg viewBox="0 0 24 24"><path d="M7 14h10.5a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.6 1A3.5 3.5 0 0 0 7 14z" fill="currentColor"/><path d="M13 16l-4 6h3l-1 4 5-6h-3l1.5-4z" fill="currentColor"/></svg>',
};

// Night variants. Only clear and partly need them - a rain cloud looks the same
// at any hour, but a blazing sun at midnight makes the whole panel look wrong.
const WEATHER_ICONS_NIGHT = {
  clear: '<svg viewBox="0 0 24 24"><path d="M15.5 2A9.5 9.5 0 1 0 22 13.2 7.5 7.5 0 0 1 15.5 2z" fill="currentColor"/></svg>',
  partly: '<svg viewBox="0 0 24 24"><path d="M11.5 2.6A6.4 6.4 0 1 0 16 10.2 5 5 0 0 1 11.5 2.6z" fill="currentColor"/><path d="M8 19h8.5a3.3 3.3 0 0 0 .2-6.6 5.2 5.2 0 0 0-10 .9A3.2 3.2 0 0 0 8 19z" fill="currentColor" opacity="0.85"/></svg>',
};

function weatherIcon(key) {
  return WEATHER_ICONS[key] || WEATHER_ICONS.cloudy;
}

/** The icon for a key at a given time of day. `isDay` undefined means day, so
 *  callers with no daylight information behave exactly as before. */
function weatherIconAt(key, isDay) {
  if (isDay === false || isDay === 0) {
    return WEATHER_ICONS_NIGHT[key] || weatherIcon(key);
  }
  return weatherIcon(key);
}

const weatherChip = document.getElementById("weather-chip");
const weatherIconEl = document.getElementById("weather-icon");
const weatherTempEl = document.getElementById("weather-temp");
const weatherRangeEl = document.getElementById("weather-range");
const weatherNow = document.getElementById("weather-now");
const weatherForecast = document.getElementById("weather-forecast");
const weatherFootnote = document.getElementById("weather-footnote");

// Published so the dimming schedule can key off real sun times.
let currentWeather = null;
const weatherListeners = [];

function onWeather(listener) {
  weatherListeners.push(listener);
  if (currentWeather) listener(currentWeather);
}

function shortDay(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" });
}

function renderWeather(data) {
  currentWeather = data;

  if (!data || data.available === false) {
    weatherChip.classList.add("hidden");
  } else {
    weatherChip.classList.remove("hidden");
    weatherIconEl.innerHTML = weatherIcon(data.icon);
    weatherTempEl.textContent = `${data.temperature}°`;
    const today = data.days && data.days[0];
    weatherRangeEl.textContent = today ? `${today.high}° / ${today.low}°` : "";
    weatherChip.classList.toggle("stale", !!data.stale);
  }

  weatherListeners.forEach((listener) => listener(data));
}

// Today plus three. The payload now carries a full week for the /weather page,
// but this is a peek from the header - seven cells in a small overlay is a worse
// answer than a link to the page with room for them.
const PANEL_FORECAST_DAYS = 4;

function renderWeatherPanel() {
  const data = currentWeather;
  if (!data) return;

  weatherNow.innerHTML = "";
  const hero = document.createElement("div");
  hero.className = "weather-hero";
  hero.innerHTML = `
    <span class="weather-hero-icon">${weatherIcon(data.icon)}</span>
    <div>
      <div class="weather-hero-temp">${data.temperature}°</div>
      <div class="weather-hero-label">${data.label}</div>
      <div class="weather-hero-meta">
        Feels ${data.feels_like}° &middot; ${data.humidity}% humidity &middot; ${data.wind} mph
      </div>
    </div>`;
  weatherNow.appendChild(hero);

  weatherForecast.innerHTML = "";
  // Today plus three. The payload now carries a full week for the /weather page,
  // but this is a peek from the header - seven cells in a small overlay is a
  // worse answer than a link to the page that has room for them.
  (data.days || []).slice(0, PANEL_FORECAST_DAYS).forEach((day, index) => {
    const cell = document.createElement("div");
    cell.className = "forecast-day";
    cell.innerHTML = `
      <div class="forecast-name">${index === 0 ? "Today" : shortDay(day.date)}</div>
      <div class="forecast-icon">${weatherIcon(day.icon)}</div>
      <div class="forecast-temps"><strong>${day.high}°</strong> ${day.low}°</div>
      <div class="forecast-precip">${day.precip_chance != null ? day.precip_chance + "%" : ""}</div>`;
    weatherForecast.appendChild(cell);
  });

  const sun = data.sunrise && data.sunset
    ? `Sunrise ${new Date(data.sunrise).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` +
      ` · sunset ${new Date(data.sunset).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : "";
  weatherFootnote.textContent = data.stale
    ? `${sun} · offline, last reading ${new Date(data.fetched_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : `${data.place} · ${sun}`;
}

const weatherPanel = initPanel("weather-overlay", "weather-close");
weatherChip.addEventListener("click", () => {
  renderWeatherPanel();
  weatherPanel.open();
});

async function refreshWeather() {
  try {
    const resp = await fetch("/api/weather");
    renderWeather(resp.ok ? await resp.json() : null);
  } catch (e) {
    renderWeather(null);
  }
}

refreshWeather();
// The server caches for 15 minutes, so polling faster than that only burns
// requests against its own cache.
setInterval(refreshWeather, 15 * 60 * 1000);
