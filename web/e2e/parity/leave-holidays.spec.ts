import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Public holidays (step 4d3): /leave/holidays/. Django leave/holidays.html against LeaveHolidaysPage. Same path on both
// sides; run as `admin` (the right to change leave settings). Read-only: nothing is added, deleted or prefilled (the
// demo DB is shared; writes are covered by the API and Vitest tests).
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

const YEAR = "/leave/holidays/?year=2026";
const EMPTY_YEAR = "/leave/holidays/?year=2040";

parity("leave holidays: a year with holidays", YEAR, YEAR, [visit(YEAR)], { signIn: true });
parity("leave holidays: a year without holidays", EMPTY_YEAR, EMPTY_YEAR, [visit(EMPTY_YEAR)], { signIn: true });
