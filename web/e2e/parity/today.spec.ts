import { expect, test } from "@playwright/test";
import { bothSides, motionTokens, openPath, parity, type Step } from "./harness";

// Today («Өнөөдөр»): Django employees/today.html against TodayPage. Same path on both sides; the demo user is `hr`.
const PATH = "/employees/today/";

// The date text that differs only at midnight: the header date beside the title, the strip's date range, and the day
// heading of an opened away day.
const DATE_MASKS = ["h1 + span.ml-auto > span.text-sm", "#away-title + span", "[data-away-day]"];

const openToday: Step = (page) => openPath(page, PATH);

// Full-page screenshots: light and dark, 1280 px and 375 px (the harness runs all four).
parity("today", PATH, PATH, [openToday], { signIn: true, mask: DATE_MASKS });

test.describe("today steps", () => {
  test.use({ reducedMotion: "no-preference" });

  test("a clicked away day puts its heading under the strip, the same on both sides", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      await page.locator("[data-away-strip] button").first().click();
      const heading = page.locator("#away-names h3");
      await expect(heading).toBeVisible();
      return heading.innerText();
    });
    expect(sides.web).toBe(sides.django);
  });

  test("«Ажилласан жилийн ой» opens on the first click and closes on the second", async ({ browser }) => {
    await bothSides(browser, PATH, async (page) => {
      const toggle = page.getByRole("button", { name: "Ажилласан жилийн ой" });
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
    });
  });

  test("the first closed attention group turns its chevron, with the same transition duration", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      const box = page.locator("#attention-box");
      if ((await box.count()) === 0) return null;
      // The groups are only visible inside the attention box, so open it first (its own toggle, no data change).
      if (!(await box.evaluate((el) => (el as HTMLDetailsElement).open))) {
        await box.locator("summary").first().click();
      }
      const groups = page.locator("[data-attention-group]");
      const index = await groups.evaluateAll((els) => els.findIndex((el) => !el.hasAttribute("open")));
      if (index < 0) return null;
      const group = groups.nth(index);
      const chevron = group.locator("summary").first().locator("svg").last();
      const closed = await chevron.evaluate((el) => {
        const style = getComputedStyle(el);
        // Tailwind 4 rotate-180 sets the CSS `rotate` property, not `transform`.
        return { turn: `${style.rotate}|${style.transform}`, duration: style.transitionDuration };
      });
      await group.locator("summary").first().click();
      await expect(group).toHaveJSProperty("open", true);
      await expect
        .poll(() => chevron.evaluate((el) => `${getComputedStyle(el).rotate}|${getComputedStyle(el).transform}`))
        .not.toBe(closed.turn);
      return { duration: closed.duration };
    });
    test.skip(sides.django === null && sides.web === null, "no closed attention group in the demo data");
    expect(sides.web).toEqual(sides.django);
  });

  test("the attention box has the same data-tone on both sides", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      const box = page.locator("#attention-box");
      if ((await box.count()) === 0) return null;
      return box.getAttribute("data-tone");
    });
    test.skip(sides.django === null && sides.web === null, "no attention box in the demo data");
    expect(sides.web).toEqual(sides.django);
  });

  test("a.card-soft hover has the same transition duration on both sides (M-14)", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      await page.locator("a.card-soft").first().hover();
      return motionTokens(page, "a.card-soft");
    });
    expect(sides.web).toEqual(sides.django);
  });
});
