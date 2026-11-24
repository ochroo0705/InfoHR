import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// «Миний даалгавар» page (step 4c): /checklists/mine/. Django checklists/mine.html + _my_tasks.html against MinePage.
// Same path on both sides; run as `hr` (the demo user has open tasks). Read-only: nothing is ticked (the demo DB is
// shared; the tick is covered by the API and Vitest tests).
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4c (checklists)».

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

const MINE = "/checklists/mine/";

parity("checklists: my tasks", MINE, MINE, [visit(MINE)], { signIn: true });
