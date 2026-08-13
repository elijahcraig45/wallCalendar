/* Today / Notes / Recipes / timers / dimming / themes.
 *
 * Same lesson as the other specs: assert geometry and behaviour, not counts. Most
 * of the bugs these cover were "the element was present and correct and simply
 * would not go away", which a count-based test passes happily.
 */

const path = require("path");
const { test, expect } = require("@playwright/test");

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "..", "test-results", "shots");
const VIEWPORTS = [
  { name: "1024x600", width: 1024, height: 600 },
  { name: "1920x1080", width: 1920, height: 1080 },
];

async function shoot(page, name) {
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
}

async function expectNoSidewaysScroll(page, label) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(overflow, `${label} scrolls sideways`).toBeLessThanOrEqual(1);
}

for (const vp of VIEWPORTS) {
  test.describe(`new pages ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("every page renders clean in the shell", async ({ page }) => {
      for (const target of ["/today", "/notes", "/recipes"]) {
        const problems = [];
        page.on("pageerror", (e) => problems.push(`${target} pageerror: ${e.message}`));
        page.on("console", (m) => {
          if (m.type() === "error") problems.push(`${target} console: ${m.text()}`);
        });
        await page.goto(target);
        await page.waitForTimeout(1200);
        // 7 destinations now; the rail has to still fit a 600px panel.
        await expect(page.locator(".rail-item")).toHaveCount(7);
        const railFits = await page.evaluate(() => {
          const rail = document.getElementById("rail");
          return rail.scrollHeight <= rail.clientHeight + 1;
        });
        expect(railFits, `${target}: rail overflows at ${vp.name}`).toBe(true);
        await expectNoSidewaysScroll(page, target);
        expect(problems, `errors on ${target}`).toEqual([]);
        await shoot(page, `feat-${vp.name}-${target.slice(1)}`);
      }
    });
  });
}

test.describe("today overview", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("composes weather, today's events, notes and the week", async ({ page }) => {
    await page.goto("/today");
    await expect(page.locator(".today-weather-temp")).toHaveText(/^-?\d+°$/);
    // The fixtures put 9 events on today.
    expect(await page.locator("#today-events .today-event").count()).toBeGreaterThan(4);
    expect(await page.locator("#today-notes .today-note").count()).toBeGreaterThan(1);
    expect(await page.locator("#today-next .today-event").count()).toBeGreaterThan(1);

    // Past events are dimmed rather than dropped - "did I miss it" is a question
    // people ask the wall.
    const dimmed = await page.locator(".today-event--past").count();
    expect(dimmed, "nothing marked past despite morning fixtures").toBeGreaterThan(0);
  });
});

test.describe("notes", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("adds, completes and deletes", async ({ page }) => {
    await page.goto("/notes");
    await expect(page.locator(".note-row").first()).toBeVisible();
    const before = await page.locator(".note-row").count();

    const title = `Test note ${Date.now()}`;
    await page.fill("#note-input", title);
    await page.press("#note-input", "Enter");
    // New note is newest-updated, so it leads the open items.
    await expect(page.locator(".note-text").first()).toHaveText(new RegExp(title));
    expect(await page.locator(".note-row").count()).toBe(before + 1);

    // Completing must strike it through, not just record a flag.
    const row = page.locator(".note-row").first();
    await row.locator(".note-check").click();
    await expect.poll(async () =>
      page.evaluate((text) => {
        const el = [...document.querySelectorAll(".note-row")]
          .find((r) => r.textContent.includes(text));
        return el ? getComputedStyle(el.querySelector(".note-text")).textDecorationLine : "none";
      }, title)
    ).toContain("line-through");

    const afterComplete = await page.locator(".note-row").count();
    await page.locator(".note-row", { hasText: title }).locator(".note-delete").click();
    await expect.poll(() => page.locator(".note-row").count()).toBe(afterComplete - 1);
  });
});

test.describe("recipes", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  // The three views are switched, not navigated. They each set `display` on an ID,
  // which outranks .hidden - so all three rendered stacked on top of each other
  // until .hidden was made !important. Checking rendered height, not the class.
  test("shows exactly one view at a time", async ({ page }) => {
    await page.goto("/recipes");
    await expect(page.locator(".recipe-card").first()).toBeVisible();

    const heights = () =>
      page.evaluate(() => ({
        browse: document.getElementById("recipes-browse").offsetHeight > 0,
        detail: document.getElementById("recipe-detail").offsetHeight > 0,
        cook: document.getElementById("cook-mode").offsetHeight > 0,
      }));

    expect(await heights()).toEqual({ browse: true, detail: false, cook: false });

    await page.locator(".recipe-card").first().click();
    await expect(page.locator(".recipe-detail-title")).not.toBeEmpty();
    expect(await heights()).toEqual({ browse: false, detail: true, cook: false });
    expect(await page.locator(".ingredient-list li").count()).toBeGreaterThan(2);
    expect(await page.locator(".step-list li").count()).toBeGreaterThan(2);

    await page.click("#cook-start");
    expect(await heights()).toEqual({ browse: false, detail: false, cook: true });
    await expect(page.locator("#cook-progress")).toHaveText(/Step 1 of \d+/);

    await page.click("#recipes-back");
    expect(await heights()).toEqual({ browse: true, detail: false, cook: false });
  });

  test("cooking mode steps forward and starts a step's timer", async ({ page }) => {
    await page.goto("/recipes");
    await page.locator(".recipe-card").first().click();
    await page.click("#cook-start");

    // Walk to a step that declares a timer. Only steps that actually specify one
    // offer it - inventing a duration would be worse than not offering it.
    let offered = false;
    for (let i = 0; i < 8; i += 1) {
      if (await page.locator("#cook-timer").isVisible()) { offered = true; break; }
      if (await page.locator("#cook-next").textContent() === "Finish") break;
      await page.click("#cook-next");
    }
    expect(offered, "no step in the first recipe offered a timer").toBe(true);

    await page.click("#cook-timer");
    // Started from a recipe, owned by the shell.
    await expect(page.locator("#timer-chip-text")).toHaveText(/^\d+:\d\d$/);
    await expect(page.locator("#timer-chip")).toHaveClass(/running/);
  });
});

test.describe("kitchen timers", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a timer survives navigating between pages", async ({ page }) => {
    await page.goto("/");
    await page.click("#timer-chip");
    await page.locator("#timer-presets button", { hasText: /^5m$/ }).click();
    await expect(page.locator("#timer-chip-text")).toHaveText(/^[45]:\d\d$/);

    // The whole reason state is absolute timestamps in localStorage rather than a
    // countdown variable: a timer set while cooking has to outlive the page.
    await page.goto("/recipes");
    await expect(page.locator("#timer-chip")).toHaveClass(/running/);
    await expect(page.locator("#timer-chip-text")).toHaveText(/^[45]:\d\d$/);

    await page.click("#timer-chip");
    await expect(page.locator(".timer-row")).toHaveCount(1);
    await page.locator(".timer-row .pill-button").click();
    await expect(page.locator("#timer-chip-text")).toHaveText("");
  });

  test("fires, chimes visually and can be dismissed", async ({ page }) => {
    await page.clock.install();
    await page.goto("/");
    await page.click("#timer-chip");
    await page.fill("#timer-minutes", "2");
    await page.locator("#timer-form button[type=submit]").click();
    await expect(page.locator("#timer-chip-text")).toHaveText(/^[12]:\d\d$/);

    await page.clock.fastForward("02:05");
    await expect(page.locator("#timer-chip")).toHaveClass(/ringing/);
    await expect(page.locator("#timer-chip-text")).toHaveText("Done!");
    await expect(page.locator(".timer-row--done")).toHaveCount(1);

    await page.locator(".timer-row .pill-button", { hasText: "Dismiss" }).click();
    await expect(page.locator("#timer-chip")).not.toHaveClass(/ringing/);
  });
});

test.describe("ambient and themes", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("monthly theme moves the accent but never the text colour", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();

    const read = () =>
      page.evaluate(() => ({
        accent: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(),
        text: getComputedStyle(document.documentElement).getPropertyValue("--text").trim(),
        bg: getComputedStyle(document.documentElement).getPropertyValue("--bg").trim(),
      }));

    const first = await read();
    expect(first.accent).toMatch(/^#/);

    // Six months on is guaranteed to be a different season, so a different accent.
    for (let i = 0; i < 6; i += 1) await page.click("#next-month");
    await page.waitForTimeout(600);
    const later = await read();

    expect(later.accent, "accent did not change across seasons").not.toBe(first.accent);
    // Legibility is not up for negotiation: only the accent moves.
    expect(later.text).toBe(first.text);
    expect(later.bg).toBe(first.bg);
  });

  test("night dimming can be turned on by the clock and woken by a touch", async ({ page }) => {
    // 3am: night under any schedule, real sunset or the fallback window.
    await page.clock.install({ time: new Date("2026-08-13T03:00:00") });
    await page.goto("/");
    await page.waitForTimeout(800);

    const dimOpacity = () =>
      page.evaluate(() => parseFloat(getComputedStyle(document.getElementById("night-dim")).opacity));
    await expect.poll(dimOpacity).toBeGreaterThan(0.5);

    // A touch has to wake it, or the wall is unusable at night.
    await page.mouse.click(640, 400);
    await expect.poll(dimOpacity).toBe(0);
    await shoot(page, "feat-night-woken");
  });
});
