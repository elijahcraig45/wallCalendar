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

    /* A fresh tab per page, deliberately. Walking all three with one `page` made
       this flaky: navigating away cancels whatever fetch the previous page had in
       flight, Chromium logs that as a console error, and the listener belonging to
       the NEXT page catches it - a failure with nothing wrong with the page named
       in the message. Error listeners also accumulated across iterations. */
    test("every page renders clean in the shell", async ({ context }) => {
      for (const target of ["/today", "/weather", "/recipes"]) {
        const page = await context.newPage();
        const problems = [];
        page.on("pageerror", (e) => problems.push(`${target} pageerror: ${e.message}`));
        page.on("console", (m) => {
          if (m.type() === "error") problems.push(`${target} console: ${m.text()}`);
        });
        await page.goto(target);
        await page.waitForTimeout(1200);
        // 7 destinations now that Weather has its own page; the rail still has
        // to fit a 600px panel, which is what the overflow check below is for.
        await expect(page.locator(".rail-item")).toHaveCount(7);
        const railFits = await page.evaluate(() => {
          const rail = document.getElementById("rail");
          return rail.scrollHeight <= rail.clientHeight + 1;
        });
        expect(railFits, `${target}: rail overflows at ${vp.name}`).toBe(true);
        await expectNoSidewaysScroll(page, target);
        expect(problems, `errors on ${target}`).toEqual([]);
        await shoot(page, `feat-${vp.name}-${target.slice(1)}`);
        await page.close();
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

    /* Asserted by total span rather than bar count, because the fixtures are offsets
       from TODAY: which events cross a Saturday->Sunday boundary changes daily, so a
       hard-coded "exactly one bar" is only true on some days of the week. This test
       failed the morning the date rolled over — the rendering was right and the
       assertion was a coincidence.

       The invariants that actually matter: a multi-day event spans, it never becomes
       per-day chips, its widths add up to its length, and where it does split across
       week rows the touching ends are squared off. */
    const grandma = bars.filter((b) => b.title === "Grandma visiting");
    expect(grandma.length, "Grandma visiting is missing entirely").toBeGreaterThan(0);
    expect(grandma.length, "a 6-day event cannot need more than two week rows")
      .toBeLessThanOrEqual(2);
    expect(
      grandma.reduce((total, b) => total + b.days, 0),
      "the bars should add up to the fixture's six days",
    ).toBe(6);

    // Whenever anything is split, the cut ends must be marked so they render squared
    // rather than rounded — that is what makes it read as one event across two rows.
    for (const title of new Set(bars.map((b) => b.title))) {
      const parts = bars.filter((b) => b.title === title);
      if (parts.length < 2) continue;
      expect(parts.some((b) => b.openRight), `${title}: no bar runs off a week edge`).toBe(true);
      expect(parts.some((b) => b.openLeft), `${title}: no bar continues a previous week`).toBe(true);
    }

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

    // A theme sets its own ground AND its text, so neither is fixed. The real
    // invariant - the one both earlier versions of this assertion were groping
    // for - is that body text stays readable against the surface it sits on,
    // whichever direction the palette goes.
    for (const shade of [first, later]) {
      const contrast = await page.evaluate(() => {
        const lum = (css) => {
          const [r, g, b] = css.match(/\d+/g).map(Number).map((v) => {
            const c = v / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const cell = document.querySelector(".day-cell:not(.today):not(.outside-month)");
        const a = lum(getComputedStyle(cell).backgroundColor);
        const b = lum(getComputedStyle(cell.querySelector(".day-number")).color);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      });
      // 4.5:1 is the WCAG AA threshold for body text.
      expect(contrast, `theme ${shade.accent} leaves text unreadable on its cells`)
        .toBeGreaterThan(4.5);
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
        lines: cs.getPropertyValue("--border").trim(),
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
        text: cs.getPropertyValue("--text").trim(),
        lines: cs.getPropertyValue("--border").trim(),
      };
    });
    expect(derived.accent).toBe("#3fa7d6");
    expect(derived.lines, "grid line colour was not derived").toMatch(/^#[0-9a-f]{6}$/i);
    // A one-field theme still has to produce readable text, which means the
    // resolver picked it from the ground's lightness rather than leaving it unset.
    expect(derived.text, "text colour was not derived").toMatch(/^#[0-9a-f]{6}$/i);
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

test.describe("light-theme contrast sweep", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  /* This app was built dark and converted to a light ground. That conversion
     touches every surface, and the failure mode is silent: a rule that hardcoded
     white text, or a faint white-over-dark overlay, still "works" - it just
     becomes invisible. So rather than trusting the sweep of replacements, this
     walks every visible text node on every page and measures the contrast it
     actually renders at. */
  const measure = () => {
        const channel = (v) => {
          const c = v / 255;
          return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        };
        const parse = (css) => {
          const m = (css || "").match(/[\d.]+/g);
          if (!m) return null;
          const [r, g, b, a] = m.map(Number);
          return { r, g, b, a: a === undefined ? 1 : a };
        };
        const relLum = ({ r, g, b }) =>
          0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);

        /* Backgrounds have to be COMPOSITED, not just read. Nearly every faint
           fill here is translucent (rgba(0,0,0,0.04) over white, today's cell is
           the accent at 10%), and reading those as opaque colours reports pale
           peach as near-black - which produced a page of confident false
           positives the first time this ran. */
        const effectiveBg = (el) => {
          const layers = [];
          for (let n = el; n; n = n.parentElement) {
            const c = parse(getComputedStyle(n).backgroundColor);
            if (!c || c.a === 0) continue;
            layers.push(c);
            if (c.a >= 1) break;
          }
          // Assume the page sits on white if nothing opaque was found.
          let out = { r: 255, g: 255, b: 255 };
          for (let i = layers.length - 1; i >= 0; i -= 1) {
            const l = layers[i];
            out = {
              r: l.r * l.a + out.r * (1 - l.a),
              g: l.g * l.a + out.g * (1 - l.a),
              b: l.b * l.a + out.b * (1 - l.a),
            };
          }
          return relLum(out);
        };

        const bad = [];
        document.querySelectorAll("body *").forEach((el) => {
          const text = [...el.childNodes]
            .filter((n) => n.nodeType === 3 && n.textContent.trim())
            .map((n) => n.textContent.trim())
            .join(" ");
          if (!text) return;
          const style = getComputedStyle(el);
          if (style.visibility === "hidden" || style.display === "none") return;
          if (parseFloat(style.opacity) < 0.35) return;   // deliberately dimmed
          const rect = el.getBoundingClientRect();
          if (rect.width < 4 || rect.height < 4) return;

          const fgColor = parse(style.color);
          if (!fgColor || fgColor.a === 0) return;
          const fg = relLum(fgColor);
          const bg = effectiveBg(el);
          const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
          // 3:1 rather than 4.5:1 - most of this is large or semibold, and the
          // point is catching invisible text, not auditing to spec.
          if (ratio < 3) {
            bad.push({
              where: el.className || el.tagName,
              text: text.slice(0, 30),
              ratio: Math.round(ratio * 100) / 100,
            });
          }
        });
        return bad;
      };

  const findOffenders = (page) => page.evaluate(measure);

  for (const target of ["/", "/today", "/weather", "/recipes", "/browser", "/accounts", "/spotify"]) {
    test(`no unreadable text on ${target}`, async ({ page }) => {
      await page.goto(target);
      await page.waitForTimeout(1600);
      const offenders = await findOffenders(page);
      expect(offenders, `unreadable text on ${target}`).toEqual([]);
    });
  }

  /* Today's cell is a translucent accent tint, and what sits UNDER it decides
     what colour that becomes. .week-cells is painted with --border and the cells
     sit on it with 1px gaps - that's how the grid is drawn - so a bare
     `background: <tint>` on today replaced the white surface and composited the
     accent over the grid-LINE colour. It rendered #e9ddd1 (a tan block) where
     #fcf7f3 was intended, and on the old dark theme the same bug is what produced
     the "muddy brown haze" the theme was rewritten twice to remove.

     Comparing against a normal cell rather than asserting a fixed colour, so this
     holds for any palette: today should read as the same paper, faintly tinted. */
  test("today's cell is a tint of the paper, not a different colour", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell.today");

    const { today, plain } = await page.evaluate(() => {
      const parse = (css) => {
        const m = (css || "").match(/[\d.]+/g);
        if (!m) return null;
        const [r, g, b, a] = m.map(Number);
        return { r, g, b, a: a === undefined ? 1 : a };
      };
      // Composite the element's own background over its ancestors, which is what
      // the eye sees and what the buggy version got wrong.
      const composite = (el) => {
        const layers = [];
        for (let n = el; n; n = n.parentElement) {
          const st = getComputedStyle(n);
          const c = parse(st.backgroundColor);
          // A background-image tint (how today is layered) reads as an extra pass
          // of the same colour; approximate it with the accent at its own alpha.
          if (st.backgroundImage !== "none") {
            const tint = parse(st.backgroundImage);
            if (tint) layers.push(tint);
          }
          if (c && c.a > 0) {
            layers.push(c);
            if (c.a >= 1) break;
          }
        }
        let out = { r: 255, g: 255, b: 255 };
        for (let i = layers.length - 1; i >= 0; i -= 1) {
          const l = layers[i];
          out = {
            r: l.r * l.a + out.r * (1 - l.a),
            g: l.g * l.a + out.g * (1 - l.a),
            b: l.b * l.a + out.b * (1 - l.a),
          };
        }
        return out;
      };
      return {
        today: composite(document.querySelector("#month-grid .day-cell.today")),
        plain: composite(
          document.querySelector("#month-grid .day-cell:not(.today):not(.outside-month)")
        ),
      };
    });

    const delta = Math.max(
      Math.abs(today.r - plain.r),
      Math.abs(today.g - plain.g),
      Math.abs(today.b - plain.b)
    );
    // The intended tint moves the blue channel most, by ~15/255. The bug moved it
    // by 46, so 24 separates "faint highlight" from "different-coloured block".
    expect(
      delta,
      `today (${JSON.stringify(today)}) is too far from a normal cell (${JSON.stringify(plain)})`
    ).toBeLessThan(24);
  });

  /* The sweep above reads computed styles, and that has one blind spot big enough
     to have shipped a bug through it: the now-playing pane is backed by blurred
     album art, and a background IMAGE is not a background COLOR. Nothing in a
     computed-style walk can tell you how dark this month's album cover is. Worse,
     the art is a sibling layer rather than an ancestor, so even an
     "is there an image above me" check would miss it.

     So this one measures pixels. It screenshots the pane, decodes it back into a
     canvas in-page, and takes the median luminance - text covers a minority of the
     pane, so the median is the backdrop. Then it checks the title's colour against
     that. Ground truth, and indifferent to how the backdrop is built. */
  for (const palette of ["this month", "night"]) {
  test(`the now-playing pane is readable whatever is playing (${palette})`, async ({ page }) => {
    // The veil flips direction with the palette's lightness, so a dark palette
    // exercises the opposite branch: a dark veil under LIGHT text. Only the
    // month-of-the-day palette was ever measured before.
    if (palette === "night") {
      // Inlined rather than read from themes.js: addInitScript runs before any
      // page script, so NIGHT_THEME does not exist yet at that point.
      await page.addInitScript((night) => {
        localStorage.setItem("wallcal_theme", JSON.stringify(night));
      }, {"name": "Night", "accent": "#7aa2d6", "base": "#12141a", "surface": "#1b1e26", "lines": "#2c303a", "text": "#f0f0f0", "textDim": "#8a8f9c", "strength": 1.0});
    }
    await page.goto("/spotify");
    await page.waitForSelector("#track-title");
    await page.waitForTimeout(1500);

    const shot = (await page.locator("#nowplaying-pane").screenshot()).toString("base64");
    const { median, textColor } = await page.evaluate(async (b64) => {
      const img = new Image();
      img.src = "data:image/png;base64," + b64;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0);
      const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const channel = (v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      };
      const lums = [];
      for (let i = 0; i < data.length; i += 4) {
        lums.push(0.2126 * channel(data[i]) + 0.7152 * channel(data[i + 1]) + 0.0722 * channel(data[i + 2]));
      }
      lums.sort((a, b) => a - b);
      return {
        median: lums[Math.floor(lums.length / 2)],
        textColor: getComputedStyle(document.getElementById("track-title")).color,
      };
    }, shot);

    const [r, g, b] = textColor.match(/\d+/g).map(Number);
    const channel = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    const textLum = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    const ratio = (Math.max(textLum, median) + 0.05) / (Math.min(textLum, median) + 0.05);

    // Guards against the pin silently not applying, which would make the night
    // case a second run of the light one - passing while proving nothing.
    if (palette === "night") {
      expect(textLum, `night palette did not apply (text is ${textColor})`).toBeGreaterThan(0.5);
    } else {
      expect(textLum, `light palette should have dark text (got ${textColor})`).toBeLessThan(0.1);
    }

    expect(
      ratio,
      `${palette}: track title (${textColor}) vs the pane's backdrop (luminance ${median.toFixed(3)})`
    ).toBeGreaterThan(3);
  });
  }

  /* The loop above only ever proves ONE palette: themeForMonth() resolves by
     today's date, so whichever month it happens to be is the only one measured
     and the other twelve ship unverified. That is a poor deal on a conversion
     whose failure mode is invisible text. This pins each palette through the
     documented localStorage override and measures them all. */
  test("every palette in themes.js is readable", async ({ page }) => {
    await page.goto("/");
    const palettes = await page.evaluate(() =>
      [...MONTHLY_THEMES, NIGHT_THEME, THEME_TEMPLATE].map((t) => ({ name: t.name, theme: t }))
    );
    // Twelve months plus night plus the template users are told to copy.
    expect(palettes.length).toBe(14);

    const failures = [];
    for (const { name, theme } of palettes) {
      await page.addInitScript((t) => {
        localStorage.setItem("wallcal_theme", JSON.stringify(t));
      }, theme);
      await page.goto("/today");     // the densest mix of surfaces and dim text
      await page.waitForTimeout(1200);
      const offenders = await findOffenders(page);
      if (offenders.length) failures.push({ palette: name, offenders: offenders.slice(0, 4) });
    }
    expect(failures, "palettes with unreadable text").toEqual([]);
  });
});

test.describe("weather page", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("shows conditions, the hours, the week and the alerts", async ({ page }) => {
    await page.goto("/weather");
    await expect(page.locator(".wx-now-temp")).toHaveText(/^-?\d+°$/);

    // 24 hourly cells and 7 days, from the same fixtures the /today page uses.
    expect(await page.locator(".wx-hour").count()).toBe(24);
    expect(await page.locator(".wx-day").count()).toBe(10);

    // The demo fixture carries three alerts, one of them already expired: the
    // expired one must not be rendered. None are urgent - see demo_weather.py for
    // why the fixtures deliberately don't raise the shell banner.
    expect(await page.locator(".wx-alert").count()).toBe(2);
    expect(await page.locator(".wx-alert--urgent").count()).toBe(0);
    await expect(page.locator("#wx-alert-count")).toHaveText("2");
    await expect(page.locator("#wx-alerts")).not.toContainText("Flood Advisory");
    // And with nothing urgent, the shell banner stays down.
    await expect(page.locator("#alert-banner")).toBeHidden();
    await shoot(page, "weather-page");
  });

  test("an urgent alert is styled as urgent in the list", async ({ page }) => {
    await page.route("**/api/weather/alerts", (route) =>
      route.fulfill({
        json: {
          alerts: [
            {
              id: "t1", event: "Tornado Warning", severity: "Extreme", urgent: true,
              area: "Fulton", headline: "Tornado Warning issued",
              description: "Take shelter.", instruction: "Move to a basement.",
              sender: "NWS", ends: null, expires: null,
            },
          ],
          count: 1, urgent_count: 1,
        },
      })
    );
    await page.goto("/weather");
    expect(await page.locator(".wx-alert--urgent").count()).toBe(1);
    await expect(page.locator("#wx-alert-count")).toHaveClass(/wx-count--urgent/);
  });

  test("an alert opens to its full text and closes again", async ({ page }) => {
    await page.goto("/weather");
    const detail = page.locator('[data-wx-detail="0"]');
    await expect(detail).toBeHidden();

    await page.locator('[data-wx-alert="0"]').click();
    await expect(detail).toBeVisible();
    // The instruction is the part you'd act on, so it has to be in the detail.
    await expect(detail).toContainText("interior room");

    await page.locator('[data-wx-alert="0"]').click();
    await expect(detail).toBeHidden();
  });

  /* The storm outlook must never read as a lightning detector. There is no free
     strike-level feed - Open-Meteo's lightning_potential is all nulls for US
     locations - so the page states what it is. */
  test("the storm outlook says it is a forecast, not a detector", async ({ page }) => {
    await page.goto("/weather");
    await expect(page.locator(".wx-thunder-head")).toContainText(/Thunder|No thunder/);
    await expect(page.locator(".wx-thunder-caveat")).toContainText("not a detector");
    // CAPE band, from the fixture's 2600 J/kg afternoon.
    await expect(page.locator(".wx-thunder-cape")).toContainText("CAPE");
  });

  test("shows air quality and pollen, each attributed", async ({ page }) => {
    await page.goto("/weather");

    const air = page.locator("#wx-air");
    await expect(air).toContainText("AQI · Moderate");
    // The components matter: an Atlanta summer AQI is ozone, not particulates,
    // and that changes the advice from "shut the windows" to "go out earlier".
    await expect(air).toContainText("ozone");
    await expect(air).toContainText("Pollen · Medium-high");
    await expect(air).toContainText("Ragweed");
    // Pollen is a third-party index rather than a measurement, so it says whose.
    await expect(air).toContainText("pollen.com");
    expect(await page.locator(".wx-air-dial").count()).toBe(2);
  });

  /* Two providers, two scales: Google's UPI is 0-5, pollen.com's is 0-12. A bare
     "4" is High on one and Low-medium on the other, so the dial's colour has to be
     chosen against whichever scale answered - and the scale has to be on screen.
     Colouring a Google 4 green because 4/12 is low would be actively misleading. */
  test("pollen is coloured and labelled against its own scale", async ({ page }) => {
    const withPollen = (pollen) => async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      await route.fulfill({ json: { ...data, pollen } });
    };

    const dialColor = () =>
      page.locator(".wx-air-row").nth(1).locator(".wx-air-dial")
        .evaluate((el) => getComputedStyle(el).backgroundColor);

    // Google: 4 out of 5 is High, and must read as such.
    await page.route("**/api/weather/air", withPollen({
      available: true, source: "Google Pollen", scale_max: 5,
      today: { index: 4, label: "High", triggers: ["Ragweed"], types: [], recommendation: null },
      tomorrow: { index: 2, label: "Low" }, yesterday: { index: null },
    }));
    await page.goto("/weather");
    await expect(page.locator("#wx-air")).toContainText("Pollen · High");
    await expect(page.locator("#wx-air")).toContainText("Google Pollen");
    await expect(page.locator("#wx-air")).toContainText("0–5");
    const googleFour = await dialColor();

    // pollen.com: 4 out of 12 is Low-medium, and must NOT be the same colour.
    await page.unroute("**/api/weather/air");
    await page.route("**/api/weather/air", withPollen({
      available: true, source: "pollen.com", scale_max: 12,
      today: { index: 4, label: "Low-medium", triggers: ["Grasses"] },
      tomorrow: { index: 3, label: "Low-medium" }, yesterday: { index: 5 },
    }));
    await page.goto("/weather");
    await expect(page.locator("#wx-air")).toContainText("Pollen · Low-medium");
    await expect(page.locator("#wx-air")).toContainText("0–12");
    const iqviaFour = await dialColor();

    expect(iqviaFour, "the same number is coloured identically on both scales")
      .not.toBe(googleFour);
  });

  /* Google supplies things pollen.com can't: per-type indices and a health note. */
  test("Google's extra pollen detail is shown when it answers", async ({ page }) => {
    await page.route("**/api/weather/air", async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      await route.fulfill({
        json: {
          ...data,
          pollen: {
            available: true, source: "Google Pollen", scale_max: 5,
            today: {
              index: 4, label: "High", triggers: ["Ragweed", "Oak"],
              types: [
                { name: "Grass", index: 4, label: "High", in_season: true },
                { name: "Tree", index: 1, label: "Very Low", in_season: false },
                // No reading: must be dropped, not shown as a dash or a zero.
                { name: "Weed", index: null, label: null, in_season: false },
              ],
              recommendation: "Keep windows closed in the morning.",
            },
            tomorrow: { index: 2, label: "Low" }, yesterday: { index: null },
          },
        },
      });
    });
    await page.goto("/weather");
    const air = page.locator("#wx-air");
    await expect(air).toContainText("Grass 4");
    await expect(air).toContainText("Tree 1");
    await expect(air).not.toContainText("Weed");
    await expect(page.locator(".wx-air-advice")).toContainText("windows closed");
  });

  /* Pollen comes from an undocumented endpoint that will break one day. When it
     does, the air quality half has to survive it. */
  test("pollen failing leaves the air quality showing", async ({ page }) => {
    await page.route("**/api/weather/air", async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      await route.fulfill({
        json: {
          ...data,
          pollen: { available: false, source: "pollen.com" },
          errors: ["Couldn't reach the pollen service (ReadTimeout)."],
        },
      });
    });
    await page.goto("/weather");
    await expect(page.locator("#wx-air")).toContainText("AQI · Moderate");
    await expect(page.locator("#wx-air")).toContainText("Pollen unavailable");
    expect(await page.locator(".wx-air-dial").count()).toBe(1);
  });

  test("the radar opens full-screen and switches between views", async ({ page }) => {
    await page.route("**/api/weather/radar", (route) =>
      route.fulfill({
        json: {
          available: true, station: "KFFC", state: "GA", region: "SOUTHEAST",
          loop_url: "https://radar.weather.gov/ridge/standard/KFFC_loop.gif",
          still_url: "https://radar.weather.gov/ridge/standard/KFFC_0.gif",
          regional_url: "https://radar.weather.gov/ridge/standard/SOUTHEAST_loop.gif",
          national_url: "https://radar.weather.gov/ridge/standard/CONUS_loop.gif",
        },
      })
    );
    // The images are on radar.weather.gov; the test is about wiring, not pixels.
    await page.route("https://radar.weather.gov/**", (route) => route.abort());
    await page.goto("/weather");

    /* The thumbnail must have a SIZE, not just a src. It once had `height: 100%`
       inside a flex parent that never grew, so the live page rendered an empty
       div - the wiring assertions below all passed while nothing was on screen. */
    const box = await page.locator("#wx-radar").boundingBox();
    expect(box.width, "radar thumbnail has no width").toBeGreaterThan(120);
    expect(box.height, "radar thumbnail collapsed to nothing").toBeGreaterThan(120);

    const overlay = page.locator("#wx-radar-overlay");
    await expect(overlay).toBeHidden();
    await page.locator("#wx-radar").click();
    await expect(overlay).toBeVisible();
    await expect(page.locator("#wx-radar-caption")).toContainText("KFFC");

    /* Opening it has to actually enlarge. The source GIF is 600x550 - the same
       size as the thumbnail - so at native scale this overlay showed the identical
       picture in a bigger box and the feature did nothing. */
    const big = await page.locator("#wx-radar-big").boundingBox();
    expect(big.width, "the enlarged radar is no bigger than the thumbnail")
      .toBeGreaterThan(box.width * 1.3);

    await page.locator('[data-wx-radar="regional"]').click();
    await expect(page.locator("#wx-radar-caption")).toContainText("SOUTHEAST");
    await expect(page.locator("#wx-radar-big img")).toHaveAttribute("src", /SOUTHEAST_loop/);

    await page.locator('[data-wx-radar="national"]').click();
    await expect(page.locator("#wx-radar-big img")).toHaveAttribute("src", /CONUS_loop/);

    await page.locator("#wx-radar-close").click();
    await expect(overlay).toBeHidden();
  });

  /* A state with no verified RIDGE regional loop must not offer the tab - the
     alternative is a tab that loads a 404. */
  test("no regional tab when the state has no regional loop", async ({ page }) => {
    await page.route("**/api/weather/radar", (route) =>
      route.fulfill({
        json: {
          available: true, station: "KABC", state: "ZZ", region: null,
          loop_url: "https://radar.weather.gov/ridge/standard/KABC_loop.gif",
          regional_url: null,
          national_url: "https://radar.weather.gov/ridge/standard/CONUS_loop.gif",
        },
      })
    );
    await page.route("https://radar.weather.gov/**", (route) => route.abort());
    await page.goto("/weather");
    await page.locator("#wx-radar").click();
    await expect(page.locator('[data-wx-radar="regional"]')).toBeHidden();
    await expect(page.locator('[data-wx-radar="national"]')).toBeVisible();
  });

  test("the daylight card reports length and tomorrow's change", async ({ page }) => {
    await page.goto("/weather");
    const sun = page.locator("#wx-sun");
    await expect(sun).toContainText(/\d+h \d\dm/);
    await expect(sun).toContainText(/longer tomorrow|shorter tomorrow|About the same/);
    // A two-minute change must read "2m", not "0h 02m".
    expect(await sun.textContent()).not.toMatch(/0h \d\dm/);
  });

  /* Open-Meteo returns raw totals, so the day list printed 0.004" and 0.035" -
     four significant figures of drizzle, which reads as precision the forecast
     doesn't have and is not a number anyone acts on. */
  test("rain totals are rounded, and trace amounts omitted", async ({ page }) => {
    await page.goto("/weather");
    const totals = await page.locator("#wx-days").textContent();
    expect(totals, "un-rounded rain total on screen").not.toMatch(/\d\.\d{3,}"/);

    await page.route("**/api/weather", async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      const days = data.days.map((d, i) => ({ ...d, precip_total: i === 0 ? 0.004 : 0.2718 }));
      await route.fulfill({ json: { ...data, days } });
    });
    await page.goto("/weather");
    const rows = page.locator(".wx-day");
    await expect(rows.first()).not.toContainText('"');      // trace: nothing shown
    await expect(rows.nth(1)).toContainText('0.27"');       // rounded, not 0.2718
  });

  /* Caught on the live wall: "No thunder in the next 24 hours" sat directly above
     "Very unstable - strong storms possible" while the radar showed cells 30 miles
     out. All three statements were true; leading with only the first is how a wall
     display loses your trust. */
  test("an unstable sky with no forecast thunder says so", async ({ page }) => {
    await page.route("**/api/weather", async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      await route.fulfill({
        json: { ...data, thunder_hours: [], cape_peak: 2570 },
      });
    });
    await page.goto("/weather");
    await expect(page.locator(".wx-thunder-head")).toContainText("the air is unstable");
    await expect(page.locator(".wx-thunder-cape")).toContainText("Very unstable");

    // And a genuinely quiet sky must not be dressed up as anything.
    await page.unroute("**/api/weather");
    await page.route("**/api/weather", async (route) => {
      const resp = await route.fetch();
      const data = await resp.json();
      await route.fulfill({ json: { ...data, thunder_hours: [], cape_peak: 200 } });
    });
    await page.goto("/weather");
    await expect(page.locator(".wx-thunder-head")).toHaveText("No thunder in the next 24 hours");
  });

  /* A regional advisory lists every county it covers - thirty-odd names, five
     wrapped lines, burying the alerts under it. */
  test("a long county list is truncated, with the full one in the detail", async ({ page }) => {
    const counties = Array.from({ length: 30 }, (_, i) => `County${i}`).join("; ");
    await page.route("**/api/weather/alerts", (route) =>
      route.fulfill({
        json: {
          alerts: [
            {
              id: "x", event: "Heat Advisory", severity: "Moderate", urgent: false,
              area: counties, headline: "Heat Advisory in effect",
              description: "Hot.", instruction: null, sender: "NWS", ends: null, expires: null,
            },
          ],
          count: 1, urgent_count: 0,
        },
      })
    );
    await page.goto("/weather");

    const summary = page.locator(".wx-alert-area");
    await expect(summary).toContainText("+ 26 more");
    expect((await summary.textContent()).length).toBeLessThan(80);

    // The full list is still available, just not in the collapsed row.
    await page.locator('[data-wx-alert="0"]').click();
    await expect(page.locator(".wx-alert-fullarea")).toContainText("County29");
  });

  test("a failing alerts service leaves the rest of the page working", async ({ page }) => {
    // Alerts are NWS; every number is Open-Meteo. One source failing must not
    // take the other half of the page down, which is why they are separate calls.
    await page.route("**/api/weather/alerts", (route) => route.abort());
    await page.goto("/weather");

    await expect(page.locator(".wx-now-temp")).toHaveText(/^-?\d+°$/);
    expect(await page.locator(".wx-day").count()).toBe(10);
    await expect(page.locator("#wx-alerts")).toContainText("Couldn't reach");
  });
});

test.describe("severe weather banner", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  const alert = (over = {}) => ({
    id: "a1", event: "Tornado Warning", severity: "Extreme", urgent: true,
    area: "Fulton; DeKalb; Cobb", headline: "Tornado Warning issued",
    ends: new Date(Date.now() + 45 * 60 * 1000).toISOString(),
    expires: new Date(Date.now() + 45 * 60 * 1000).toISOString(),
    description: "Take shelter now.", instruction: "Move to a basement.",
    sender: "NWS Peachtree City GA", ...over,
  });

  const serve = (alerts) => (route) =>
    route.fulfill({
      json: {
        alerts,
        count: alerts.length,
        urgent_count: alerts.filter((a) => a.urgent).length,
      },
    });

  /* The whole point: the wall shows a calendar all day, so a warning that only
     appears on /weather is not doing its job. */
  test("an urgent warning shows on the calendar, not just the weather page", async ({ page }) => {
    await page.route("**/api/weather/alerts", serve([alert()]));
    await page.goto("/");
    await expect(page.locator("#alert-banner")).toBeVisible();
    await expect(page.locator("#alert-banner-event")).toHaveText("Tornado Warning");
    await expect(page.locator("#alert-banner-area")).toContainText("Fulton");
    await shoot(page, "alert-banner");
  });

  test("a non-urgent advisory does not take over the wall", async ({ page }) => {
    // A heat advisory is worth a line on the weather page and nothing more; a
    // banner for every advisory would train you to ignore the banner.
    await page.route("**/api/weather/alerts", serve([
      alert({ id: "h1", event: "Heat Advisory", severity: "Moderate", urgent: false }),
    ]));
    await page.goto("/");
    await page.waitForTimeout(800);
    await expect(page.locator("#alert-banner")).toBeHidden();
  });

  /* The dangerous bug this guards against: a single "dismissed" flag would mean
     dismissing a heat advisory at noon silently suppresses a tornado warning at
     6pm. Dismissal is per alert id. */
  test("dismissing one warning does not suppress a different one", async ({ page }) => {
    await page.route("**/api/weather/alerts", serve([
      alert({ id: "flood", event: "Flash Flood Warning" }),
    ]));
    await page.goto("/");
    await expect(page.locator("#alert-banner-event")).toHaveText("Flash Flood Warning");

    await page.locator("#alert-banner-dismiss").click();
    await expect(page.locator("#alert-banner")).toBeHidden();

    // A different alert arrives on the next poll: it must NOT be suppressed.
    await page.unroute("**/api/weather/alerts");
    await page.route("**/api/weather/alerts", serve([alert({ id: "tornado" })]));
    await page.evaluate(() => refreshAlerts());
    await expect(page.locator("#alert-banner")).toBeVisible();
    await expect(page.locator("#alert-banner-event")).toHaveText("Tornado Warning");

    // ...while the one that WAS dismissed stays dismissed.
    await page.unroute("**/api/weather/alerts");
    await page.route("**/api/weather/alerts", serve([
      alert({ id: "flood", event: "Flash Flood Warning" }),
    ]));
    await page.evaluate(() => refreshAlerts());
    await expect(page.locator("#alert-banner")).toBeHidden();
  });

  test("several urgent warnings collapse to one banner with a count", async ({ page }) => {
    await page.route("**/api/weather/alerts", serve([
      alert({ id: "t", event: "Tornado Warning" }),
      alert({ id: "f", event: "Flash Flood Warning" }),
    ]));
    await page.goto("/");
    await expect(page.locator("#alert-banner-event")).toHaveText("Tornado Warning (+1 more)");
  });

  /* 2am is when this matters most, and it's also when a black overlay covers the
     screen. The banner has to be above it - this was z-index 60 against the
     overlay's 3000, i.e. underneath. */
  test("the banner sits above the night dimming overlay", async ({ page }) => {
    await page.route("**/api/weather/alerts", serve([alert()]));
    await page.goto("/");
    await expect(page.locator("#alert-banner")).toBeVisible();

    const stacking = await page.evaluate(() => {
      const banner = document.getElementById("alert-banner");
      document.getElementById("night-dim").classList.remove("hidden");
      const rect = banner.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + 40, rect.top + rect.height / 2);
      return {
        bannerZ: Number(getComputedStyle(banner).zIndex),
        dimZ: Number(getComputedStyle(document.getElementById("night-dim")).zIndex),
        bannerOnTop: banner.contains(hit) || banner === hit,
      };
    });
    expect(stacking.bannerZ).toBeGreaterThan(stacking.dimZ);
    expect(stacking.bannerOnTop, "the dimming overlay covers the warning").toBe(true);
  });

  /* The banner takes real height, and on a 600px panel that comes straight off the
     month rows - which had already trimmed their pills to fit the taller layout, so
     14 cells ended up clipping their own content. Nothing fires window.resize for
     this, hence the explicit layout-change event, and the banner is tightened on
     short panels because 48px of 600 is 8% of the screen. */
  test("a warning arriving later re-fits the calendar rather than clipping it",
    async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 600 });

      // Start with nothing active - which is how the wall spends nearly all its
      // time - and let the month grid settle and trim to the full height.
      await page.route("**/api/weather/alerts", serve([]));
      await page.goto("/");
      await page.waitForSelector("#month-grid .day-cell");
      await page.waitForTimeout(1000);
      await expect(page.locator("#alert-banner")).toBeHidden();

      const before = await page.evaluate(() =>
        [...document.querySelectorAll("#month-grid .day-cell")]
          .filter((c) => c.scrollHeight > c.clientHeight + 1).length
      );
      expect(before, "clipping before any warning").toBe(0);

      // Now a warning arrives, hours later, and takes height off every row. The
      // cells have ALREADY trimmed to fit the taller layout, and nothing fires
      // window.resize for this - which left 14 of them clipping their own content.
      await page.unroute("**/api/weather/alerts");
      await page.route("**/api/weather/alerts", serve([alert()]));
      await page.evaluate(() => refreshAlerts());
      await expect(page.locator("#alert-banner")).toBeVisible();
      await page.waitForTimeout(1400);   // the relayout debounce

      const after = await page.evaluate(() => {
        const cells = [...document.querySelectorAll("#month-grid .day-cell")];
        return {
          cells: cells.length,
          clipping: cells.filter((c) => c.scrollHeight > c.clientHeight + 1).length,
          overflowMarkers: document.querySelectorAll(".event-overflow").length,
          bannerHeight: Math.round(
            document.getElementById("alert-banner").getBoundingClientRect().height
          ),
        };
      });

      expect(after.cells, "the grid lost rows to the banner").toBe(42);
      expect(after.clipping, "cells clipping after the banner took their height")
        .toBe(0);
      // It fits by hiding pills behind "+N more", not by overflowing.
      expect(after.overflowMarkers).toBeGreaterThan(0);
      // 48px out of 600 is 8% of the screen, so the banner tightens here.
      expect(after.bannerHeight, "the banner is not compact on a short panel")
        .toBeLessThan(44);
      await expectNoSidewaysScroll(page, "calendar with a warning at 1024x600");
    });

  /* Both the shell banner and the weather page's list are fed by one poll. Two
     pollers would double the request rate against the NWS. */
  test("the weather page adds no second alerts poll", async ({ page }) => {
    let calls = 0;
    await page.route("**/api/weather/alerts", (route) => {
      calls += 1;
      return serve([alert()])(route);
    });
    await page.goto("/weather");
    await expect(page.locator("#alert-banner")).toBeVisible();
    await expect(page.locator(".wx-alert").first()).toContainText("Tornado Warning");
    await page.waitForTimeout(1500);
    expect(calls, "the alerts endpoint was polled more than once per cycle").toBe(1);
  });
});

test.describe("touch input", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  /* On the wall there is no hardware keyboard: the compositor only offers an
     on-screen keyboard once something has text focus. Opening the sheet therefore
     has to focus the title itself, or "add an event" needs two taps before you can
     type - and the first version needed exactly that.
     (The other half of this was Chromium not advertising text-input under Wayland
     at all, which is a launch flag rather than anything testable here - see
     deploy/kiosk-launch.sh.) */
  test("opening the event sheet focuses the title so a keyboard can appear", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    await page.click("#add-event-toggle");
    await expect(page.locator("#add-event-overlay")).toBeVisible();

    const focused = await page.evaluate(() => document.activeElement?.id);
    expect(focused, "the title field is not focused, so no keyboard would appear")
      .toBe("add-event-title");

    // And it has to be a real text field: a compositor offers no keyboard for a
    // div, however editable it looks.
    await expect(page.locator("#add-event-title")).toHaveAttribute("type", "text");
    await page.keyboard.type("Dentist");
    await expect(page.locator("#add-event-title")).toHaveValue("Dentist");
  });
});
