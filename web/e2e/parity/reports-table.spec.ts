import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Reports, step 5a: the catalogue at /reports/ (Django reports/catalogue.html against CataloguePage) and the report table
// at /reports/<key>/ (Django reports/report.html with _table.html, _rows.html, _filters.html and _column_filters.html
// against ReportPage, ReportTable, FilterBar and ColumnChips). Same path on both sides; run as `hr` (holds
// reports.view_reports, view_employees, view_personal and leave.view_leave). Read-only: no step clicks anything that
// writes. Nothing is saved, no view is stored and no column is picked.
//
// Addresses (each one verified in the registry and the report modules):
//   /reports/                                         catalogue (app/reports/catalogue.py, CATALOGUE; h1 in catalogue.html)
//   /reports/staff-list/                              (a) plain list: staff-list, registry.py REPORTS, staff_list.py REPORT (key line 666)
//   /reports/absences/?group=department               (b) grouped: absences.py ABSENCES (key line 179), group_options=("department", "type")
//                                                         at line 187; column key "department" at line 173
//   /reports/staff-list/?cols=...&totals=years_worked:sum&pin=1
//                                                     (c) footer total and pinned column: staff_list.py "years_worked" (line 235,
//                                                         numeric=True, no `needs`, so `hr` sees it). The column is not in the
//                                                         default columns (DEFAULT_COLUMNS), so it is named with `cols=`: a total on a
//                                                         hidden column is not applied (table.py, "A total or colour on an unshown column").
//                                                         totals syntax «col:agg» is totals.py parse_totals (agg: sum, avg, min, max, count).
//                                                         pin is filters.py `pin`, 0 to 3.
//   /reports/staff-list/?state=all&sort=name          (d) a filter and a sort: state=all is filters.py STATES ("all" = Бүгд);
//                                                         sort=name is staff_list.py column key "name" (line 116).
//   /reports/staff-list/?add=nationality              (e) a column-filter chip: column_filters.py COLUMN_FILTERS "nationality"
//                                                         (line 44, gated by the column "nationality", needs PERSONAL, which `hr` holds);
//                                                         the name is listed in staff_list.py column_filters (COLUMN_FILTERS, line 671).
//
// Demo data: the spec does not depend on rows. A report with no rows in the demo DB still compares its empty state on both
// sides, which is also a valid comparison.
//
// Masks: none. The report pages carry no typed «today» text; the age and years-worked columns count to today, but both
// sides read the same day in one run, so they agree. If a run crosses midnight, the age column may differ: re-run.
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 5a (reports)».

test.setTimeout(60_000);

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
}

function visit(path: string): Step {
  return async (page) => {
    await openPath(page, path);
    await settle(page);
  };
}

const CATALOGUE = "/reports/";
const PLAIN_LIST = "/reports/staff-list/";
const GROUPED = "/reports/absences/?group=department";
const TOTALS_AND_PIN = "/reports/staff-list/?cols=name&cols=department&cols=years_worked&totals=years_worked:sum&pin=1";
const FILTERED_AND_SORTED = "/reports/staff-list/?state=all&sort=name";
const COLUMN_FILTER_CHIP = "/reports/staff-list/?add=nationality";

// (catalogue) the «Тайлан» catalogue with its groups and search box.
parity("reports: catalogue", CATALOGUE, CATALOGUE, [visit(CATALOGUE)], { signIn: true });

// (a) a plain list report with its default columns.
parity("reports: table, plain list (staff-list)", PLAIN_LIST, PLAIN_LIST, [visit(PLAIN_LIST)], { signIn: true });

// (b) the same table grouped by a group option (the group heads and their counts).
parity("reports: table, grouped by department (absences)", GROUPED, GROUPED, [visit(GROUPED)], { signIn: true });

// (c) a footer total on a numeric column with the first column pinned.
parity("reports: table, footer total and pinned column", TOTALS_AND_PIN, TOTALS_AND_PIN, [visit(TOTALS_AND_PIN)], {
  signIn: true,
});

// (d) a state filter and a sort applied to the staff list.
parity("reports: table, state filter and sort", FILTERED_AND_SORTED, FILTERED_AND_SORTED, [visit(FILTERED_AND_SORTED)], {
  signIn: true,
});

// (e) a column-filter chip added through the address (add=), with no value set yet.
parity("reports: table, column filter chip", COLUMN_FILTER_CHIP, COLUMN_FILTER_CHIP, [visit(COLUMN_FILTER_CHIP)], {
  signIn: true,
});
