/* Brightness, the sleep screen, and the interaction between them.
 *
 * Measured rather than inspected, because every bug this could have is a render
 * result: an overlay that is present but at the wrong opacity, a sleep screen that is
 * in the DOM but behind the page, or a tap that is swallowed when it should not be.
 */

const path = require("path");
const { test, expect } = require("@playwright/test");

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "..", "test-results", "shots");

async function dimOpacity(page) {
  return page.evaluate(() => {
    const el = document.getElementById("night-dim");
    return el.classList.contains("hidden") ? 0 : Number(getComputedStyle(el).opacity);
  });
}

test.describe("brightness", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  /* Brightness is a *stored* setting, so the one test here that saves it has to put
     it back. It leaks otherwise: a run left the dev server at 40%, and the next specs
     to touch the shell failed in ways that pointed nowhere near here - the night-dim
     test read 0.6 instead of 0 after waking, and the contrast sweep measured every
     page through a 60% black veil. Cheaper to reset than to debug twice. */
  test.afterEach(async ({ request }) => {
    await request.post("/api/system/display", { data: { brightness: 1 } });
  });

  test("the chip opens a panel, and the slider dims the wall as you drag", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    expect(await dimOpacity(page), "a fresh wall should not be dimmed").toBe(0);

    await page.click("#brightness-chip");
    await expect(page.locator("#brightness-overlay")).toBeVisible();

    // Drive the real control rather than calling the function behind it: the whole
    // point is that dragging the slider changes the screen.
    await page.locator("#brightness-range").fill("40");
    await page.locator("#brightness-range").dispatchEvent("input");

    const dimmed = await dimOpacity(page);
    expect(dimmed, "40% brightness should leave a 60% black veil").toBeCloseTo(0.6, 1);
    await expect(page.locator("#brightness-value")).toHaveText("40%");

    await page.screenshot({ path: path.join(SHOT_DIR, "brightness-40.png") });
  });

  /* The reason the wake handler is gated on state rather than on the overlay being
     visible, and the reason #night-dim sets pointer-events: none.

     Two separate ways a dimmed wall can stop responding, and both were real: the
     overlay is fixed and full-bleed, so it hit-tests over the whole page and ate
     every tap (this test caught that); and a state-blind wake handler would consume
     the first tap at any brightness below 100%.

     Asserted on the event itself rather than on some panel opening, so it measures
     the invariant - taps reach the page - and not the calendar's UI semantics. */
  test("dimming by hand blocks neither hit-testing nor the tap itself", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    await page.evaluate(() => previewBrightness(0.4));
    expect(await dimOpacity(page)).toBeGreaterThan(0.5);

    // 1. The overlay must not be what the pointer lands on.
    const hit = await page.evaluate(() => {
      const el = document.elementFromPoint(960, 540);
      return el ? el.id || el.className : "nothing";
    });
    expect(hit, "the dim overlay is hit-testing over the page").not.toBe("night-dim");

    // 2. The tap must arrive at the page, un-prevented.
    const arrived = await page.evaluate(async () => {
      const seen = { target: null, prevented: null };
      const onDown = (e) => {
        seen.target = e.target.id || e.target.className;
        // Read after the capture-phase handler in nav.js has had its chance.
        setTimeout(() => { seen.prevented = e.defaultPrevented; }, 0);
      };
      document.addEventListener("pointerdown", onDown);
      const cell = document.querySelectorAll("#month-grid .day-cell")[10];
      const r = cell.getBoundingClientRect();
      cell.dispatchEvent(new PointerEvent("pointerdown", {
        bubbles: true, cancelable: true,
        clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
      }));
      await new Promise((res) => setTimeout(res, 20));
      document.removeEventListener("pointerdown", onDown);
      return seen;
    });
    expect(arrived.target, "the tap never reached a day cell").toContain("day-cell");
    expect(arrived.prevented, "a hand-dimmed wall swallowed the tap").toBe(false);
  });

  test("but a sleeping wall does swallow the tap that wakes it", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    /* Measured on the target, not on document. nav.js's capture-phase handler calls
       stopPropagation(), so a probe on document never runs at all - which is the
       swallow working, and would read as a failure if asserted there. What matters is
       that the element underneath never hears about the tap. */
    const reachedCell = await page.evaluate(async () => {
      sleepNow();
      let heard = false;
      const cell = document.querySelectorAll("#month-grid .day-cell")[10];
      const onDown = () => { heard = true; };
      cell.addEventListener("pointerdown", onDown);
      cell.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true }));
      await new Promise((res) => setTimeout(res, 20));
      cell.removeEventListener("pointerdown", onDown);
      return heard;
    });
    expect(reachedCell, "the waking tap fell through to the calendar underneath").toBe(false);
    // ...and it did wake the wall rather than being simply dropped.
    await expect(page.locator("#sleep-screen")).toBeHidden();
  });

  test("sleep covers the wall with a faint clock, and a tap wakes it", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    await page.evaluate(() => sleepNow());
    const sleep = page.locator("#sleep-screen");
    await expect(sleep).toBeVisible();

    // Full-bleed: it replaces the page rather than shading it, so it has to cover the
    // rail and the top bar too.
    const box = await sleep.boundingBox();
    expect(box.x).toBe(0);
    expect(box.y).toBe(0);
    expect(box.width).toBe(1920);
    expect(box.height).toBe(1080);

    // It has to be the topmost thing at the centre, or the tap that wakes the wall
    // lands on the calendar underneath.
    const onTop = await page.evaluate(() => {
      const el = document.elementFromPoint(960, 540);
      return Boolean(el && el.closest("#sleep-screen"));
    });
    expect(onTop, "something is drawn over the sleep screen").toBe(true);

    // The clock is the one thing worth keeping visible, and it must be faint.
    await expect(page.locator("#sleep-time")).toHaveText(/\d/);
    const clockLuma = await page.evaluate(() => {
      const c = getComputedStyle(document.getElementById("sleep-time")).color;
      const [r, g, b] = c.match(/\d+/g).map(Number);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    });
    expect(clockLuma, "the sleep clock is too bright for a dark kitchen").toBeLessThan(140);
    expect(clockLuma, "the sleep clock is invisible").toBeGreaterThan(40);

    await page.screenshot({ path: path.join(SHOT_DIR, "sleep-screen.png") });

    // And the tap that wakes it must be swallowed - the calendar underneath must not
    // also receive it.
    await page.mouse.click(960, 540);
    await expect(sleep).toBeHidden();
    await expect(page.locator("#day-detail")).toBeHidden();
  });

  test("the worst case is never a black screen", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    // Minimum brightness, asleep, and after dark all at once - the combination that
    // multiplies out to roughly 0.008 without the clamp.
    const opacity = await page.evaluate(() => {
      previewBrightness(0.2);
      sleepNow();
      const el = document.getElementById("night-dim");
      return Number(getComputedStyle(el).opacity);
    });
    expect(opacity, "the dim overlay reached full black").toBeLessThan(1);
    expect(opacity).toBeLessThanOrEqual(0.94);
  });

  test("the chip row still fits a 1024x600 panel", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 600 });
    await page.goto("/");
    await page.waitForSelector("#month-grid .day-cell");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow, "adding the brightness chip pushed the top bar over").toBeLessThanOrEqual(1);

    const chip = await page.locator("#brightness-chip").boundingBox();
    expect(chip.height, "the chip is too small to hit with a fingertip").toBeGreaterThanOrEqual(44);
    expect(chip.width).toBeGreaterThanOrEqual(44);

    // And the panel itself has to be usable at that height.
    await page.click("#brightness-chip");
    const panel = await page.locator("#brightness-panel").boundingBox();
    expect(panel.y).toBeGreaterThanOrEqual(0);
    expect(panel.y + panel.height, "the brightness panel is taller than the panel").toBeLessThanOrEqual(600);
    await page.screenshot({ path: path.join(SHOT_DIR, "brightness-1024x600.png") });
  });
});
