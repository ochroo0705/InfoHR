import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Reports, step 5c: the non-table views of a report at /reports/<key>/ (the layout bar's «Харагдац» choices). Django:
// reports/report.html with layouts/cards.html, board.html, calendar.html (month, and _week.html for lweek), timeline.html,
// chart.html and pivot.html. React: LayoutBody.tsx picks CardsLayout, BoardLayout, CalendarLayout, TimelineLayout,
// ChartLayout and PivotLayout. Same path on both sides, run as `hr` (signIn: true), at 1280 and 375 px, light and dark
// (harness defaults). One parity() case per view. Read-only: the spec only opens the address; it clicks nothing.
//
// Addresses (each one verified in the code; the line numbers are the ones read):
//   /reports/staff-list/?layout=cards
//       (a) cards. filters.py LAYOUTS (line 94) and the layout parse (line 323). staff_list.py REPORT.layouts (line 705)
//           lists "cards"; layouts.py offered_layouts (line 163) keeps it. Cards need no column.
//   /reports/staff-list/?layout=board&lby=state
//       (b) board. lby is a category: staff_list.py group_options (line 678) lists "state", a column with no `needs`
//           (COLUMNS line 204). layouts.py clean_params (line 102) keeps lby only for a category or date column.
//   /reports/staff-list/?layout=calendar&lby=birth_date&lmonth=2025-06
//       (c) calendar, month view. birth_date is a date column (staff_list.py line 147, kind="date", needs PERSONAL, which
//           `hr` holds). layout_repeat (line 708) includes birth_date, so birthdays repeat each year and June has entries.
//           lmonth is parsed by filters.py _month (line 328); layouts.py _month (line 265) reads «YYYY-MM».
//           The month does not contain today (2026-11-25), so no today ring is drawn.
//   /reports/staff-list/?layout=calendar&lby=first_hire_date&lweek=2025-06-02
//       (d) calendar, week view. first_hire_date is a date column (staff_list.py line 228, kind="date"). lweek is parsed by
//           filters.py _week (line 249) and layouts.py week_start (line 910). 2025-06-02 is a Monday (2025-06-01 was a
//           Sunday). Three working staff have a hire date on 2025-06-03 (GOV_EMPLOYEES, read through macs-hr run_query), so
//           the week has entries. The week does not contain today.
//   /reports/staff-list/?layout=timeline&lby=first_hire_date&lby2=contract_end&lyear=2025
//       (e) timeline. first_hire_date (line 228) starts the bar; contract_end is a date column (staff_list.py line 270,
//           kind="date"), the default end (layout_date2, line 707). lyear is parsed by filters.py (line 335) and
//           layouts.py _window_year (line 956). Working staff hired in 2025 (April, June and July) fall inside the window.
//           The 2025 window does not contain today, so the today line is not drawn; it is still masked (timeline.html
//           line 40, data-today; TimelineLayout.tsx lines 112 and 154) in case the window is changed.
//   /reports/staff-list/?layout=chart&lby=state
//       (f) chart, bar. state is a category (group_options, line 678). CHARTS (filters.py line 95) lists "bar".
//           The chart canvas is an echarts drawing: Django chart.html line 6 is a div with data-chart and role="img" and an
//           aria-label; React ChartLayout.tsx lines 131-134 is a div with role="img" and the same kind of aria-label (no
//           data-chart). CHART_MASK matches both sides; the chart is masked and its value table below is still compared.
//   /reports/staff-list/?layout=pivot&lby=state&lby2=gender
//       (g) pivot. state (line 678) and gender (staff_list.py line 171, needs PERSONAL, in group_options) are both
//           categories. layouts.py resolve (line 383) gives the pivot its second category from lby2. Count of rows is the
//           default value (lval empty).
//
// Demo data: the hire dates and birthdays are read from the demo DB where a count was checked (see each case). The
// calendar and week cases use a date the demo DB is known to have; if a run shows an empty view on both sides, the
// comparison is still valid, but re-check the demo data.
//
// Masks: the chart canvas (CHART_MASK) on the chart case only. Today: the timeline case masks [data-today]; the calendar
// and week cases do not contain today, so nothing today-dependent is drawn. The calendar's «36 жил» style notes count to
// today, but both sides read the same day in one run, so they agree.
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 5c (report layouts)».

test.setTimeout(60_000);

const STAFF = "/reports/staff-list/";
const CARDS = `${STAFF}?layout=cards`;
const BOARD = `${STAFF}?layout=board&lby=state`;
const CALENDAR_MONTH = `${STAFF}?layout=calendar&lby=birth_date&lmonth=2025-06`;
const CALENDAR_WEEK = `${STAFF}?layout=calendar&lby=first_hire_date&lweek=2025-06-02`;
const TIMELINE = `${STAFF}?layout=timeline&lby=first_hire_date&lby2=contract_end&lyear=2025`;
const CHART = `${STAFF}?layout=chart&lby=state`;
const PIVOT = `${STAFF}?layout=pivot&lby=state&lby2=gender`;

// The chart canvas is a drawing, not text: Django's div (data-chart, role="img") and React's div (role="img") both match
// `[role="img"][aria-label]`, and the data-chart selector covers Django's own markup.
const CHART_MASK = ['[data-chart], [role="img"][aria-label]'];
// Today's marker in the timeline (data-today on both sides). Masked so a window that ever includes today does not
// make the run depend on the date.
const TIMELINE_MASK = ["[data-today]"];

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

// (a) the cards view: one card per employee, titled with the name.
parity("reports layout: cards (staff-list)", CARDS, CARDS, [visit(CARDS)], { signIn: true });

// (b) the board: one lane per state, with the cards of each lane.
parity("reports layout: board by state (staff-list)", BOARD, BOARD, [visit(BOARD)], { signIn: true });

// (c) the calendar month view, birthdays of June 2025 (they repeat each year).
parity("reports layout: calendar, month of birthdays (staff-list)", CALENDAR_MONTH, CALENDAR_MONTH, [visit(CALENDAR_MONTH)], {
  signIn: true,
});

// (d) the calendar week view from Monday 2 June 2025, by first hire date.
parity("reports layout: calendar, week of first hires (staff-list)", CALENDAR_WEEK, CALENDAR_WEEK, [visit(CALENDAR_WEEK)], {
  signIn: true,
});

// (e) the timeline of the 2025 window: a bar per person from the hire date to the contract end.
parity("reports layout: timeline, 2025 window (staff-list)", TIMELINE, TIMELINE, [visit(TIMELINE)], {
  signIn: true,
  mask: TIMELINE_MASK,
});

// (f) the bar chart of the staff by state (the canvas is masked; the value table is compared).
parity("reports layout: chart, bars by state (staff-list)", CHART, CHART, [visit(CHART)], {
  signIn: true,
  mask: CHART_MASK,
});

// (g) the pivot: state down the rows, gender across the columns, a count in each cell.
parity("reports layout: pivot, state by gender (staff-list)", PIVOT, PIVOT, [visit(PIVOT)], { signIn: true });
