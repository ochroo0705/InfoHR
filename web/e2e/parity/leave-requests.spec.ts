import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Leave requests (step 4d2): /leave/requests/ with its two tabs, the status filter and the detail pop-up. Django
// leave/requests.html, _request_rows.html, _request_detail.html against LeaveRequestsPage, LeaveRequestsTable and
// RequestDetailModal. Same path on both sides; run as `hr` (sees every request). Read-only: pop-ups are opened and
// closed, nothing is approved or rejected (the demo DB is shared; writes are covered by the API and Vitest tests). The
// request form opens from the My page for a staff user, so the browser check covers it, not this spec.
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4d2 (leave requests)».

test.setTimeout(60_000);

const MODAL = ".fixed.inset-0.z-50";

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1, nav[aria-label]").first()).toBeVisible();
}

function visit(path: string): Step {
  return async (page) => {
    await openPath(page, path);
    await settle(page);
  };
}

// Step: the first row opens its detail pop-up (skips when the list is empty).
const openFirstRow: Step = async (page) => {
  const row = page.locator("tbody tr").first();
  if ((await row.locator("td").count()) < 3) {
    test.skip(true, "No request row in the demo data for this tab.");
    return;
  }
  await row.click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const MINE = "/leave/requests/";
const ALL = "/leave/requests/?tab=all";
const WAITING = "/leave/requests/?tab=all&status=waiting";
const APPROVED = "/leave/requests/?tab=all&status=approved";
const REJECTED = "/leave/requests/?tab=all&status=rejected";
const WITHDRAWN = "/leave/requests/?tab=all&status=withdrawn";

parity("leave requests: my queue", MINE, MINE, [visit(MINE)], { signIn: true });
parity("leave requests: all", ALL, ALL, [visit(ALL)], { signIn: true });
parity("leave requests: waiting", WAITING, WAITING, [visit(WAITING)], { signIn: true });
parity("leave requests: approved", APPROVED, APPROVED, [visit(APPROVED)], { signIn: true });
parity("leave requests: rejected", REJECTED, REJECTED, [visit(REJECTED)], { signIn: true });
parity("leave requests: withdrawn", WITHDRAWN, WITHDRAWN, [visit(WITHDRAWN)], { signIn: true });
parity("leave requests: waiting detail pop-up", WAITING, WAITING, [visit(WAITING), openFirstRow], { signIn: true });
parity("leave requests: decided detail pop-up", APPROVED, APPROVED, [visit(APPROVED), openFirstRow], { signIn: true });
