/* Layout and behaviour checks for the Spotify page.
 *
 * Backed by app/demo_spotify.py, whose playback state is real (in-memory) - so
 * pressing play here actually changes what the API reports, and these tests can
 * check round-trips rather than just that buttons exist.
 *
 * Playback state is shared server-side and persists between tests, so nothing
 * below asserts a *specific* starting track - only that the right things change.
 */

const path = require("path");
const { test, expect } = require("@playwright/test");

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "..", "test-results", "shots");

const VIEWPORTS = [
  { name: "1024x600", width: 1024, height: 600 },
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1920x1080", width: 1920, height: 1080 },
];

const WIDE_FONT_CSS = `* { font-family: Verdana, sans-serif !important; }`;

async function shoot(page, name) {
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
}

/** A track list renders a "Loading..." row first, and the view's title is set
 *  before the fetch resolves - so waiting on the title proves nothing. Wait for
 *  the loading row to go instead. */
async function waitForTracks(page, listSelector = "#playlist-tracks") {
  await expect(page.locator(`${listSelector} .playlist-loading`)).toHaveCount(0);
  await expect(page.locator(`${listSelector} li`).first()).toBeVisible();
}

/** Track/album rows must actually be styled as rows.
 *
 *  These lists used to pick up their styling from classes in the template's
 *  class list (`.sheet-body`, `.row-list`) that the pane conversion removed. The
 *  queue then rendered with bullet points and a full-width album cover - and a
 *  row-*count* assertion passed the whole time, because the rows were all there.
 *  So: check the geometry, not the count. */
async function expectStyledRows(page, listSelector) {
  const rows = await page.evaluate((selector) => {
    const list = document.querySelector(selector);
    const style = getComputedStyle(list);
    return {
      bulleted: style.listStyleType !== "none",
      oversizedThumbnails: [...list.querySelectorAll("img")]
        .filter((img) => img.getBoundingClientRect().width > 80)
        .length,
      unflowedRows: [...list.querySelectorAll("li")]
        .filter((li) => getComputedStyle(li).display !== "flex" && li.querySelector("img"))
        .length,
    };
  }, listSelector);
  expect(rows, `${listSelector} rows are not styled as rows`).toEqual({
    bulleted: false,
    oversizedThumbnails: 0,
    unflowedRows: 0,
  });
}

/** The whole point of the two-pane layout is that nothing has to scroll sideways
 *  and the transport controls fit the pane they're in. */
async function expectPaneGeometry(page, label) {
  const geometry = await page.evaluate(() => {
    const transport = document.getElementById("transport-controls");
    const inner = document.getElementById("nowplaying-inner");
    const root = document.documentElement;
    return {
      pageOverflowsSideways: root.scrollWidth > root.clientWidth + 1,
      transportClipped: transport.scrollWidth > transport.clientWidth + 1,
      paneOverflows: inner.scrollHeight > inner.clientHeight + 1,
    };
  });
  expect(geometry, label).toEqual({
    pageOverflowsSideways: false,
    transportClipped: false,
    paneOverflows: false,
  });
}

for (const vp of VIEWPORTS) {
  test.describe(`spotify ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("now playing and browse both fit the pane", async ({ page }) => {
      await page.goto("/spotify");
      await expect(page.locator("#album-art")).toBeVisible();
      await expect(page.locator("#track-title")).not.toBeEmpty();
      await expect(page.locator("#track-artist")).not.toBeEmpty();
      // A real duration proves the payload reached the pane, not just markup.
      await expect(page.locator("#time-duration")).not.toHaveText("0:00");
      await expect(page.locator("#device-current-name")).not.toBeEmpty();

      expect(await page.locator("#playlists-strip .tile").count()).toBeGreaterThan(5);
      expect(await page.locator("#quick-access-grid .quick-tile").count()).toBeGreaterThan(3);

      await expectPaneGeometry(page, `${vp.name}: now-playing pane geometry`);
      await shoot(page, `spotify-${vp.name}-home`);
    });

    test("a playlist opens beside now playing, not over it", async ({ page }) => {
      await page.goto("/spotify");
      await page.locator("#playlists-strip .tile").nth(3).click();

      await expect(page.locator("#playlist-name")).not.toBeEmpty();
      await waitForTracks(page);
      expect(await page.locator("#playlist-tracks li").count()).toBeGreaterThan(3);
      await expectStyledRows(page, "#playlist-tracks");
      // The whole reason for panes over bottom sheets: now playing stays visible.
      await expect(page.locator("#album-art")).toBeVisible();
      await expect(page.locator("#browse-back")).toBeVisible();

      await expectPaneGeometry(page, `${vp.name}: playlist view geometry`);
      await shoot(page, `spotify-${vp.name}-playlist`);

      await page.click("#browse-back");
      await expect(page.locator("#browse-home")).toBeVisible();
      await expect(page.locator("#browse-back")).toBeHidden();
    });

    test("survives the wider font the Pi will actually use", async ({ page }) => {
      await page.goto("/spotify");
      await expect(page.locator("#album-art")).toBeVisible();
      await page.addStyleTag({ content: WIDE_FONT_CSS });
      await page.waitForTimeout(300);
      await expectPaneGeometry(page, `${vp.name}: wide font`);
      await shoot(page, `spotify-${vp.name}-wide-font`);
    });
  });
}

test.describe("spotify playback", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("play/pause round-trips through the API", async ({ page }) => {
    await page.goto("/spotify");
    await expect(page.locator("#album-art")).toBeVisible();

    const pausedIconHidden = () =>
      page.evaluate(() => document.getElementById("icon-pause").classList.contains("hidden"));

    const before = await pausedIconHidden();
    await page.click("#btn-play-pause");
    await expect.poll(pausedIconHidden).toBe(!before);

    // Put it back, so a later test doesn't inherit a paused player.
    await page.click("#btn-play-pause");
    await expect.poll(pausedIconHidden).toBe(before);
  });

  test("next advances to a different track", async ({ page }) => {
    await page.goto("/spotify");
    await expect(page.locator("#track-title")).not.toBeEmpty();
    const first = await page.textContent("#track-title");

    await page.click("#btn-next");
    await expect.poll(() => page.textContent("#track-title")).not.toBe(first);
  });

  test("tapping a track in a playlist starts it", async ({ page }) => {
    await page.goto("/spotify");
    await page.locator("#playlists-strip .tile").nth(2).click();
    await waitForTracks(page);

    const wanted = await page.locator("#playlist-tracks li .result-title").nth(3).textContent();
    await page.locator("#playlist-tracks li").nth(3).click();
    await expect.poll(() => page.textContent("#track-title")).toBe(wanted);
  });

  test("the queue and device picker open as panes", async ({ page }) => {
    await page.goto("/spotify");

    await page.click("#queue-toggle");
    await expect(page.locator("#queue-overlay")).toBeVisible();
    await expect(page.locator("#album-art")).toBeVisible();
    await waitForTracks(page, "#queue-tracks");
    expect(await page.locator("#queue-tracks li").count()).toBeGreaterThan(0);
    await expectStyledRows(page, "#queue-tracks");

    await page.click("#device-toggle");
    await expect(page.locator("#device-overlay")).toBeVisible();
    // loadDevices() is async - the list is empty for a moment after the click.
    await expect(page.locator("#device-list li:not(.device-note)").first()).toBeVisible();
    expect(await page.locator("#device-list li:not(.device-note)").count()).toBeGreaterThan(1);
    // Exactly one device reads as active.
    await expect(page.locator("#device-list li.active")).toHaveCount(1);
  });
});

test.describe("spotify browse navigation", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // The search field lives in the pane's persistent header, so it can be typed
  // into while a detail view is open - and results render inside the *home*
  // view. Without resetting the view first, typing silently did nothing.
  test("search works while a detail view is open", async ({ page }) => {
    await page.goto("/spotify");
    await page.click("#queue-toggle");
    await expect(page.locator("#queue-overlay")).toBeVisible();

    await page.fill("#search-input", "water");
    await expect(page.locator("#search-results .tile").first()).toBeVisible();
    await expect(page.locator("#browse-home")).toBeVisible();
    await expect(page.locator("#queue-overlay")).toBeHidden();
  });

  test("back walks album to artist to home", async ({ page }) => {
    await page.goto("/spotify");
    await page.fill("#search-input", "ada");
    await expect(page.locator("#search-results .tile").first()).toBeVisible();

    await page.locator("#search-results .tile").first().click();
    await expect(page.locator("#artist-overlay")).toBeVisible();
    const artist = await page.textContent("#artist-name");
    expect(artist).not.toBe("");

    await page.locator("#artist-albums li").first().click();
    await expect(page.locator("#playlist-overlay")).toBeVisible();

    // Reaching an album *through* an artist must come back to that artist, not
    // dump you at home - which is what happens if the artist view is closed
    // before the album view opens.
    await page.click("#browse-back");
    await expect(page.locator("#artist-overlay")).toBeVisible();
    await expect(page.locator("#artist-name")).toHaveText(artist);

    await page.click("#browse-back");
    await expect(page.locator("#browse-home")).toBeVisible();
  });
});

test.describe("shell now-playing chip", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("shows on the calendar and is suppressed on the Music page", async ({ page }) => {
    await page.goto("/");
    // Music is now visible from the calendar - previously the only now-playing
    // UI lived inside the Spotify page.
    await expect(page.locator("#rail-now-playing")).toBeVisible();
    await expect(page.locator("#rail-np-title")).not.toBeEmpty();
    await expect(page.locator("#rail-np-art")).toHaveAttribute("src", /.+/);
    await shoot(page, "spotify-rail-chip-on-calendar");

    // Redundant next to a full now-playing pane. This asserts the display rule
    // stayed class-scoped: an ID-scoped `display: flex` outranks .hidden, which
    // is how the chip first shipped visible here.
    await page.goto("/spotify");
    await expect(page.locator("#rail-now-playing")).toBeHidden();
  });

  test("the chip's play/pause controls playback from the calendar", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#rail-now-playing")).toBeVisible();

    const playIconHidden = () =>
      page.evaluate(() => document.getElementById("rail-np-play").classList.contains("hidden"));
    const before = await playIconHidden();
    await page.click("#rail-np-toggle");
    await expect.poll(playIconHidden).toBe(!before);

    await page.click("#rail-np-toggle");
    await expect.poll(playIconHidden).toBe(before);
  });
});

test.describe("spotify page hygiene", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("loads no Web Playback SDK and logs nothing in demo mode", async ({ page }) => {
    const problems = [];
    const sdkRequests = [];
    page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
    page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
    page.on("request", (r) => { if (r.url().includes("sdk.scdn.co")) sdkRequests.push(r.url()); });

    await page.goto("/spotify");
    await expect(page.locator("#album-art")).toBeVisible();
    await page.waitForTimeout(1500);

    // The SDK can't authenticate against fixture state; loading it just produced
    // a stream of 401s and a DRM failure.
    expect(sdkRequests, "Web Playback SDK loaded in demo mode").toEqual([]);
    expect(problems, "console errors on the Spotify page").toEqual([]);
  });
});
