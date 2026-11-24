import { expect, test, type Page } from "@playwright/test";
import { DJANGO_URL, openPath, parity, type Step } from "./harness";

// System log («Системийн бүртгэл») at /logs/system/: Django logs/system.html with its row partials (_system_rows.html,
// _system_items.html) against SystemLogPage (SystemLogFilters.tsx, SystemLogTable.tsx, CheckMenu.tsx). Both sides use the
// same path. Read-only: every step opens a filter panel, a batch or a page state, and nothing is saved or submitted.
//
// Which user: this spec uses the harness's login, which reads PARITY_USER and PARITY_PASSWORD (one credential pair per
// run; harness.ts has no per-spec user). The system log needs `accounts.view_audit`, which the `hr` account does not hold,
// so run this file with an account that does. Use the superuser `admin` (demo login, seed_demo.py): it sees every tab and
// the Excel link, so every scenario runs. Example:
//   PARITY_USER=admin PARITY_PASSWORD=... npx playwright test logs-system
// The `auditor` demo login also works for the page itself, but it holds no `view_employees`, so the tab set differs from
// `hr`'s and the Excel link needs `export_lists` (granted to it only if seeded). Prefer `admin` for this file.
//
// Compared, after each step: the whole page (screenshot) and the focused element id, at 1280 and 375 px, light and dark.
// The harness hides the Django-only `[data-assistant-fab]` button in every screenshot (EXPECTED_DIFFS).
//
// Not compared, asserted per side: the Excel link's `href` path. Django's link is `/logs/system/export/`; React's is
// `/api/v1/logs/system/export`. The step reads the link on the side it runs on and checks its own path; the query is not
// compared.
//
// The system log has no order pop-up and no person chip (its rows are not linked to an order or to an employee filter),
// so those scenarios are not in this file. Its junk address uses an unknown category, since the system log has no `kind`
// parameter (the employee log's `kind` is a different filter).
//
// Batch pill («Цааш харуулах», `[data-more-batch]`): shown only with more than 60 rows (config/batching.py, LIST_BATCH).
// The pill step skips with a reason when the page has 60 rows or fewer.
//
// Known differences: none recorded yet. Record any the first run shows in EXPECTED_DIFFS.md, section «system log».

const MODAL = ".fixed.inset-0.z-50";
const SYSTEM_LOG = "/logs/system/";
const EXCEL = "#log-excel";
// The Excel link's path, per side (the page's own origin decides which side it is).
const DJANGO_EXCEL_PATH = "/logs/system/export/";
const REACT_EXCEL_PATH = "/api/v1/logs/system/export";
// Rows of the log table, not counting the «Цааш харуулах» row and not the empty-state row.
const LOG_ROWS = "tbody tr:not([data-more-row])";
const PILL = "[data-more-batch]";
// The «Ангилал» panel's summary (the <details> of the category filter). Scoped to <summary>, so the table head is not hit.
const CATEGORY_SUMMARY = "summary";
const CATEGORY_LABEL = "Ангилал";
// Category values as stored (app/accounts/audit.py Category): access, settings, import, export, hr.
const CATEGORY_ONE = "access";
const CATEGORY_TWO = "export";
// A search text. Both sides run the same search, so an empty result is still a valid comparison.
const SEARCH_TEXT = "нэвтэрсэн";

// Each parity test signs in on both sides and opens the log on both: with a batch step it needs more than 30 s.
test.setTimeout(60_000);

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

// Step: opens the «Ангилал» panel by its summary. Both sides draw it as a <details>; the step clicks its summary.
const openCategoryPanel: Step = async (page) => {
  await page.locator(CATEGORY_SUMMARY, { hasText: CATEGORY_LABEL }).first().click();
  await expect(page.locator("details[open]").first()).toBeVisible();
};

// Step: the batch pill scrolls into view and loads the next batch. Both sides must show more rows afterwards.
const loadNextBatch: Step = async (page) => {
  const pill = page.locator(PILL);
  if ((await pill.count()) === 0) {
    test.skip(true, "The system log has 60 rows or fewer, so no «Цааш харуулах» pill is drawn (needs 61 or more rows).");
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

// Step: the Excel link's path on this side. The side is read from the page's origin: DJANGO_URL is Django, anything else
// is the React page. Only the path is checked; the query part (the cleaned filters) is not compared.
const excelPathPerSide: Step = async (page) => {
  const link = page.locator(EXCEL);
  if ((await link.count()) === 0) {
    test.skip(true, "The Excel link is hidden: the parity account has no export right for the system log.");
    return;
  }
  const href = await link.first().getAttribute("href");
  expect(href, "the Excel link has no href").toBeTruthy();
  const onDjango = new URL(page.url()).origin === new URL(DJANGO_URL).origin;
  const expected = onDjango ? DJANGO_EXCEL_PATH : REACT_EXCEL_PATH;
  expect(new URL(href ?? "", page.url()).pathname).toBe(expected);
};

const searchPath = `${SYSTEM_LOG}?q=${encodeURIComponent(SEARCH_TEXT)}`;

// Default view: the newest first, no filter.
parity("system log: default", SYSTEM_LOG, SYSTEM_LOG, [visit(SYSTEM_LOG)], { signIn: true });

// The text search.
parity("system log: search", searchPath, searchPath, [visit(searchPath)], { signIn: true });

// Two categories in the address (the panel shows «· 2» on both sides).
parity(
  "system log: categories access and export",
  `${SYSTEM_LOG}?category=${CATEGORY_ONE}&category=${CATEGORY_TWO}`,
  `${SYSTEM_LOG}?category=${CATEGORY_ONE}&category=${CATEGORY_TWO}`,
  [visit(`${SYSTEM_LOG}?category=${CATEGORY_ONE}&category=${CATEGORY_TWO}`)],
  { signIn: true },
);

// The date range, from and to.
parity(
  "system log: date range 2026",
  `${SYSTEM_LOG}?from=2026-01-01&to=2026-12-31`,
  `${SYSTEM_LOG}?from=2026-01-01&to=2026-12-31`,
  [visit(`${SYSTEM_LOG}?from=2026-01-01&to=2026-12-31`)],
  { signIn: true },
);

// The oldest-first order.
parity("system log: oldest first", `${SYSTEM_LOG}?oldest=1`, `${SYSTEM_LOG}?oldest=1`, [visit(`${SYSTEM_LOG}?oldest=1`)], {
  signIn: true,
});

// Junk in the address: an unknown category and an IP text that is not an address prefix. Both sides drop the category and
// the IP (the Excel link follows the cleaned address), so the rows are compared as the unfiltered list.
parity(
  "system log: junk address",
  `${SYSTEM_LOG}?category=zzz&ip=x`,
  `${SYSTEM_LOG}?category=zzz&ip=x`,
  [visit(`${SYSTEM_LOG}?category=zzz&ip=x`)],
  { signIn: true },
);

// The «Ангилал» panel opened on the default view.
parity("system log: category panel open", SYSTEM_LOG, SYSTEM_LOG, [visit(SYSTEM_LOG), openCategoryPanel], { signIn: true });

// The «Цааш харуулах» pill loads the next batch. Skipped when the log has 60 rows or fewer.
parity("system log: pill loads the next batch", SYSTEM_LOG, SYSTEM_LOG, [visit(SYSTEM_LOG), loadNextBatch], { signIn: true });

// The Excel link's path, per side (not compared with the other side).
parity("system log: Excel link path", SYSTEM_LOG, SYSTEM_LOG, [visit(SYSTEM_LOG), excelPathPerSide], { signIn: true });
