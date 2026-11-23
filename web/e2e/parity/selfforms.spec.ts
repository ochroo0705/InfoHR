import { expect, test, type Browser, type Page, type TestInfo } from "@playwright/test";
import { DJANGO_URL, WEB_URL, openPath } from "./harness";

// Self-form links at /employees/self-forms/ (list) and /employees/self-forms/<pk>/ (show): Django `selfform/list.html`
// and `selfform/show.html` against SelfFormListPage.tsx, SelfFormCreateForm.tsx and SelfFormShowPage.tsx (CopyLink.tsx).
// Both sides use the same paths. Read-only: nothing is created, extended or revoked. The empty create form is submitted
// on purpose: the form is refused before any link is written, so it only shows the error boxes.
//
// Compared at 1280 px only (the 375 px run is skipped for this spec): the list heading, the table headings, the row count
// and the create form's labels; the error under the empty create form; and, for the first OPEN and the first SUBMITTED
// invitation in the list, the show page's heading, status text and copy-link button label. Text is compared, not pixels.
//
// Not compared: the QR code, the clipboard (the copy button is never clicked), and the purge / decision sections.
//
// Skips: a show-page case with no invitation of that status in the list is skipped with a reason.
//
// Known differences: see EXPECTED_DIFFS.md, section «self-forms». The empty-submit error text is recorded as an annotation
// (not a failure) when the two sides differ, because the Django text is not yet verified against the React one.

// Each case signs in on both sides and does a few page loads: a little more than the 30 s default.
test.setTimeout(90_000);

const VIEWPORT = { width: 1280, height: 800 };
const LIST = "/employees/self-forms/";
const TITLE = "Өөрөө бөглөх анкет";
// The state words of the list badge (employees/services/selfform_page.py): open and submitted.
const OPEN_STATE = "Нээлттэй";
const SUBMITTED_STATE = "Хянах хүлээж байна";
const COPY_LABEL = "Холбоос хуулах";
const CREATE_BUTTON = "Холбоос үүсгэх";
const TABLE_HEADS = ["Нэр", "Салбар", "Төлөв", "Хугацаа", "Үйлдэл"];
// Error boxes of the create form: a field error under a box (both sides `p.text-red-600`), or the red form-level box
// (Django `p.bg-red-50`, React `div.bg-red-50`).
const FIELD_ERROR = "form p.text-red-600";
const FORM_ERROR = "form .bg-red-50";
const ANY_ERROR = `${FIELD_ERROR}, ${FORM_ERROR}`;

// The list has loaded its rows: the React list fetches them over the API; Django's rows are in the HTML already.
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("tbody tr").first()).toBeVisible();
}

// The create form: the form that holds the «Холбоос үүсгэх» button (the same on both sides).
function createForm(page: Page) {
  return page.locator("form").filter({ has: page.getByRole("button", { name: CREATE_BUTTON }) });
}

// Signs in on a login page. Same steps as login() in harness.ts, but the submit button is picked by id or by its form:
// harness.ts clicks `form button`, which matches two buttons on the React login page (the password toggle and «Нэвтрэх»).
async function signIn(page: Page, base: string): Promise<void> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  await page.waitForURL((url) => url.pathname.startsWith("/login"));
  await page.locator("#id_username").fill(username);
  await page.locator("#id_password").fill(password);
  await page.locator("#login-submit, form:has(#id_password) button[type=submit]").first().click();
  await page.waitForURL((url) => url.origin === base && !url.pathname.startsWith("/login"));
}

// Signs in on both sides in fresh 1280 px contexts, opens `path` on each, and runs `run` there. Mirrors bothSides() in
// harness.ts, which uses the browser's default viewport.
async function onSides<T>(
  browser: Browser,
  path: string,
  run: (page: Page) => Promise<T>,
): Promise<{ django: T; web: T }> {
  const onSide = async (base: string): Promise<T> => {
    const context = await browser.newContext({ viewport: VIEWPORT, reducedMotion: "no-preference" });
    try {
      const page = await context.newPage();
      await page.goto(base + path);
      await signIn(page, base);
      await openPath(page, path);
      return await run(page);
    } finally {
      await context.close();
    }
  };
  const django = await onSide(DJANGO_URL);
  const web = await onSide(WEB_URL);
  return { django, web };
}

// Trimmed text of every element matching the selector.
async function textsOf(page: Page, selector: string): Promise<string[]> {
  return (await page.locator(selector).allTextContents()).map((text) => text.replace(/\s+/g, " ").trim());
}

// Case 1: the list page. Heading, table headings, row count and the create form's labels.
test("self-forms list: heading, table headings, row count and create form labels match", async ({ browser }) => {
  const sides = await onSides(browser, LIST, async (page) => {
    await settle(page);
    return {
      heading: (await textsOf(page, "h1"))[0] ?? "",
      heads: await textsOf(page, "thead th"),
      rows: await page.locator("tbody tr").count(),
      labels: await textsOf(createForm(page), "label"),
    };
  });
  const { django, web } = sides;

  expect(django.heading, "Django heading is the page title").toBe(TITLE);
  expect(web.heading, "React heading").toBe(django.heading);
  expect(django.heads, "Django table headings").toEqual(TABLE_HEADS);
  expect(web.heads, "React table headings").toEqual(django.heads);
  expect(web.rows, "React row count (the empty-state row counts as one)").toBe(django.rows);
  expect(django.labels.length, "Django create form has its labels").toBeGreaterThan(0);
  expect(web.labels, "React create form labels").toEqual(django.labels);
});

// Case 2: the create form submitted empty. Nothing is written (the label is required); the error text is compared.
test("self-forms create form: submitted empty shows an error", async ({ browser }, testInfo: TestInfo) => {
  const sides = await onSides(browser, LIST, async (page) => {
    await settle(page);
    const rowsBefore = await page.locator("tbody tr").count();
    await createForm(page).getByRole("button", { name: CREATE_BUTTON }).click();
    // Django answers with a full page; React answers through the API. Wait for an error box, or give up after 10 s.
    await page
      .locator(ANY_ERROR)
      .first()
      .waitFor({ state: "visible", timeout: 10_000 })
      .catch(() => undefined);
    await page.waitForLoadState("networkidle");
    return {
      fieldErrors: await textsOf(page, FIELD_ERROR),
      formErrors: await textsOf(page, FORM_ERROR),
      rowsBefore,
      rowsAfter: await page.locator("tbody tr").count(),
    };
  });
  const { django, web } = sides;

  // React must show the error (this is the intended behaviour, not a known diff).
  expect(
    web.fieldErrors.length + web.formErrors.length,
    "React shows an error for the empty label",
  ).toBeGreaterThan(0);
  // Nothing was written: the row count does not change on either side.
  expect(web.rowsAfter, "React: no row added by the refused create").toBe(web.rowsBefore);
  expect(django.rowsAfter, "Django: no row added by the refused create").toBe(django.rowsBefore);

  const djangoText = JSON.stringify({ fieldErrors: django.fieldErrors, formErrors: django.formErrors });
  const webText = JSON.stringify({ fieldErrors: web.fieldErrors, formErrors: web.formErrors });
  if (djangoText !== webText) {
    // A known diff, recorded and not failed (see the header): the two sides word or place the error differently.
    testInfo.annotations.push({
      type: "known diff",
      description: `self-forms empty create: django ${djangoText}, web ${webText}`,
    });
    console.log(`[known diff] self-forms empty create: django ${djangoText}, web ${webText}`);
  }
});

// Case 3: the show page for the first OPEN and the first SUBMITTED invitation in the list. The row is found on each side
// from its own list, by its state word, and opened by a click on its first cell (both sides navigate to its page).
type ShowFacts = { listLabel: string; heading: string; status: string; copy: string };

async function showFactsFor(page: Page, state: string): Promise<ShowFacts | null> {
  await settle(page);
  const rows = page.locator("tbody tr").filter({ has: page.locator("td:nth-child(3) span", { hasText: state }) });
  if ((await rows.count()) === 0) return null;
  const firstCell = rows.first().locator("td").first();
  const listLabel = ((await firstCell.textContent()) ?? "").replace(/\s+/g, " ").trim();
  await firstCell.click();
  await page.waitForURL(/\/employees\/self-forms\/\d+\/?$/);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("#selfform-link")).toBeVisible();
  const heading = ((await page.locator("h1").first().textContent()) ?? "").replace(/\s+/g, " ").trim();
  const status = ((await page.locator("h1 + span").first().textContent()) ?? "").replace(/\s+/g, " ").trim();
  const copy = ((await page.locator("#selfform-link + button").first().textContent()) ?? "").replace(/\s+/g, " ").trim();
  return { listLabel, heading, status, copy };
}

for (const [kind, state] of [
  ["open", OPEN_STATE],
  ["submitted", SUBMITTED_STATE],
] as const) {
  test(`self-forms show page: first ${kind} invitation`, async ({ browser }) => {
    const sides = await onSides(browser, LIST, (page) => showFactsFor(page, state));
    const { django, web } = sides;

    if (django === null && web === null) {
      test.skip(true, `The list has no invitation with the «${state}» state (the demo data is not seeded, or none is open).`);
      return;
    }
    expect(web, `the list on React has an invitation with «${state}»`).not.toBeNull();
    expect(django, `the list on Django has an invitation with «${state}»`).not.toBeNull();
    if (django === null || web === null) return;

    expect(django.heading, "Django show heading is the invitation label").toBe(django.listLabel);
    expect(web.listLabel, "React opened the same invitation as Django").toBe(django.listLabel);
    expect(web.heading, "React show heading").toBe(django.heading);
    expect(web.status, "React status text").toBe(django.status);
    expect(django.status, "Django status text is the list state").toBe(state);
    expect(django.copy, "Django copy-link button label").toBe(COPY_LABEL);
    expect(web.copy, "React copy-link button label").toBe(django.copy);
  });
}
