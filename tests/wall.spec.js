/* Layout verification for the landscape wall calendar.
 *
 * The point of these tests is not pixel-matching - it's proving the layout
 * survives the panel sizes this thing actually runs on, with a realistic
 * (deliberately dense) set of events behind it. Every assertion is about
 * something that would be visibly broken on the wall: content spilling out of
 * a cell, a top bar that can't fit its own controls, concurrent events drawn
 * on top of each other, a page that scrolls sideways.
 */

const path = require("path");
const { test, expect } = require("@playwright/test");

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "..", "test-results", "shots");

// The panels this is plausibly mounted on. 1024x600 is the official Pi 7" DSI
// touchscreen and by far the tightest case; 1280x800 is the newer 7"; 1920x1080
// is a repurposed monitor or TV.
const VIEWPORTS = [
  { name: "1024x600", width: 1024, height: 600 },
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1920x1080", width: 1920, height: 1080 },
];

// Raspberry Pi OS has none of -apple-system / Segoe UI / Roboto, so the wall
// renders in DejaVu Sans - wider than anything available on a Mac. Verdana is
// present here and is wider still, so passing under it means there's real slack
// for the Pi rather than a layout tuned to macOS metrics.
const WIDE_FONT_CSS = `* { font-family: Verdana, sans-serif !important; }`;

async function shoot(page, name) {
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
}

/** Nothing anywhere on the page may scroll horizontally. */
async function expectNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(() => {
    const results = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth + 1) {
      results.push({ el: "html", scroll: root.scrollWidth, client: root.clientWidth });
    }
    document.querySelectorAll("#top-bar, #top-bar-content, #rail, #stage, #content").forEach((el) => {
      if (el.scrollWidth > el.clientWidth + 1) {
        results.push({ el: el.id, scroll: el.scrollWidth, client: el.clientWidth });
      }
    });
    return results;
  });
  expect(overflow, `${label}: horizontal overflow`).toEqual([]);
}

async function switchView(page, view) {
  await page.click(`.view-tab[data-view="${view}"]`);
  await expect(page.locator(`.view-tab[data-view="${view}"]`)).toHaveAttribute("aria-selected", "true");
  // The switch triggers a fetch + re-render; wait for the pane to be populated.
  await page.waitForTimeout(400);
}

for (const vp of VIEWPORTS) {
  test.describe(`${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("month view fits its cells and fills its rows", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();

      // Rows must come from the data: a 5-week month rendered into 6 fixed rows
      // used to leave a permanently empty band across the bottom.
      const cells = await page.locator("#month-grid .day-cell").count();
      expect(cells % 7).toBe(0);
      // One .week-row per week: each needs its own span-bar layer over its own
      // cells, so this is a column of week grids rather than one flat 7xN grid.
      const rows = await page.locator("#month-grid .week-row").count();
      expect(rows).toBe(cells / 7);

      // No cell may hide content it rendered - pills-per-cell is computed from
      // the measured cell height, and this is the check that it was computed
      // correctly for this viewport.
      const spilling = await page.evaluate(() =>
        [...document.querySelectorAll(".day-cell")]
          .filter((c) => c.scrollHeight > c.clientHeight + 1)
          .map((c) => ({
            day: c.querySelector(".day-number")?.textContent,
            scroll: c.scrollHeight,
            client: c.clientHeight,
          }))
      );
      expect(spilling, "day cells clipping their own content").toEqual([]);

      // The fixtures put 9 events on today, so overflow indication must engage
      // somewhere rather than silently dropping events.
      await expect(page.locator(".event-overflow").first()).toBeVisible();

      // Long titles must ellipsise inside their chip, not overflow it. A bare text
      // node in a flex container ignores text-overflow entirely, so every title
      // lives in its own span - .event-pill-title for timed events,
      // .span-bar-label for the all-day bars.
      const overflowing = await page.evaluate(() =>
        [...document.querySelectorAll(".event-pill, .span-bar")]
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map((el) => el.textContent.trim())
      );
      expect(overflowing, "chip text overflowing its chip").toEqual([]);

      // ...and prove that check isn't vacuous. The long fixture title is an
      // all-day event, so it renders as a span bar rather than a pill - which is
      // exactly how this assertion silently stopped proving anything once
      // multi-day events became bars.
      const ellipsised = await page.evaluate(() =>
        [...document.querySelectorAll(".event-pill-title, .span-bar-label")]
          .filter((t) => t.scrollWidth > t.clientWidth + 1).length
      );
      expect(ellipsised, "nothing ellipsised - the overflow check proves nothing").toBeGreaterThan(0);

      await expectNoHorizontalOverflow(page, "month");
      await shoot(page, `${vp.name}-month`);
    });

    test("week view renders a real time grid", async ({ page }) => {
      await page.goto("/");
      await switchView(page, "week");

      await expect(page.locator(".timegrid-col")).toHaveCount(7);
      await expect(page.locator(".timegrid-day-head")).toHaveCount(7);
      // The day-detail pane belongs to day view only; a week has no single day
      // to detail.
      await expect(page.locator("#day-detail")).toBeHidden();
      // Today is always inside the current week, so the now-line must exist and
      // must be in exactly one column.
      await expect(page.locator(".now-line")).toHaveCount(1);
      expect(await page.locator(".event-block").count()).toBeGreaterThan(10);

      // Every block has to stay inside its own day column.
      const escaping = await page.evaluate(() =>
        [...document.querySelectorAll(".timegrid-col")].flatMap((col) =>
          [...col.querySelectorAll(".event-block")]
            .filter((b) => b.offsetLeft < -1 || b.offsetLeft + b.offsetWidth > col.clientWidth + 1)
            .map((b) => b.textContent)
        )
      );
      expect(escaping, "event blocks escaping their column").toEqual([]);

      // All-day events must land in the all-day band, never in the timed grid.
      expect(await page.locator(".timegrid-allday-col .event-pill").count()).toBeGreaterThan(0);

      // The whole day should be on screen at once - the grid stretches its
      // hours to fit, so needing to scroll a normal week means the available
      // height was mismeasured (which it was, when the all-day band was still
      // empty at measuring time).
      const scroll = await page.evaluate(() => {
        const el = document.getElementById("timegrid-scroll");
        return { top: el.scrollTop, scrollH: el.scrollHeight, clientH: el.clientHeight };
      });
      expect(scroll.scrollH, "time grid overflows its viewport").toBeLessThanOrEqual(scroll.clientH + 1);
      expect(scroll.top, "time grid opened scrolled").toBe(0);

      // Back-to-back short events (School dropoff 8:45-9:00, Standup 9:00-9:20)
      // are each drawn taller than their real duration to stay tappable, so the
      // packer has to treat them as overlapping and put them side by side
      // rather than stacking one invisibly under the other.
      const backToBack = await page.evaluate(() =>
        [...document.querySelectorAll(".timegrid-col")].map((col) =>
          [...col.querySelectorAll(".event-block")]
            .filter((b) => ["School dropoff", "Standup"]
              .includes(b.querySelector(".event-block-title")?.textContent))
            .map((b) => Math.round(b.offsetLeft))
        ).filter((lefts) => lefts.length === 2)
      );
      expect(backToBack.length, "no weekday with both short events").toBeGreaterThan(0);
      backToBack.forEach((lefts) => {
        expect(new Set(lefts).size, "short adjacent events stacked on each other").toBe(2);
      });

      await expectNoHorizontalOverflow(page, "week");
      await shoot(page, `${vp.name}-week`);
    });

    test("day view lays concurrent events side by side", async ({ page }) => {
      await page.goto("/");
      await switchView(page, "day");

      await expect(page.locator(".timegrid-col")).toHaveCount(1);
      await expect(page.locator(".now-line")).toHaveCount(1);

      // The detail pane is what stops a single column from being stretched
      // across the whole landscape screen.
      await expect(page.locator("#day-detail")).toBeVisible();
      expect(await page.locator("#day-detail-list .event-card").count()).toBeGreaterThan(5);
      const gridWidth = await page.evaluate(() => document.getElementById("timegrid").clientWidth);
      const stageWidth = await page.evaluate(() => document.getElementById("content").clientWidth);
      expect(gridWidth).toBeLessThan(stageWidth * 0.85);

      // Detail cards must stack time-over-title-over-meta, not collapse onto a
      // single line (which is what inheriting .row-list's flex row did).
      const stacked = await page.evaluate(() => {
        const card = document.querySelector("#day-detail-list .event-card");
        const time = card.querySelector(".event-card-time").getBoundingClientRect();
        const title = card.querySelector(".event-card-title").getBoundingClientRect();
        return title.top >= time.bottom - 1;
      });
      expect(stacked, "detail card fields laid out side by side").toBe(true);

      // Today's fixtures include three events overlapping between 14:00 and
      // 16:00 (Dentist / Plumber window / Pickup order ready). If the overlap
      // packing works they occupy three distinct columns; if it silently fails
      // they stack on top of each other at left: 0 and full width.
      const afternoon = await page.evaluate(() =>
        [...document.querySelectorAll(".event-block")]
          .filter((b) => ["Dentist", "Plumber window", "Pickup order ready"]
            .includes(b.querySelector(".event-block-title")?.textContent))
          .map((b) => ({
            title: b.querySelector(".event-block-title").textContent,
            left: Math.round(b.offsetLeft),
            width: Math.round(b.offsetWidth),
          }))
      );
      expect(afternoon).toHaveLength(3);
      const lefts = new Set(afternoon.map((b) => b.left));
      expect(lefts.size, "overlapping events share a left offset").toBe(3);
      const colWidth = await page.evaluate(() => document.querySelector(".timegrid-col").clientWidth);
      afternoon.forEach((b) => {
        expect(b.width).toBeLessThan(colWidth * 0.7);
      });

      await expectNoHorizontalOverflow(page, "day");
      await shoot(page, `${vp.name}-day`);
    });

    test("agenda view uses the full width", async ({ page }) => {
      await page.goto("/");
      await switchView(page, "agenda");

      expect(await page.locator(".agenda-day-group").count()).toBeGreaterThan(5);
      await expectNoHorizontalOverflow(page, "agenda");
      await shoot(page, `${vp.name}-agenda`);
    });

    test("day overlay and event edit sheet fit on screen", async ({ page }) => {
      await page.goto("/");
      // Aim at the day number: the centre of a cell is now covered by the span-bar
      // layer, and a tap there is meant to open that event, not the day.
      await page.locator("#month-grid .day-cell.today .day-number").click();
      await expect(page.locator("#day-overlay")).toBeVisible();

      const panelFits = await page.evaluate(() => {
        const p = document.getElementById("day-overlay-panel").getBoundingClientRect();
        return p.top >= -1 && p.bottom <= window.innerHeight + 1 && p.left >= -1 && p.right <= window.innerWidth + 1;
      });
      expect(panelFits, "day overlay panel off-screen").toBe(true);

      // It has to be an actual overlay, not just something that happens to fit.
      // .modal-overlay was silently dead for a long time - an unescaped */ inside
      // the comment above it ended the comment early and the resulting broken
      // selector swallowed the rule - so this panel rendered inline in the page
      // flow, squeezing the calendar sideways. "It fits on screen" was true the
      // whole time, which is why nothing caught it.
      const overlays = await page.evaluate(() => {
        const overlay = document.getElementById("day-overlay");
        const style = getComputedStyle(overlay);
        const rect = document.getElementById("day-overlay-panel").getBoundingClientRect();
        return {
          position: style.position,
          hasBackdrop: style.backgroundColor !== "rgba(0, 0, 0, 0)",
          horizontallyCentered: Math.abs(rect.x + rect.width / 2 - window.innerWidth / 2) < 4,
        };
      });
      expect(overlays, "day overlay is not overlaying").toEqual({
        position: "fixed",
        hasBackdrop: true,
        horizontallyCentered: true,
      });
      await shoot(page, `${vp.name}-day-overlay`);

      // Tapping an event in the overlay must open the edit sheet - this is the
      // path that previously only existed from month view.
      await page.locator("#day-overlay-events .event-card--editable").first().click();
      await expect(page.locator("#add-event-overlay")).toBeVisible();
      await expect(page.locator("#add-event-heading")).toHaveText("Edit Event");
      await expect(page.locator("#add-event-title")).not.toHaveValue("");

      const sheetFits = await page.evaluate(() => {
        const p = document.getElementById("add-event-panel").getBoundingClientRect();
        return p.top >= -1 && p.bottom <= window.innerHeight + 1;
      });
      expect(sheetFits, "edit sheet off-screen").toBe(true);
      await shoot(page, `${vp.name}-edit-sheet`);
    });

    test("week events are tappable to edit", async ({ page }) => {
      await page.goto("/");
      await switchView(page, "week");
      await page.locator(".event-block.event-card--editable").first().click();
      await expect(page.locator("#add-event-overlay")).toBeVisible();
      await expect(page.locator("#add-event-heading")).toHaveText("Edit Event");
    });

    test("survives the wider font the Pi will actually use", async ({ page }) => {
      await page.goto("/");
      await page.addStyleTag({ content: WIDE_FONT_CSS });
      // Re-render so measured pills-per-cell reflects the wider metrics.
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await page.waitForTimeout(500);

      const spilling = await page.evaluate(() =>
        [...document.querySelectorAll(".day-cell")]
          .filter((c) => c.scrollHeight > c.clientHeight + 1).length
      );
      expect(spilling, "day cells clip under a wider font").toBe(0);
      await expectNoHorizontalOverflow(page, "month/wide-font");
      await shoot(page, `${vp.name}-month-wide-font`);

      await switchView(page, "week");
      await expectNoHorizontalOverflow(page, "week/wide-font");
      await shoot(page, `${vp.name}-week-wide-font`);
    });
  });
}

test.describe("shell", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // The rail replaced a hamburger drawer, so every page's chrome changed. These
  // pages are otherwise untouched (the Spotify UI deliberately so) - this is
  // here to catch the shell regressing them.
  for (const [path, label] of [["/", "Calendar"], ["/spotify", "Music"], ["/browser", "Web"], ["/accounts", "Accounts"]]) {
    test(`${path} renders in the shell without console errors`, async ({ page }) => {
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

      await page.goto(path);
      await expect(page.locator("#rail")).toBeVisible();
      await expect(page.locator("#clock-time")).not.toBeEmpty();
      await expect(page.locator("#clock-date")).not.toBeEmpty();
      // Exactly one rail entry is marked active, and it's this page's.
      await expect(page.locator(".rail-item.active")).toHaveCount(1);
      await expect(page.locator(".rail-item.active")).toContainText(label);
      await expectNoHorizontalOverflow(page, path);

      // Spotify's endpoints need a real signed-in account, which demo mode
      // doesn't provide - failed fetches are expected there and aren't a shell
      // regression. Everywhere else the page must be clean.
      if (path !== "/spotify") {
        expect(errors, `console errors on ${path}`).toEqual([]);
      }
      await shoot(page, `shell${path === "/" ? "-calendar" : path.replace("/", "-")}`);
    });
  }
});

test.describe("weather", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("the chip reads on every page and opens a forecast", async ({ page }) => {
    await page.goto("/");
    const chip = page.locator("#weather-chip");
    await expect(chip).toBeVisible();
    await expect(page.locator("#weather-temp")).toHaveText(/^-?\d+°$/);
    await expect(page.locator("#weather-icon svg")).toBeVisible();

    // The header already carries a clock, month nav, view switcher and actions -
    // weather must not be what tips it into overflowing.
    const headerFits = await page.evaluate(() => {
      const bar = document.getElementById("top-bar");
      return bar.scrollWidth <= bar.clientWidth + 1;
    });
    expect(headerFits, "top bar overflows once weather is added").toBe(true);

    await chip.click();
    await expect(page.locator("#weather-overlay")).toBeVisible();
    // 4 days: today plus three.
    await expect(page.locator(".forecast-day")).toHaveCount(4);
    // Fixtures deliberately vary the codes, so a single repeated icon means the
    // code-to-icon mapping collapsed.
    const icons = await page.evaluate(() =>
      [...new Set([...document.querySelectorAll(".forecast-icon svg path, .forecast-icon svg circle")]
        .map((el) => el.getAttribute("d") || "circle"))].length
    );
    expect(icons, "forecast icons are all identical").toBeGreaterThan(1);
    await shoot(page, "weather-panel");

    // It's shell furniture, so it belongs on the other pages too.
    await page.goto("/spotify");
    await expect(page.locator("#weather-chip")).toBeVisible();
  });
});

test.describe("person colors", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // The contract of calendar_service._person_color is that each signed-in
  // account gets a distinct color, since that's the only thing distinguishing
  // whose event is whose at a glance. The server here runs with two accounts
  // (see playwright.config.js), so two colors must actually reach the page.
  //
  // The single-account case - which is what the real wall is in today - can't be
  // exercised against this server; it was verified separately by rendering
  // against the live account.
  test("each account gets a distinct color", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();
    const colors = await page.evaluate(() =>
      [...new Set([...document.querySelectorAll(".event-dot, .event-pill:not(.event-pill--timed)")]
        .map((el) => getComputedStyle(el).backgroundColor))]
    );
    expect(colors.length, `expected 2 distinct person colors, got ${colors}`).toBe(2);
  });
});

test.describe("no accounts connected", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // Served by the zero-accounts instance on :5001 (see playwright.config.js).
  // Before this state existed, an unconfigured wall showed an empty grid with
  // nothing explaining why.
  test("empty state covers the grid and points at Accounts", async ({ page }) => {
    await page.goto("http://127.0.0.1:5001/");
    const empty = page.locator("#no-accounts");
    await expect(empty).toBeVisible();
    await expect(empty.locator("a")).toHaveAttribute("href", "/accounts");

    // It has to paint *over* the grid, not sit behind it - it's an absolute fill
    // and the stacking depends on #calendar-view being a positioned ancestor.
    const covers = await page.evaluate(() => {
      const el = document.getElementById("no-accounts");
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + 20);
      return el.contains(hit);
    });
    expect(covers, "empty state is behind the calendar grid").toBe(true);
    await shoot(page, "empty-state");
  });
});

test.describe("kiosk longevity", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // The now-line reschedules itself every minute over the set of days it was
  // rendered with. Navigating away has to cancel that, or a minute later the
  // stale timer draws today's line into whatever column index today used to
  // occupy - in a different week, or a column that doesn't exist at all in
  // single-column day view. A wall runs for weeks, so this would surface as
  // "the calendar randomly grows red lines" rather than as an obvious bug.
  // Tapping through months faster than the API answers used to let a slow
  // response for a month you'd left land after a faster one, so the header said
  // August while the grid showed September. Found by driving the real app; very
  // reachable on a Pi over wifi.
  test("a slow response for an abandoned month never wins", async ({ page }) => {
    await page.route("**/api/calendar/2026/9", async (route) => {
      await new Promise((r) => setTimeout(r, 2000));
      await route.continue();
    });
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    // Jump to a known month so the assertion doesn't depend on today's date.
    await page.evaluate(() => {
      document.querySelector('.view-tab[data-view="month"]').click();
    });
    await page.waitForTimeout(500);

    await page.click("#next-month");   // September, slow
    await page.waitForTimeout(150);
    await page.click("#today-jump");   // back to this month, fast - must win
    await page.waitForTimeout(2600);   // let the abandoned September land

    const shown = await page.evaluate(() => {
      const nums = [...document.querySelectorAll("#month-grid .day-cell:not(.outside-month) .day-number")];
      return { days: nums.length, label: document.getElementById("month-label").textContent };
    });
    const expectedDays = new Date(
      new Date().getFullYear(), new Date().getMonth() + 1, 0
    ).getDate();
    expect(shown.days, `grid shows a different month than the header ("${shown.label}")`)
      .toBe(expectedDays);
  });

  /* Pushing to main restarts Flask, but nothing restarts the kiosk browser - it
     holds the same document from boot, so it keeps rendering the CSS it loaded
     then. A deploy of the light theme succeeded on every measure except being
     visible on the wall. The client now polls the build and reloads itself. */
  test("a new build reloads the wall", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    // Survives only until a reload, which is how the reload gets detected.
    await page.evaluate(() => { window.__beforeDeploy = true; });

    await page.route("**/api/version", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ build: "a-different-build", started_at: 1 }),
      })
    );

    // Poll on a timer in production; called directly here rather than waiting a
    // minute for it.
    await page.evaluate(() => checkBuild());
    await page.waitForFunction(() => window.__beforeDeploy === undefined, null, { timeout: 5000 });
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();
  });

  test("an unchanged build does not reload the wall", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");
    await page.evaluate(() => { window.__beforeDeploy = true; });

    // Reloading on every poll would restart the page each minute forever, which
    // is a far worse failure than a stale one.
    await page.evaluate(async () => { await checkBuild(); await checkBuild(); });
    await page.waitForTimeout(600);
    expect(await page.evaluate(() => window.__beforeDeploy)).toBe(true);
  });

  test("navigating away cancels the now-line timer", async ({ page }) => {
    await page.clock.install();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto("/");
    await switchView(page, "week");
    await expect(page.locator(".now-line")).toHaveCount(1);

    await page.click("#next-month");
    await page.waitForTimeout(400);
    await expect(page.locator(".now-line")).toHaveCount(0);

    // Let the minute tick pass. A leaked timer re-adds the line here.
    await page.clock.fastForward("02:00");
    await page.waitForTimeout(200);
    await expect(page.locator(".now-line"), "stale timer redrew the now-line").toHaveCount(0);

    // And a leaked week-shaped timer firing against a one-column day grid
    // indexes past the end of the columns.
    await switchView(page, "day");
    await page.clock.fastForward("02:00");
    await page.waitForTimeout(200);
    expect(errors, "stale now-line timer threw").toEqual([]);
  });
});
