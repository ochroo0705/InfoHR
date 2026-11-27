import { expect, test, type APIResponse, type Browser, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, login, openPath, parity, type Step } from "./harness";

// Reports, step 5d: the print page, the row-selection bar and the picked people's files (report print, Excel, selection).
// Read only: the spec opens pages, ticks rows and posts the selected-file requests. The POSTs write files and audit lines
// and nothing else. Run as `hr` (signIn: true). Django and React share the same path for the print pages; the file routes
// differ (see below).
//
// Print pages, one parity() case each (1280 and 375 px, light and dark, from the harness defaults):
//   /reports/staff-list/print/                      Django reports/print.html; React ReportPrintPage (PORTED: /^\/reports\/[^/]+\/print\/$/).
//   /reports/absences/print/?group=department       the grouped print (the demo may have no absences; both sides then print the empty table).
//   /reports/staff-list/print/?layout=chart&lby=department   the chart address. The print page may draw the chart as a
//                                                    canvas; it is masked (CHART_MASK, the same selector as reports-layouts.spec.ts).
// Masks: `.top > div:last-child` (the «today · printed_by» line of the print header, both sides) on all three print cases.
// The print page's rows load in one React query, so `visitPrint` waits for the title and the header line after the network
// is idle (openPath does the networkidle wait).
//
// Selection bar, one parity() case: /reports/staff-list/. Step 1 is the page; step 2 clicks the toolbar «Сонгох» toggle
// ([data-select-toggle], on both sides) and ticks the first two row checkboxes (`tbody input[data-select-row]`, labelled
// «Мөр сонгох» on both sides), then waits for `#selection-bar [data-count]` to read 2. The comparison is the full page
// (no clip): the selection bar and the table's checkbox column are not under one selector, so no single clip covers
// both. Nothing is masked; the staff list has no volatile text in the body.
//
// Files (one test, not pixels; no viewport): each side gets a fresh context, signs in as `hr` and opens /reports/staff-list/.
// Both sides turn «Сонгох» on and tick the first two people; their ids (in row order) must match. Then each side requests:
//   1. the whole-report Excel: GET /reports/staff-list/excel/ (Django) and GET /api/v1/reports/staff-list/excel (React),
//   2. the picked people's Excel: POST /reports/staff-list/selected/excel/ (Django, form-encoded query= and ids=) and
//      POST /api/v1/reports/staff-list/selected/excel (React, JSON {query, ids, all:false}), CSRF token in X-CSRFToken,
//   3. the picked people's CSV: the same as 2 with /selected/csv.
// Compared: status (200 on Django), Content-Disposition (the date part is the same day on both sides), Content-Type.
// CSV: the body bytes exactly, UTF-8 BOM included (the body is read as bytes, not decoded, so a BOM difference shows).
// Excel: the zip signature ("PK") and the size class (order of magnitude) only. web/package.json has no xlsx or exceljs
// (its devDependencies are @playwright/test, pixelmatch and pngjs), so sheet names, the header row and the row count are
// not read. The Excel files also carry creation timestamps, so their bytes are never compared.
// Cookies: the CSRF token is read from the context's `csrftoken` cookie. Cookies are shared by host (127.0.0.1), not by
// port, so the same cookie serves both the Django and the React origin.
//
// Each export request writes one audit line on the server (export_report or export_selected), so one run adds a few lines.
//
// Known differences: none recorded yet. Record what the first run shows in EXPECTED_DIFFS.md, section «Step 5d (report
// print, Excel, selection)».

test.setTimeout(120_000);

const STAFF = "/reports/staff-list/";
const STAFF_PRINT = "/reports/staff-list/print/";
const ABSENCES_PRINT = "/reports/absences/print/?group=department";
const CHART_PRINT = "/reports/staff-list/print/?layout=chart&lby=department";
const KEY = "staff-list";

// Today's date and the printing user, the second item of the print header. It changes between runs, so it is painted over.
const PRINT_DATE_MASK = [".top > div:last-child"];
// The chart canvas on the chart print (the same selector as reports-layouts.spec.ts): Django's div has data-chart and
// role="img"; React's has role="img" and an aria-label.
const CHART_MASK = ['[data-chart], [role="img"][aria-label]'];

// Opens a print page on this side and waits for its title and header line.
function visitPrint(path: string): Step {
  return async (page: Page) => {
    await openPath(page, path);
    await page.locator("h1").first().waitFor();
    await page.locator(".top").first().waitFor();
  };
}

// Opens the staff list on this side and waits for its first table row.
const visitStaff: Step = async (page: Page) => {
  await openPath(page, STAFF);
  await page.locator("h1").first().waitFor();
  await page.locator("tbody tr").first().waitFor();
};

// Turns «Сонгох» on and ticks the first two person rows. The bar then shows 2 on both sides.
const pickTwo: Step = async (page: Page) => {
  await page.locator("[data-select-toggle]").click();
  const boxes = page.locator("tbody input[data-select-row]");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await expect(page.locator("#selection-bar [data-count]")).toHaveText("2");
};

// Print pages.
parity("report print: staff list", STAFF_PRINT, STAFF_PRINT, [visitPrint(STAFF_PRINT)], {
  signIn: true,
  mask: PRINT_DATE_MASK,
});

parity("report print: absences by department", ABSENCES_PRINT, ABSENCES_PRINT, [visitPrint(ABSENCES_PRINT)], {
  signIn: true,
  mask: PRINT_DATE_MASK,
});

parity("report print: staff list as a chart by department", CHART_PRINT, CHART_PRINT, [visitPrint(CHART_PRINT)], {
  signIn: true,
  mask: [...PRINT_DATE_MASK, ...CHART_MASK],
});

// Selection bar with two people picked.
// One step does the whole flow and only the bar is compared: the staff list page itself still differs from Django by the
// edit legend, the pencil and the editable-cell tints (step 5f), so a full-page step 1 would fail for that reason.
parity("report selection: the bar with two people picked (staff list)", STAFF, STAFF, [async (page: Page) => {
  await visitStaff(page);
  await pickTwo(page);
  // The checklist action reaches React in step 5e: Django's button is removed so the bar compares like with like.
  await page.evaluate(() => document.querySelectorAll('#selection-bar [data-action="checklist"]').forEach((el) => el.remove()));
}], {
  signIn: true,
  clip: "#selection-bar",
});

// ---- Files -----------------------------------------------------------------------------------------------------------

type FileResult = { status: number; disposition: string; contentType: string; body: Buffer };

type SideFiles = {
  ids: string[];
  excel: FileResult;
  selectedExcel: FileResult;
  selectedCsv: FileResult;
};

// Opens the staff list signed in on one side and runs `run` there. Same sign-in as the harness's bothSides.
async function onSide<T>(browser: Browser, base: string, run: (page: Page) => Promise<T>): Promise<T> {
  const context = await browser.newContext({ reducedMotion: "no-preference" });
  try {
    const page = await context.newPage();
    await page.goto(base + STAFF);
    await login(page, base);
    await openPath(page, STAFF);
    return await run(page);
  } finally {
    await context.close();
  }
}

// The request addresses of one side. Django: /reports/<key>/…/ (trailing slash). React: /api/v1/reports/<key>/… (no slash).
function fileUrls(base: string, web: boolean) {
  const root = web ? `${base}/api/v1/reports/${KEY}` : `${base}/reports/${KEY}`;
  const tail = web ? "" : "/";
  return {
    excel: `${root}/excel${tail}`,
    selectedExcel: `${root}/selected/excel${tail}`,
    selectedCsv: `${root}/selected/csv${tail}`,
  };
}

async function readResponse(response: APIResponse): Promise<FileResult> {
  const headers = response.headers();
  return {
    status: response.status(),
    disposition: headers["content-disposition"] ?? "",
    contentType: headers["content-type"] ?? "",
    body: await response.body(),
  };
}

// The csrftoken cookie of this side's context. Django sets it on the first page; a missing cookie stops the run.
async function csrfToken(page: Page, base: string): Promise<string> {
  const cookies = await page.context().cookies(base);
  const token = cookies.find((cookie) => cookie.name === "csrftoken")?.value;
  if (!token) throw new Error(`No csrftoken cookie for ${base}: the signed-in session should have one.`);
  return token;
}

// Ticks the first two person rows (after «Сонгох») and returns their ids in row order. Both sides use the same rows.
async function pickTwoIds(page: Page): Promise<string[]> {
  await page.locator("[data-select-toggle]").click();
  const boxes = page.locator("tbody input[data-select-row]");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  return page
    .locator("tbody tr:has(input[data-select-row]:checked)")
    .evaluateAll((rows) => rows.slice(0, 2).map((row) => row.getAttribute("data-person") ?? ""));
}

// POSTs the picked ids to a selected-file route. Django takes form fields (query, ids); React takes JSON (query, ids, all).
async function postSelected(
  page: Page,
  url: string,
  web: boolean,
  ids: string[],
  token: string,
): Promise<FileResult> {
  const response = web
    ? await page.request.post(url, {
        headers: { "X-CSRFToken": token },
        data: { query: "", ids, all: false },
      })
    : await page.request.post(url, {
        headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
        data: new URLSearchParams([["query", ""], ...ids.map((id): [string, string] => ["ids", id])]).toString(),
      });
  return readResponse(response);
}

async function readSideFiles(page: Page, base: string, web: boolean): Promise<SideFiles> {
  const ids = await pickTwoIds(page);
  const token = await csrfToken(page, base);
  const urls = fileUrls(base, web);
  const excel = await readResponse(await page.request.get(urls.excel));
  const selectedExcel = await postSelected(page, urls.selectedExcel, web, ids, token);
  const selectedCsv = await postSelected(page, urls.selectedCsv, web, ids, token);
  return { ids, excel, selectedExcel, selectedCsv };
}

// Adds the differences of one file to `failures`. `kind` picks the check: exact bytes for CSV, zip signature and size class
// for Excel (see the header comment).
function compareFile(failures: string[], label: string, django: FileResult, web: FileResult, kind: "xlsx" | "csv"): void {
  const note = (what: string) => failures.push(`${label}: ${what}`);
  if (django.status !== 200) note(`django status ${django.status}, expected 200`);
  if (web.status !== django.status) note(`status django ${django.status}, web ${web.status}`);
  if (web.disposition !== django.disposition) {
    note(`Content-Disposition django "${django.disposition}", web "${web.disposition}"`);
  }
  if (web.contentType !== django.contentType) note(`Content-Type django "${django.contentType}", web "${web.contentType}"`);

  if (kind === "csv") {
    if (!django.body.equals(web.body)) {
      note(`CSV bytes differ (django ${django.body.length} bytes, web ${web.body.length} bytes)`);
    }
    return;
  }
  // Excel: no xlsx reader in the project, so only the zip signature and the order of magnitude of the size are compared.
  const isZip = (file: FileResult) => file.body.subarray(0, 2).toString("latin1") === "PK";
  if (!isZip(django)) note("django body is not a zip (no PK signature)");
  if (!isZip(web)) note("web body is not a zip (no PK signature)");
  const sizeClass = (file: FileResult) => String(Math.floor(Math.log10(Math.max(file.body.length, 1))));
  if (sizeClass(django) !== sizeClass(web)) {
    note(`size class differs (django ${django.body.length} bytes, web ${web.body.length} bytes)`);
  }
}

test.describe("report files: whole-report Excel, and the picked people's Excel and CSV", () => {
  test("staff list files match on both servers", async ({ browser }) => {
    const django = await onSide(browser, DJANGO_URL, (page) => readSideFiles(page, DJANGO_URL, false));
    const web = await onSide(browser, WEB_URL, (page) => readSideFiles(page, WEB_URL, true));

    const failures: string[] = [];
    if (django.ids.length !== 2) failures.push(`django picked ${django.ids.length} people, expected 2`);
    if (django.ids.join(",") !== web.ids.join(",")) {
      failures.push(`picked ids differ: django "${django.ids.join(",")}", web "${web.ids.join(",")}"`);
    }
    compareFile(failures, "whole-report Excel", django.excel, web.excel, "xlsx");
    compareFile(failures, "selected Excel", django.selectedExcel, web.selectedExcel, "xlsx");
    compareFile(failures, "selected CSV", django.selectedCsv, web.selectedCsv, "csv");

    expect(failures, failures.join("\n")).toEqual([]);
  });
});
