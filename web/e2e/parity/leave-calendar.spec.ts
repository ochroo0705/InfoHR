import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Team calendar (step 4d3): /leave/calendar/. Django leave/calendar.html against LeaveCalendarPage and CalendarGrid.
// Same path on both sides; run as `hr`. Read-only. A fixed month keeps the grid the same between runs.
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4d3 (leave balances, calendar, holidays, settings)».

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

const MONTH = "/leave/calendar/?month=2026-11";
const OTHER = "/leave/calendar/?month=2026-02";
const EDGE = "/leave/calendar/?month=1900-01";
const JUNK = "/leave/calendar/?month=garbage";

parity("leave calendar: a month", MONTH, MONTH, [visit(MONTH)], { signIn: true });
parity("leave calendar: another month", OTHER, OTHER, [visit(OTHER)], { signIn: true });
parity("leave calendar: first month allowed", EDGE, EDGE, [visit(EDGE)], { signIn: true });
parity("leave calendar: junk month shows this month", JUNK, JUNK, [visit(JUNK)], { signIn: true });
