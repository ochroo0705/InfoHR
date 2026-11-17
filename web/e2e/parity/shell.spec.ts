import { expect, test, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, login, parity, type Step } from "./harness";

// The first top-bar menu: the Django summary inside details[data-nav-menu], or the React trigger button
// (NavMenu.tsx gives every DropMenu data-nav-trigger). Both are the first menu in DOM order.
// Scoped to the nav strip ([data-nav]) so the theme/user menus (also menus) are never picked first.
const FIRST_MENU = "[data-nav] details[data-nav-menu] > summary, [data-nav] [data-nav-trigger]";
// The first open-able panel of those menus (base.html and NavMenu.tsx both mark it data-nav-panel).
const FIRST_PANEL = "[data-nav-panel]";
// The theme menu trigger has the aria-label Өнгө on both sides. The React panel also carries that label, so the
// selector names the trigger element only.
const THEME_TRIGGER = 'button[aria-label="Өнгө"], summary[aria-label="Өнгө"]';
const DARK_CHOICE = '[data-theme-choice="dark"]';

// The demo user lands on the employee page of the day in Django; the React home route shows placeholder content,
// which the header clip leaves out.
const SIDES = [
  { name: "django", base: DJANGO_URL, path: "/employees/today/" },
  { name: "web", base: WEB_URL, path: "/" },
] as const;

const openFirstMenu: Step = async (page: Page) => {
  // At phone width today's Django bar leaves the strip almost no room (brand, search, theme and user take it),
  // so no strip menu is clickable there: compare the closed header only. Recorded in EXPECTED_DIFFS.md.
  if ((page.viewportSize()?.width ?? 1280) < 640) return;
  await page.locator(FIRST_MENU).first().click();
};

const closeWithEscape: Step = async (page: Page) => {
  await page.keyboard.press("Escape");
};

// Same address on both sides so the same nav item is active; React has no Today screen yet, so its catch-all
// page renders inside the shell and the header is what is compared (clip).
parity("shell-header", "/employees/today/", "/employees/today/", [openFirstMenu, closeWithEscape], {
  clip: "header",
  signIn: true,
});

// Signs in on one side and lands on its home page. Used by the checks below, which run on one page at a time.
async function openSignedIn(page: Page, side: (typeof SIDES)[number]): Promise<void> {
  await page.goto(side.base + side.path);
  await login(page, side.base);
  await page.waitForLoadState("networkidle");
}

test.describe("shell motion", () => {
  for (const side of SIDES) {
    test(`${side.name}: the opened nav panel animates with pal-in`, async ({ page }) => {
      await openSignedIn(page, side);
      await page.locator(FIRST_MENU).first().click();
      const panel = page.locator(FIRST_PANEL).first();
      await expect(panel).toBeVisible();
      const animationName = await panel.evaluate((el) => getComputedStyle(el).animationName);
      expect(animationName).toBe("pal-in");
    });
  }
});

test.describe("shell reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  for (const side of SIDES) {
    test(`${side.name}: the nav panel animation duration is 0s`, async ({ page }) => {
      await openSignedIn(page, side);
      await page.locator(FIRST_MENU).first().click();
      const panel = page.locator(FIRST_PANEL).first();
      await expect(panel).toBeVisible();
      const duration = await panel.evaluate((el) => getComputedStyle(el).animationDuration);
      expect(duration).toBe("0s");
    });
  }
});

test.describe("shell theme", () => {
  for (const side of SIDES) {
    test(`${side.name}: Бараан sets data-theme to dark`, async ({ page }) => {
      await openSignedIn(page, side);
      await page.locator(THEME_TRIGGER).first().click();
      await page.locator(DARK_CHOICE).first().click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    });
  }
});
