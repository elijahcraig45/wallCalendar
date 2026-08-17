/* The System page and the touch-calibration overlay.
 *
 * Same lesson as the other specs: measure geometry, don't count elements. The
 * calibration overlay in particular cannot be checked by looking at the DOM - what
 * matters is where a crosshair physically lands and whether a tap on it reaches the
 * button, and both of those are render results.
 */

const path = require("path");
const { test, expect } = require("@playwright/test");

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "..", "test-results", "shots");

// Mirrors TARGETS in static/system.js. Duplicated on purpose: if someone changes
// one, this test should fail rather than follow along.
const TARGETS = [
  [0.12, 0.14],
  [0.88, 0.14],
  [0.50, 0.50],
  [0.12, 0.86],
  [0.88, 0.86],
];

const VIEWPORTS = [
  { name: "1024x600", width: 1024, height: 600 },
  { name: "1920x1080", width: 1920, height: 1080 },
];

for (const vp of VIEWPORTS) {
  test.describe(`system page ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("renders without spilling sideways, and every control is thumb-sized", async ({ page }) => {
      await page.goto("/system");
      await page.waitForSelector("#section-list li");

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth
      );
      expect(overflow, "the system page scrolls sideways").toBeLessThanOrEqual(1);

      // Cards must stay inside the stage, not under the rail.
      const spill = await page.evaluate(() => {
        const view = document.getElementById("system-view").getBoundingClientRect();
        return [...document.querySelectorAll(".system-card")]
          .map((card) => {
            const r = card.getBoundingClientRect();
            return Math.max(view.left - r.left, r.right - view.right);
          })
          .reduce((a, b) => Math.max(a, b), 0);
      });
      expect(spill, "a card hangs outside the content area").toBeLessThanOrEqual(1);

      /* This is operated standing up, with a fingertip, on a glossy wall panel.
         Measured on the rendered box rather than read off the CSS, because padding
         and flex both move it.

         The checkbox itself is only 26px, and deliberately so: the tap target is
         the whole label row around it. That is the thing worth pinning - a future
         change that drops the label wrapper would leave a 26px target that still
         looks identical in a screenshot. */
      const boxesWithSmallRows = await page.evaluate(() =>
        [...document.querySelectorAll("#system-view input[type=checkbox]")]
          .filter((el) => el.offsetParent !== null)
          .map((el) => {
            const label = el.closest("label.system-toggle");
            const r = label && label.getBoundingClientRect();
            return { id: el.id || "(section toggle)", h: r ? r.height : 0 };
          })
          .filter((t) => t.h < 44)
      );
      expect(
        boxesWithSmallRows,
        `checkbox rows under 44px: ${JSON.stringify(boxesWithSmallRows)}`
      ).toEqual([]);

      // Buttons follow the app's existing pill sizing (.pill-button is 38px tall
      // everywhere else), so this guards against a collapse, not against the
      // house style.
      const smallButtons = await page.evaluate(() =>
        [...document.querySelectorAll("#system-view button")]
          .filter((el) => el.offsetParent !== null)
          .map((el) => {
            const r = el.getBoundingClientRect();
            return { id: el.id || el.textContent.trim().slice(0, 20), h: r.height, w: r.width };
          })
          .filter((t) => t.h < 36 || t.w < 44)
      );
      expect(smallButtons, `buttons too small: ${JSON.stringify(smallButtons)}`).toEqual([]);

      await page.screenshot({ path: path.join(SHOT_DIR, `system-${vp.name}.png`) });
    });

    test("a hidden section loses its rail icon but keeps its page", async ({ page }) => {
      await page.goto("/system");
      await page.waitForSelector("#section-list li");

      await expect(page.locator('#rail [data-nav="/groceries"]')).toHaveCount(1);

      // The toggle reloads the page, because the rail is rendered server-side.
      const groceries = page.locator("#section-list li", { hasText: "Groceries" }).locator("input");
      await groceries.uncheck();
      await page.waitForURL(/\/system/);
      await page.waitForSelector("#section-list li");

      await expect(page.locator('#rail [data-nav="/groceries"]')).toHaveCount(0);
      // Disabled, not deleted.
      expect((await page.request.get("/groceries")).status()).toBe(200);

      // Put it back so this spec leaves no state behind for the others.
      await page.locator("#section-list li", { hasText: "Groceries" }).locator("input").check();
      await page.waitForURL(/\/system/);
      await expect(page.locator('#rail [data-nav="/groceries"]')).toHaveCount(1);
    });
  });
}

test.describe("touch calibration overlay", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  /* The overlay's geometry is the thing under test, and it has nothing to do with
     whether this machine has a touchscreen - which a laptop running the suite does
     not, so /api/system/touch reports no device and the Calibrate button is
     correctly disabled. Stubbing the two hardware endpoints lets the maths and the
     hit-testing be checked anywhere, and keeps the run from writing an rc.xml on
     whatever machine the suite happens to be on. */
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/system/touch", (route) =>
      route.fulfill({
        json: {
          matrix: [1, 0, 0, 0, 1, 0],
          calibrated: false,
          device: "Fixture Touchscreen",
          devices: ["Fixture Touchscreen"],
          output: "HDMI-A-1",
          outputs: ["HDMI-A-1"],
          on_trial: false,
          trial_seconds: 45,
        },
      })
    );
    await page.route("**/api/system/touch/calibrate", (route) =>
      route.fulfill({ json: { ok: true, matrix: [1, 0, 0, 0, 1, 0], trial_seconds: 45 } })
    );
  });

  test("the crosshair lands where the maths thinks it does", async ({ page }) => {
    await page.goto("/system");
    await page.waitForSelector("#section-list li");
    await page.click("#touch-start");

    const overlay = page.locator("#calibrate-overlay");
    await expect(overlay).toBeVisible();

    /* The whole fit is only as good as this: the page tells the server "the target
       was at fraction f", so the drawn centre has to actually be at f. A CSS change
       that positioned the crosshair by its top-left corner instead of its centre
       would skew every calibration by half a crosshair - 48px - while looking
       completely fine on screen. */
    for (let i = 0; i < TARGETS.length; i += 1) {
      const [fx, fy] = TARGETS[i];
      const measured = await page.evaluate(() => {
        const r = document.getElementById("calibrate-target").getBoundingClientRect();
        return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
      });
      expect(Math.abs(measured.cx - fx * 1920), `target ${i} x`).toBeLessThanOrEqual(1.5);
      expect(Math.abs(measured.cy - fy * 1080), `target ${i} y`).toBeLessThanOrEqual(1.5);

      // A tap on the crosshair has to reach the crosshair. The instructions block
      // is centred, and so is target 3 - without pointer-events:none on the text
      // that third tap would land on a <p> and calibration would hang forever.
      const hit = await page.evaluate(({ cx, cy }) => {
        const el = document.elementFromPoint(cx, cy);
        return el && el.closest("#calibrate-target") ? "target" : (el && el.id) || "nothing";
      }, measured);
      expect(hit, `target ${i} is covered by another element`).toBe("target");

      await page.mouse.click(measured.cx, measured.cy);
    }

    // Five taps in, it should be asking whether to keep the result rather than
    // still showing crosshairs.
    await expect(page.locator("#calibrate-target")).toBeHidden();
    await page.screenshot({ path: path.join(SHOT_DIR, "system-calibrate.png") });
  });

  test("the overlay covers the whole panel, including the rail and top bar", async ({ page }) => {
    await page.goto("/system");
    await page.waitForSelector("#section-list li");
    await page.click("#touch-start");

    // Calibration has to sample the corners, which the rail and the top bar
    // normally own - a partial overlay would collect taps aimed at the nav.
    const box = await page.locator("#calibrate-overlay").boundingBox();
    expect(box.x).toBe(0);
    expect(box.y).toBe(0);
    expect(box.width).toBe(1920);
    expect(box.height).toBe(1080);

    for (const [x, y] of [[10, 10], [1910, 10], [10, 1070], [1910, 1070]]) {
      const onOverlay = await page.evaluate(
        ({ x, y }) => {
          const el = document.elementFromPoint(x, y);
          return Boolean(el && el.closest("#calibrate-overlay"));
        },
        { x, y }
      );
      expect(onOverlay, `the overlay does not cover ${x},${y}`).toBe(true);
    }
  });
});
