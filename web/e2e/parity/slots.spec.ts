import { expect, test, type Browser, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, login, openPath } from "./harness";

// Position-slot screen «Орон тооны төлөвлөгөө» at /employees/slots/: Django `slots_list.html` with `_slot_rows.html` and
// `_slot_form.html`, against SlotsPage.tsx, SlotsTable.tsx and SlotFormModal.tsx. Both sides use the same path.
//
// Read-only: nothing is created, edited or deleted. The add pop-up is opened, inspected and closed with Escape, and the
// empty submit is sent only to see the required-field message: the server refuses an empty row, so nothing is saved.
//
// Compared at 1280 px only (the 375 px run is skipped for this screen). The comparisons read the DOM, not screenshots:
// the heading, the year links, the table headings and the row count on the list page, and the pop-up's labels and
// buttons. Each side signs in on its own origin (harness `login`), then opens the page.
//
// Async rows: the React list loads over the API, so each side waits for the network to be idle and for the first table
// row (the empty-state row counts too) before it reads the page.
//
// Known differences: none recorded yet. The Django required-field text is read but only recorded (not failed) when it
// differs, as the case asks.

const VIEWPORT = { width: 1280, height: 800 } as const;
const MODAL = ".fixed.inset-0.z-50";
const LIST = "/employees/slots/";
const YEAR_2027 = "/employees/slots/?year=2027";
const EMPTY_2027 = "2027 оны орон тоо бүртгэгдээгүй";
const REQUIRED = "Энэ талбарыг бөглөх шаардлагатай.";
const LABELS = ["Албан тушаал", "Салбар", "Төрөл", "Он", "Орон тоо"];
const BUTTONS = ["Болих", "Хадгалах"];

// Each parity test runs two sides with several page loads: more than the 30 s default.
test.setTimeout(60_000);

// Waits until the table has rows on screen (the empty-state row is a row too).
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("tbody tr").first()).toBeVisible();
}

// Runs one read or pop-up check on each side at 1280 px: a fresh context, signed in, on `path`, settled. Returns both results.
async function bothAt1280<T>(browser: Browser, path: string, run: (page: Page) => Promise<T>): Promise<{ django: T; web: T }> {
  const onSide = async (base: string): Promise<T> => {
    const context = await browser.newContext({ viewport: VIEWPORT, reducedMotion: "no-preference", colorScheme: "light" });
    try {
      const page = await context.newPage();
      await page.goto(base + path);
      await login(page, base);
      await openPath(page, path);
      await settle(page);
      return await run(page);
    } finally {
      await context.close();
    }
  };
  const django = await onSide(DJANGO_URL);
  const web = await onSide(WEB_URL);
  return { django, web };
}

// The list snapshot: heading, year links, table headings, the number of data rows, and the empty-state text if any.
async function readList(page: Page) {
  const heading = (await page.locator("h1").first().innerText()).trim();
  const yearLinks = await page
    .locator("a")
    .filter({ hasText: /←\s*\d{4}|\d{4}\s*→/ })
    .allInnerTexts();
  const headings = (await page.locator("thead th").allInnerTexts()).map((text) => text.trim());
  // A data row has a bold position cell (the first cell, class font-medium) on both sides; the empty-state row and the
  // «Цааш харуулах» row do not.
  const dataRows = await page.locator("tbody tr > td:first-child.font-medium").count();
  const emptyText = (await page.locator("tbody tr td.text-slate-400").allInnerTexts()).map((text) => text.trim());
  return { heading, yearLinks: yearLinks.map((text) => text.trim()), headings, dataRows, emptyText };
}

// Opens the add pop-up from «Нэмэх» and waits until it is on screen.
async function openAdd(page: Page) {
  await page.getByRole("button", { name: "Нэмэх" }).click();
  await expect(page.locator(MODAL)).toBeVisible();
  // The React pop-up shows its fields only after the options answer arrives: wait for the form, not just the frame.
  await expect(page.locator(MODAL).getByText("Албан тушаал").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
}

test.describe("position slots (1280 px)", () => {
  test("list page: heading, year links, table headings and row count", async ({ browser }) => {
    const { django, web } = await bothAt1280(browser, LIST, readList);
    expect(web.heading).toMatch(/Орон тооны төлөвлөгөө — \d{4}/);
    expect(web.yearLinks).toHaveLength(2);
    expect(web.headings).toEqual(["Албан тушаал", "Салбар", "Төрөл", "Орон тоо", "Ашиглаж буй", "Сул"]);
    expect(django).toEqual(web);
  });

  test("year 2027 with no slots shows the empty text on both sides", async ({ browser }) => {
    const { django, web } = await bothAt1280(browser, YEAR_2027, async (page) => {
      const snapshot = await readList(page);
      const h1 = (await page.locator("h1").first().innerText()).trim();
      return { h1, empty: snapshot.emptyText, dataRows: snapshot.dataRows };
    });
    expect(web.h1).toBe("Орон тооны төлөвлөгөө — 2027");
    expect(web.dataRows).toBe(0);
    expect(web.empty).toContain(EMPTY_2027);
    expect(django).toEqual(web);
  });

  test("add pop-up shows its labels and buttons; Escape closes it", async ({ browser }) => {
    const { django, web } = await bothAt1280(browser, LIST, async (page) => {
      await openAdd(page);
      const modal = page.locator(MODAL);
      const text = await modal.innerText();
      const labels = LABELS.map((label) => ({ label, shown: text.includes(label) }));
      const buttons = await Promise.all(
        BUTTONS.map(async (name) => ({ name, shown: await modal.getByRole("button", { name }).isVisible() })),
      );
      await page.keyboard.press("Escape");
      // Give the close a moment; a pop-up that stays open is still on screen after this.
      await expect.poll(() => page.locator(MODAL).count(), { timeout: 3000 }).toBe(0).catch(() => {});
      const openAfterEscape = await page.locator(MODAL).count();
      return { labels, buttons, closedByEscape: openAfterEscape === 0 };
    });
    expect(web.labels.every((item) => item.shown), JSON.stringify(web.labels)).toBe(true);
    expect(web.buttons.every((item) => item.shown), JSON.stringify(web.buttons)).toBe(true);
    expect(web.closedByEscape).toBe(true);
    expect(django).toEqual(web);
  });

  test("submitting the add pop-up empty shows the required text", async ({ browser }, testInfo) => {
    const { django, web } = await bothAt1280(browser, LIST, async (page) => {
      await openAdd(page);
      const modal = page.locator(MODAL);
      await modal.getByRole("button", { name: "Хадгалах" }).click({ timeout: 5000 });
      // Wait for the required text (React: the API answer; Django: the htmx answer), or give up after a few seconds.
      await expect
        .poll(async () => (await modal.innerText()).includes(REQUIRED), { timeout: 5000 })
        .toBe(true)
        .catch(() => {});
      const text = await modal.innerText();
      const found = text.includes(REQUIRED);
      // Close without saving: Болих, then nothing is left open for the next run.
      await modal.getByRole("button", { name: "Болих" }).click({ timeout: 3000 }).catch(() => {});
      return { found };
    });
    // React is the checked side (the case's own text). Django is only recorded.
    expect(web.found, "React must show the required-field text").toBe(true);
    if (!django.found) {
      testInfo.annotations.push({
        type: "known-diff",
        description: `Django does not show «${REQUIRED}» after an empty submit (the React side shows it).`,
      });
    }
  });
});
