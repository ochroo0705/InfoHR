import { expect, test, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, login } from "./harness";

// Widget motion and behaviour, checked on the React demo page only (/__widgets, dev builds). The page shows the
// pop-up shell (Modal), the confirm dialog, Select, DatePicker, MoneyInput, the validation form and ScrollHost.
// The one Django check at the end compares the pop-up keyframes on a real Django page.

const PAGE = WEB_URL + "/__widgets";

// Pop-up shell: the overlay is .fixed.inset-0.z-50, its panel is the overlay's first child (motion.css).
const OVERLAY = ".fixed.inset-0.z-50";
const PANEL = ".fixed.inset-0.z-50 > div";
const SELECT_POPUP = ".sel-popup";
const DATE_POPUP = ".dp-popup";
// The confirm dialog is z-70, so it has its own selector. It has no enter animation; it plays the exit only.
const CONFIRM = ".hr-confirm";

type Anim = { name: string; duration: string };
type ExitSeen = { self: Anim; child: Anim | null };

async function openPage(page: Page): Promise<void> {
  await page.goto(PAGE);
  await page.waitForLoadState("networkidle");
}

// A duration token from :root, in the form Playwright reports computed durations: --dur-in 180ms becomes "0.18s".
async function tokenSeconds(page: Page, token: string): Promise<string> {
  const raw = await page.evaluate(
    (prop) => getComputedStyle(document.documentElement).getPropertyValue(prop).trim(),
    token,
  );
  return `${parseFloat(raw) / 1000}s`;
}

async function animOf(page: Page, selector: string): Promise<Anim> {
  return page.locator(selector).first().evaluate((el) => {
    const s = getComputedStyle(el);
    return { name: s.animationName, duration: s.animationDuration };
  });
}

// Installs a watcher for the element that starts its exit (data-leaving), then runs the action. The watcher is in
// place before the action, so the exit (140 ms) is read in its first frame. It records the element's own animation
// and the animation of its first child (the panel).
async function captureExit(page: Page, selector: string, action: () => Promise<void>): Promise<ExitSeen> {
  await page.evaluate((sel) => {
    const w = window as unknown as { __exitSeen?: unknown };
    w.__exitSeen = undefined;
    const read = (): boolean => {
      const el = document.querySelector<HTMLElement>(sel + "[data-leaving]");
      if (!el) return false;
      const s = getComputedStyle(el);
      const child = el.firstElementChild as HTMLElement | null;
      const cs = child ? getComputedStyle(child) : null;
      w.__exitSeen = {
        self: { name: s.animationName, duration: s.animationDuration },
        child: cs ? { name: cs.animationName, duration: cs.animationDuration } : null,
      };
      return true;
    };
    const observer = new MutationObserver(() => {
      if (read()) observer.disconnect();
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-leaving"] });
  }, selector);
  await action();
  await page.waitForFunction(() => (window as unknown as { __exitSeen?: unknown }).__exitSeen !== undefined);
  return page.evaluate(() => (window as unknown as { __exitSeen: ExitSeen }).__exitSeen);
}

test.describe("widget motion tokens", () => {
  test("modal: the overlay fades in with hr-fade, the panel lifts with hr-pop, and the exit uses --dur-out", async ({
    page,
  }) => {
    await openPage(page);
    const panelIn = await tokenSeconds(page, "--dur-in");
    const panelOut = await tokenSeconds(page, "--dur-out");

    await page.getByRole("button", { name: "Цэвэр pop-up нээх" }).click();
    await expect(page.locator(OVERLAY)).toBeVisible();
    // The overlay keeps the Django value (input.css 214, .15s). The panel uses --dur-in.
    expect(await animOf(page, OVERLAY)).toEqual({ name: "hr-fade", duration: "0.15s" });
    expect(await animOf(page, PANEL)).toEqual({ name: "hr-pop", duration: panelIn });

    const exit = await captureExit(page, OVERLAY, () => page.locator("[data-modal-x]").click());
    expect(exit.self).toEqual({ name: "hr-leave", duration: panelOut });
    expect(exit.child).toEqual({ name: "hr-leave-pop", duration: panelOut });
    await expect(page.locator(OVERLAY)).toHaveCount(0);
  });

  test("select and date popups: enter with hr-pop-in on --dur-in, exit with hr-leave on --dur-out", async ({ page }) => {
    await openPage(page);
    const enter = await tokenSeconds(page, "--dur-in");
    const exitDur = await tokenSeconds(page, "--dur-out");

    // The 5-option select is a click list. Its popup takes focus, so Escape goes to the list.
    await page.locator("#widgets-dept").click();
    await expect(page.locator(SELECT_POPUP)).toBeVisible();
    expect(await animOf(page, SELECT_POPUP)).toEqual({ name: "hr-pop-in", duration: enter });
    const selExit = await captureExit(page, SELECT_POPUP, () => page.keyboard.press("Escape"));
    expect(selExit.self).toEqual({ name: "hr-leave", duration: exitDur });
    await expect(page.locator(SELECT_POPUP)).toHaveCount(0);

    // The day picker: its input keeps focus, so Escape goes to the input.
    await page.locator("#widgets-birth").click();
    await expect(page.locator(DATE_POPUP)).toBeVisible();
    expect(await animOf(page, DATE_POPUP)).toEqual({ name: "hr-pop-in", duration: enter });
    const dateExit = await captureExit(page, DATE_POPUP, () => page.keyboard.press("Escape"));
    expect(dateExit.self).toEqual({ name: "hr-leave", duration: exitDur });
    await expect(page.locator(DATE_POPUP)).toHaveCount(0);
  });

  test("confirm: no enter animation, and the exit plays hr-leave and hr-leave-pop", async ({ page }) => {
    await openPage(page);
    const exitDur = await tokenSeconds(page, "--dur-out");

    await page.getByRole("button", { name: "Энгийн асуулт" }).click();
    await expect(page.getByRole("alertdialog", { name: "Хадгалах уу?" })).toBeVisible();
    expect(await animOf(page, CONFIRM)).toEqual({ name: "none", duration: "0s" });

    const exit = await captureExit(page, CONFIRM, () => page.locator(".hr-confirm-no").click());
    expect(exit.self).toEqual({ name: "hr-leave", duration: exitDur });
    expect(exit.child).toEqual({ name: "hr-leave-pop", duration: exitDur });
    await expect(page.locator(CONFIRM)).toHaveCount(0);
    await expect(page.getByText("Сүүлийн хариулт: Болих")).toBeVisible();
  });
});

test.describe("widget reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("every widget animation and transition duration is 0s", async ({ page }) => {
    await openPage(page);

    await page.getByRole("button", { name: "Цэвэр pop-up нээх" }).click();
    await expect(page.locator(OVERLAY)).toBeVisible();
    expect((await animOf(page, OVERLAY)).duration).toBe("0s");
    expect((await animOf(page, PANEL)).duration).toBe("0s");
    // Reduced motion also removes the pop-up at once, with no exit phase.
    await page.locator("[data-modal-x]").click();
    await expect(page.locator(OVERLAY)).toHaveCount(0);

    await page.locator("#widgets-dept").click();
    await expect(page.locator(SELECT_POPUP)).toBeVisible();
    expect((await animOf(page, SELECT_POPUP)).duration).toBe("0s");
    await page.keyboard.press("Escape");
    await expect(page.locator(SELECT_POPUP)).toHaveCount(0);

    await page.locator("#widgets-birth").click();
    await expect(page.locator(DATE_POPUP)).toBeVisible();
    expect((await animOf(page, DATE_POPUP)).duration).toBe("0s");
    await page.keyboard.press("Escape");
    await expect(page.locator(DATE_POPUP)).toHaveCount(0);

    const transition = await page
      .getByRole("button", { name: "Цэвэр pop-up нээх" })
      .evaluate((el) => getComputedStyle(el).transitionDuration);
    expect(transition).toBe("0s");
  });
});

test.describe("widget keyboard order", () => {
  test("Escape closes an inner picker first, then the modal", async ({ page }) => {
    await openPage(page);
    await page.getByRole("button", { name: "Цэвэр pop-up нээх" }).click();
    const dialog = page.getByRole("dialog", { name: "Цэвэр pop-up" });
    await expect(dialog).toBeVisible();

    await page.locator("#widgets-modal-date").click();
    await expect(page.locator(DATE_POPUP)).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.locator(DATE_POPUP)).toHaveCount(0);
    await expect(dialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.locator(OVERLAY)).toHaveCount(0);
  });
});

test.describe("widget dirty modal", () => {
  test("a typed-in modal asks before Escape, the ✕ or an outside click throws the input away", async ({ page }) => {
    await openPage(page);
    await page.getByRole("button", { name: "Бичсэн pop-up нээх" }).click();
    const dialog = page.getByRole("dialog", { name: "Бичсэн pop-up" });
    await dialog.getByLabel("Нэр", { exact: true }).fill("Бат");

    const ask = page.getByRole("alertdialog", { name: "Оруулсан мэдээлэл хадгалагдахгүй. Хаах уу?" });
    await page.keyboard.press("Escape");
    await expect(ask).toBeVisible();
    await expect(dialog).toBeVisible();

    // «Болих» keeps the pop-up and the typed text.
    await page.locator(".hr-confirm-no").click();
    await expect(ask).toHaveCount(0);
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Нэр", { exact: true })).toHaveValue("Бат");

    // The ✕ asks too; «Хаах» closes the pop-up.
    await dialog.locator("[data-modal-x]").click();
    await expect(ask).toBeVisible();
    await page.locator(".hr-confirm-yes").click();
    await expect(dialog).toHaveCount(0);
  });
});

test.describe("ScrollHost demo", () => {
  test("the 200px box with 30 lines shows a vertical rail whose fill follows the scroll", async ({ page }) => {
    await openPage(page);
    const block = page.locator('[data-testid="widgets-scrollhost"]');
    const box = block.locator(".sbar-on");
    const rail = block.locator(".sbar-y");
    await expect(rail).toHaveClass(/is-on/);

    const measure = () =>
      rail.evaluate((r) => ({
        track: r.clientHeight,
        thumb: parseFloat((r.querySelector(".sbar-thumb") as HTMLElement).style.height) || 0,
      }));

    const top = await measure();
    expect(top.thumb).toBeGreaterThan(0);
    expect(top.thumb).toBeLessThan(top.track);

    await box.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    await expect
      .poll(async () => (await measure()).thumb)
      .toBe((await measure()).track);
  });
});

test.describe("widget screenshots", () => {
  for (const theme of ["light", "dark"] as const) {
    test.describe(theme, () => {
      test.use({ colorScheme: theme });

      test(`the demo page in ${theme}`, async ({ page }) => {
        await page.addInitScript((value: string) => {
          try {
            localStorage.setItem("theme", value);
          } catch {
            // Storage blocked: the page falls back to the system setting (colorScheme above).
          }
        }, theme);
        await openPage(page);
        await expect(page).toHaveScreenshot(`widgets-${theme}.png`, {
          fullPage: true,
          animations: "disabled",
          caret: "hide",
        });
      });
    });
  }
});

// Django side: the same pop-up keyframes on a real Django page. It opens the event menu of an employee page, whose
// menu items load into #modal (hx-target="#modal"). If the demo user cannot reach such a page, the test is skipped.
test.describe("django pop-up motion", () => {
  test("a Django pop-up panel animates with hr-pop", async ({ page }) => {
    await page.goto(DJANGO_URL + "/employees/");
    await login(page, DJANGO_URL);
    await page.goto(DJANGO_URL + "/employees/");
    await page.waitForLoadState("networkidle");

    const hrefs = await page
      .locator("a[href]")
      .evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
    const detail = hrefs.find((h) => /^\/employees\/\d+\/$/.test(h));
    test.skip(
      !detail,
      "The staff list shows no link to an employee page for the demo user, so there is no pop-up opener to reach.",
    );
    await page.goto(DJANGO_URL + (detail ?? "/employees/"));
    await page.waitForLoadState("networkidle");

    const menu = page.locator("summary", { hasText: "Өөрчлөлт бүртгэх" });
    test.skip(
      (await menu.count()) === 0,
      "The event menu (Өөрчлөлт бүртгэх) is not shown for the demo user on this employee page.",
    );
    await menu.click();
    await page.locator('details[open] [hx-target="#modal"]').first().click();

    const panel = page.locator(PANEL).first();
    await expect(panel).toBeVisible();
    const name = await panel.evaluate((el) => getComputedStyle(el).animationName);
    expect(name).toBe("hr-pop");
  });
});
