import { expect, test, type Browser, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, login, openPath, parity, type Step } from "./harness";

// Reports, step 5e: the selection bar's «Ажлаас гарах жагсаалт эхлүүлэх» action and its pop-up form (the result list is not
// reached). Read only: the spec ticks two rows and opens the form. It never presses «Эхлүүлэх»: that starts checklists in
// the shared demo database, both sides read the same database, and a second submit would answer «Нээлттэй байсан».
// Run as `hr` (signIn: true).
//
// Pixel case, one parity() per viewport and theme (the harness defaults: 1280 and 375 px, light and dark), on
// /reports/staff-list/. One step does the whole flow: «Сонгох» is turned on, the first two person rows are ticked
// (`tbody input[data-select-row]`), `#selection-bar [data-count]` reads 2, the bar's checklist button is clicked
// (`#selection-bar [data-action="checklist"]`, on both sides; Django's pop-up is an htmx POST that lands in the body),
// and the form's «Эхлүүлэх» button is awaited. Only the pop-up panel is compared (clip): the React `Modal` panel
// (`[role="dialog"][aria-modal="true"]`) and Django's panel (`div.fixed.inset-0 > div[class*="max-h-[90vh]"]`) are the same
// element on each side. The staff list behind the overlay is not compared, as in 5d (it differs by the edit legend, step 5f).
// Mask: the anchor-day box (`input[name="anchor_day"]`) on both sides. It holds today's date, which changes between runs,
// and Django draws a native date box where React draws its own date input.
//
// Text (one test, not pixels): each side signs in as `hr`, opens the staff list, picks the same two rows and opens the
// form. Compared: the pop-up heading (the first h2 of the panel) and its intro paragraph (the first p of the panel, with
// whitespace collapsed). The intro must read «Сонгосон 2 хүнд».
//
// Opening the pop-up reads its form only (the form read writes nothing).
//
// Known differences: none recorded yet. Record what the first run shows in EXPECTED_DIFFS.md, section «Step 5e (selected
// checklist pop-up)».

test.setTimeout(120_000);

const STAFF = "/reports/staff-list/";

// The pop-up panel on either side (see the header comment). `.first()` in the harness picks the one dialog open.
const PANEL = '[role="dialog"][aria-modal="true"], div.fixed.inset-0 > div[class*="max-h-[90vh]"]';
// The anchor-day box: holds today's date (see the header comment).
const DATE_MASK = ['input[name="anchor_day"]'];

// Ticks the first two person rows after «Сонгох», then opens the checklist pop-up from the bar and waits for its form.
const openChecklistForm: Step = async (page: Page) => {
  await page.locator("h1").first().waitFor();
  await page.locator("tbody tr").first().waitFor();
  await page.locator("[data-select-toggle]").click();
  const boxes = page.locator("tbody input[data-select-row]");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await expect(page.locator("#selection-bar [data-count]")).toHaveText("2");
  await page.locator('#selection-bar [data-action="checklist"]').click();
  await page.getByRole("button", { name: "Эхлүүлэх", exact: true }).waitFor();
};

// The pop-up form (pixels).
parity("report selection: the checklist pop-up with two people picked (staff list)", STAFF, STAFF, [openChecklistForm], {
  signIn: true,
  clip: PANEL,
  mask: DATE_MASK,
});

// ---- Text ------------------------------------------------------------------------------------------------------------

type FormText = { heading: string; intro: string };

// Opens the staff list signed in on one side, opens the pop-up for two picked people and reads its heading and intro.
// Nothing is submitted.
async function readFormText(browser: Browser, base: string): Promise<FormText> {
  const context = await browser.newContext({ reducedMotion: "no-preference" });
  try {
    const page = await context.newPage();
    await page.goto(base + STAFF);
    await login(page, base);
    await openPath(page, STAFF);
    await openChecklistForm(page);
    const panel = page.locator(PANEL).first();
    const clean = (text: string | null) => (text ?? "").replace(/\s+/g, " ").trim();
    return {
      heading: clean(await panel.locator("h2").first().textContent()),
      intro: clean(await panel.locator("p").first().textContent()),
    };
  } finally {
    await context.close();
  }
}

test.describe("report selection: checklist pop-up text", () => {
  test("heading and intro match on both servers for two picked people", async ({ browser }) => {
    const django = await readFormText(browser, DJANGO_URL);
    const web = await readFormText(browser, WEB_URL);

    expect(django.intro, "django intro").toContain("Сонгосон 2 хүнд");
    expect(web.intro, "web intro").toContain("Сонгосон 2 хүнд");
    expect(web.heading).toBe(django.heading);
    expect(web.intro).toBe(django.intro);
  });
});
