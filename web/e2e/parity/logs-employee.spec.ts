import { expect, request, test, type Page } from "@playwright/test";
import { DJANGO_URL, openPath, parity, type Step } from "./harness";

// Employee log («Ажилтны бүртгэл») at /logs/: Django logs/employee.html with its row partials (_employee_rows.html,
// _employee_items.html) against EmployeeLogPage (EmployeeLogFilters.tsx, EmployeeLogTable.tsx, CheckMenu.tsx). Both sides
// use the same path. Read-only: every step opens a filter, a pop-up or a batch, and nothing is saved or submitted.
//
// Which user: `hr` (the PARITY_USER of the other specs). The employee log needs `macs.view_employees` and sees the people
// the scope allows; `hr` holds the log rights the other specs already rely on. The system log is in logs-system.spec.ts.
//
// Which employee for `?employee=<pk>`: Болд (seed_demo's `bold` login), the same person the other specs use. His pk is
// read from the staff-list report (/reports/staff-list/?q=Болд) by an authenticated request, as employee.spec.ts does.
//
// Compared, after each step: the whole page (screenshot) and the focused element id. Each scenario is also run at 1280 and
// 375 px in light and dark (the harness runs all four). The harness hides the Django-only `[data-assistant-fab]` button
// in every screenshot (EXPECTED_DIFFS, «employee activity drawer»).
//
// Not compared, asserted per side: the Excel link's `href` path. Django's link is `/logs/export/`; React's is
// `/api/v1/logs/employee/export`. The step reads the link on the side it runs on and checks its own path; the query part
// is not compared.
//
// Async rows: the React log loads over the API, so every step waits for the network to be idle and for the first row.
//
// Batch pill («Цааш харуулах», `[data-more-batch]`): it shows only when the address has more than 60 rows (config/batching.py,
// LIST_BATCH). With fewer rows the pill step skips with a reason. Django loads the next batch when the pill is revealed
// (htmx `revealed`); React through an IntersectionObserver. Scrolling the pill into view triggers both.
//
// Order pop-up: a row with an order carries `cursor-pointer` on both sides (Django `_employee_items.html`, React
// EmployeeLogTable). A click on that row opens the order detail pop-up. If the first batch has no such row, the step skips.
//
// Known differences: none recorded yet. Record any the first run shows in EXPECTED_DIFFS.md, section «employee log».

const MODAL = ".fixed.inset-0.z-50";
const STAFF_LIST = "/reports/staff-list/";
const EMPLOYEE_NAME = "Болд";
const LOG = "/logs/";
const EXCEL = "#log-excel";
// The Excel link's path, per side (the page's own origin decides which side it is).
const DJANGO_EXCEL_PATH = "/logs/export/";
const REACT_EXCEL_PATH = "/api/v1/logs/employee/export";
// Rows of the log table, not counting the «Цааш харуулах» row and not the empty-state row.
const LOG_ROWS = "tbody tr:not([data-more-row])";
const PILL = "[data-more-batch]";
const ORDER_ROW = "tbody tr.cursor-pointer";
// The «Төрөл» panel's summary (the <details> of the kind filter). Scoped to <summary> so the table's «Төрөл» head is not hit.
const KIND_SUMMARY = "summary";
const KIND_LABEL = "Төрөл";
// A search text that the seeded log rows are expected to contain. Both sides run the same search, so an empty result is a
// valid comparison too; the spec does not depend on the rows matching.
const SEARCH_TEXT = "Болд";

// Each parity test signs in on both sides and opens the log on both: with a pop-up or a batch step it needs more than 30 s.
test.setTimeout(60_000);

let employeePk = 0;

test.beforeAll(async () => {
  employeePk = await findEmployeePk(EMPLOYEE_NAME);
});

// Signs in to Django with the login form (PARITY_USER / PARITY_PASSWORD), then reads the staff-list report for the name.
// The row that names the employee holds the link to its page; its pk is the number in that link.
async function findEmployeePk(name: string): Promise<number> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  const api = await request.newContext({ baseURL: DJANGO_URL });
  try {
    const loginPage = await api.get("/login/");
    const token = (await loginPage.text()).match(/name="csrfmiddlewaretoken" value="([^"]+)"/)?.[1];
    if (!token) throw new Error("No CSRF token on Django /login/.");
    const signedIn = await api.post("/login/", { form: { username, password, csrfmiddlewaretoken: token } });
    if (new URL(signedIn.url()).pathname.startsWith("/login")) {
      throw new Error("Sign-in to Django failed for the parity account (check PARITY_USER / PARITY_PASSWORD).");
    }
    const report = await (await api.get(`${STAFF_LIST}?q=${encodeURIComponent(name)}`)).text();
    for (const row of report.split(/<tr[\s>]/)) {
      if (!row.includes(name)) continue;
      const match = row.match(/href="\/employees\/(\d+)\/"/);
      if (match) return Number(match[1]);
    }
    throw new Error(`No staff-list row names "${name}" with a link to /employees/<pk>/ (is the demo data seeded?).`);
  } finally {
    await api.dispose();
  }
}

// Waits until the log has its rows on this side (the empty state is a row too, so the wait holds for an empty result).
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("tbody tr").first()).toBeVisible();
}

// Opens the log address on this side (the harness signed in and landed on the home page), then waits for the rows.
function visit(path: string): Step {
  return async (page) => {
    await openPath(page, path);
    await settle(page);
  };
}

// Step: opens the «Төрөл» panel by its summary. Both sides draw it as a <details>; the step clicks its summary.
const openKindPanel: Step = async (page) => {
  await page.locator(KIND_SUMMARY, { hasText: KIND_LABEL }).first().click();
  await expect(page.locator("details[open]").first()).toBeVisible();
};

// Step: the batch pill scrolls into view and loads the next batch. Both sides must show more rows afterwards.
const loadNextBatch: Step = async (page) => {
  const pill = page.locator(PILL);
  if ((await pill.count()) === 0) {
    test.skip(true, "The log has 60 rows or fewer, so no «Цааш харуулах» pill is drawn (needs 61 or more rows).");
    return;
  }
  const before = await page.locator(LOG_ROWS).count();
  await pill.first().scrollIntoViewIfNeeded();
  // Django's htmx `revealed` fires on a scroll event, and the table box fits the screen so the pill can already be in
  // view: scroll the box itself to its end so both sides see a scroll.
  await page.locator(".ptable").first().evaluate((box) => {
    box.scrollTop = box.scrollHeight;
  });
  // Known Django gap (EXPECTED_DIFFS): inside the scrolling table box htmx `revealed` may never fire, so the pill is clicked
  // when scrolling loaded nothing (its `click` trigger is the other way the pill loads; React loads on scroll alone).
  await page.waitForTimeout(3000);
  if ((await page.locator(LOG_ROWS).count()) === before && (await pill.count()) > 0) await pill.first().click();
  await expect.poll(() => page.locator(LOG_ROWS).count(), { timeout: 15_000 }).toBeGreaterThan(before);
  await settle(page);
};

// Step: a click on the first row that carries an order opens the order detail pop-up. The click is on the message cell
// (the last cell), which both sides leave to the row's own handler. Skipped with a reason when no such row is on screen.
const openOrderEntry: Step = async (page) => {
  const row = page.locator(ORDER_ROW).first();
  if ((await row.count()) === 0) {
    test.skip(true, "The first batch of the employee log has no entry with an order (nothing to open).");
    return;
  }
  await row.locator("td").last().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await expect(page.locator(`${MODAL} h3`).first()).toBeVisible();
};

// Step: the Excel link's path on this side. The side is read from the page's origin: DJANGO_URL is Django, anything else
// is the React page. Only the path is checked; the query part (the cleaned filters) is not compared.
const excelPathPerSide: Step = async (page) => {
  const link = page.locator(EXCEL);
  if ((await link.count()) === 0) {
    test.skip(true, "The Excel link is hidden: the parity account has no export right for the employee log.");
    return;
  }
  const href = await link.first().getAttribute("href");
  expect(href, "the Excel link has no href").toBeTruthy();
  const onDjango = new URL(page.url()).origin === new URL(DJANGO_URL).origin;
  const expected = onDjango ? DJANGO_EXCEL_PATH : REACT_EXCEL_PATH;
  expect(new URL(href ?? "", page.url()).pathname).toBe(expected);
};

// The address with a filter: the value is encoded so the Cyrillic text and the separators are sent as a browser sends them.
const searchPath = `${LOG}?q=${encodeURIComponent(SEARCH_TEXT)}`;

// Default view: the newest first, no filter.
parity("employee log: default", LOG, LOG, [visit(LOG)], { signIn: true });

// The text search.
parity("employee log: search", searchPath, searchPath, [visit(searchPath)], { signIn: true });

// The kind filter, repeated: two kinds in the address (the panel shows «· 2» on both sides).
parity(
  "employee log: kinds correction and note",
  `${LOG}?kind=correction&kind=note`,
  `${LOG}?kind=correction&kind=note`,
  [visit(`${LOG}?kind=correction&kind=note`)],
  { signIn: true },
);

// The area filter: the orders area.
parity("employee log: area orders", `${LOG}?area=orders`, `${LOG}?area=orders`, [visit(`${LOG}?area=orders`)], {
  signIn: true,
});

// The date range, from and to.
parity(
  "employee log: date range 2026",
  `${LOG}?from=2026-01-01&to=2026-12-31`,
  `${LOG}?from=2026-01-01&to=2026-12-31`,
  [visit(`${LOG}?from=2026-01-01&to=2026-12-31`)],
  { signIn: true },
);

// The oldest-first order.
parity("employee log: oldest first", `${LOG}?oldest=1`, `${LOG}?oldest=1`, [visit(`${LOG}?oldest=1`)], { signIn: true });

// The person chip: Болд's pk in the address. Both sides show the chip with his name and the rows of his entries.
// The pk is known only after beforeAll, so the address is built by the step (the paths passed to parity() are only the
// first load that starts the sign-in).
parity(
  "employee log: one employee",
  LOG,
  LOG,
  [
    async (page) => {
      await visit(`${LOG}?employee=${employeePk}`)(page);
    },
  ],
  { signIn: true },
);

// Junk in the address: an unknown kind and an unknown area. Both sides drop them (the Excel link and the address too).
parity(
  "employee log: junk address",
  `${LOG}?kind=zzz&area=bogus`,
  `${LOG}?kind=zzz&area=bogus`,
  [visit(`${LOG}?kind=zzz&area=bogus`)],
  { signIn: true },
);

// The «Төрөл» panel opened on the default view.
parity("employee log: kind panel open", LOG, LOG, [visit(LOG), openKindPanel], { signIn: true });

// The «Цааш харуулах» pill loads the next batch. Skipped when the log has 60 rows or fewer.
parity("employee log: pill loads the next batch", LOG, LOG, [visit(LOG), loadNextBatch], { signIn: true });

// A click on an order entry opens the same order detail pop-up on both sides. Skipped when no entry has an order.
parity("employee log: order entry opens the pop-up", LOG, LOG, [visit(LOG), openOrderEntry], { signIn: true });

// The Excel link's path, per side (not compared with the other side).
parity("employee log: Excel link path", LOG, LOG, [visit(LOG), excelPathPerSide], { signIn: true });
