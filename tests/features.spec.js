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
      for (const target of ["/today", "/recipes"]) {
        const problems = [];
        page.on("pageerror", (e) => problems.push(`${target} pageerror: ${e.message}`));
        page.on("console", (m) => {
          if (m.type() === "error") problems.push(`${target} console: ${m.text()}`);
        });
        await page.goto(target);
        await page.waitForTimeout(1200);
        // 6 destinations; the rail has to still fit a 600px panel.
        await expect(page.locator(".rail-item")).toHaveCount(6);
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
    expect(await page.locator("#today-next .today-event").count()).toBeGreaterThan(1);

    // Past events are dimmed rather than dropped - "did I miss it" is a question
    // people ask the wall.
    const dimmed = await page.locator(".today-event--past").count();
    expect(dimmed, "nothing marked past despite morning fixtures").toBeGreaterThan(0);
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

test.describe("multi-day events and colours", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  // A four-day trip used to render as four separate one-day chips, which is the
  // most misleading thing a month view can do.
  test("a multi-day event is one bar spanning its days", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();

    const bars = await page.evaluate(() => {
      const cellW = document.querySelector(".day-cell").getBoundingClientRect().width;
      return [...document.querySelectorAll(".span-bar:not(.span-bar--more)")].map((b) => ({
        title: b.textContent.replace(/^\u2039\s*/, "").trim(),
        days: Math.round(b.getBoundingClientRect().width / cellW),
        openLeft: b.classList.contains("span-bar--open-left"),
        openRight: b.classList.contains("span-bar--open-right"),
      }));
    });

    // "Grandma visiting" is a six-day fixture; it must be a single wide bar, not
    // six chips.
    const grandma = bars.filter((b) => b.title === "Grandma visiting");
    expect(grandma.length, "Grandma visiting should be one bar in its week").toBe(1);
    expect(grandma[0].days, "not spanning multiple days").toBeGreaterThan(3);

    // "Asheville trip" deliberately crosses a Sat->Sun boundary, so it must split
    // into two bars whose touching ends are squared off rather than rounded.
    const asheville = bars.filter((b) => b.title === "Asheville trip");
    expect(asheville.length, "week-crossing event should split into two bars").toBe(2);
    expect(asheville.some((b) => b.openRight), "first half should run off the week edge").toBe(true);
    expect(asheville.some((b) => b.openLeft), "second half should continue from the previous week").toBe(true);

    // Nothing all-day should still be rendering as a per-day pill.
    const allDayPills = await page.locator(".event-pill:not(.event-pill--timed)").count();
    expect(allDayPills, "all-day events still drawn as per-day pills").toBe(0);
    await shoot(page, "feat-multiday-spans");
  });

  // Colours come from Google now: an event takes its calendar's colour, so the
  // wall matches what the household sees on their phones.
  test("events are coloured per calendar, with readable text", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".span-bar").first()).toBeVisible();

    const shades = await page.evaluate(() =>
      [...new Set([...document.querySelectorAll(".span-bar:not(.span-bar--more)")]
        .map((b) => getComputedStyle(b).backgroundColor))]
    );
    expect(shades.length, "every calendar rendered the same colour").toBeGreaterThan(1);

    // Google's palette is light chips with dark text. Using white on #fbd75b would
    // be unreadable, so the foreground it hands us has to be carried through.
    const contrast = await page.evaluate(() =>
      [...document.querySelectorAll(".span-bar:not(.span-bar--more)")].map((b) => {
        const lum = (c) => {
          const [r, g, bl] = c.match(/\d+/g).map(Number);
          return (0.2126 * r + 0.7152 * g + 0.0722 * bl) / 255;
        };
        const st = getComputedStyle(b);
        return Math.abs(lum(st.backgroundColor) - lum(st.color));
      })
    );
    contrast.forEach((delta) =>
      expect(delta, "event chip text has almost no contrast against its fill").toBeGreaterThan(0.35)
    );
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

    // A theme now sets its own ground as well as its accent, so --bg is expected
    // to move. What must never move is the text colour, and the ground must stay
    // dark enough for that white text to work - which is the actual invariant the
    // original assertion was reaching for.
    expect(later.text).toBe(first.text);
    for (const shade of [first.bg, later.bg]) {
      const [r, g, b] = shade.replace("#", "").match(/../g).map((h) => parseInt(h, 16));
      const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      expect(luminance, `theme ground ${shade} is too light for white text`).toBeLessThan(0.25);
    }
  });

  // The whole point of themes.js is that someone can author one without editing
  // code, so the localStorage path is the contract that matters.
  test("a custom theme can be pinned from localStorage", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() =>
      localStorage.setItem("wallcal_theme", JSON.stringify({
        name: "test-theme", accent: "#8a6fd4", secondary: "#4b3b7a",
        base: "#13111c", surface: "#1e1b2b", lines: "#3a3352", strength: 1.4,
      }))
    );
    await page.reload();
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();

    const applied = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      return {
        name: document.documentElement.dataset.theme,
        accent: cs.getPropertyValue("--accent").trim(),
        base: cs.getPropertyValue("--bg").trim(),
        lines: cs.getPropertyValue("--grid-line").trim(),
        strength: cs.getPropertyValue("--theme-strength").trim(),
      };
    });
    expect(applied).toEqual({
      name: "test-theme", accent: "#8a6fd4", base: "#13111c",
      lines: "#3a3352", strength: "1.4",
    });

    // A one-colour theme must still be valid - everything else is derived.
    await page.evaluate(() =>
      localStorage.setItem("wallcal_theme", JSON.stringify({ name: "minimal", accent: "#3fa7d6" }))
    );
    await page.reload();
    await expect(page.locator("#month-grid .day-cell").first()).toBeVisible();
    const derived = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      return {
        accent: cs.getPropertyValue("--accent").trim(),
        secondary: cs.getPropertyValue("--accent2").trim(),
        lines: cs.getPropertyValue("--grid-line").trim(),
      };
    });
    expect(derived.accent).toBe("#3fa7d6");
    expect(derived.secondary, "secondary was not derived from accent").toMatch(/^#[0-9a-f]{6}$/i);
    expect(derived.lines, "grid line colour was not derived").toMatch(/^#[0-9a-f]{6}$/i);
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
