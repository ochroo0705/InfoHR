import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Recruitment purge (step 4e): /recruitment/purge/, the list of rejected or withdrawn candidates past the retention
// period. Django recruitment/purge.html against PurgePage. Same path on both sides; run as `hr`. Read-only: the
// «Устгах» button (the purge) is never pressed; the demo DB is shared. The purge itself is covered by the API and
// Vitest tests.
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4e (recruitment)».

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

const PURGE = "/recruitment/purge/";

parity("recruitment purge: page", PURGE, PURGE, [visit(PURGE)], { signIn: true });
