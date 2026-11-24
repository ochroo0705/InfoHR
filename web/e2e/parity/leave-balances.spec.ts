import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Leave balances (step 4d3): /leave/balances/. Django leave/balances.html, _balance_rows.html against LeaveBalancesPage.
// Same path on both sides; run as `hr`. Read-only.
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

const BALANCES = "/leave/balances/";

parity("leave balances: page", BALANCES, BALANCES, [visit(BALANCES)], { signIn: true });
