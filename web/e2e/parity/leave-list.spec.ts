import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Leave list (step 4d1): /leave/ with its filters and the add and cancel pop-ups. Django leave/list.html, _rows.html,
// _form.html, _cancel.html against LeavePage, LeaveTable, LeaveFormModal and LeaveCancelModal. Same path on both sides;
// run as `hr`. Read-only: pop-ups are opened and closed, nothing is saved (the demo DB is shared; writes are covered by
// the API and Vitest tests).
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4d1 (leave list)».

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

// Step: the «Чөлөө бүртгэх» button opens the add pop-up.
const openAdd: Step = async (page) => {
  await page.getByRole("button", { name: "Чөлөө бүртгэх" }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

// Step: the cancel button of the first row opens the cancel pop-up (skips when no row has one).
const openCancel: Step = async (page) => {
  const button = page.locator("tbody button", { hasText: /Цуцлах|Буруу гэж тэмдэглэх/ }).first();
  if ((await button.count()) === 0) {
    test.skip(true, "No leave row can be cancelled in the demo data.");
    return;
  }
  await button.click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const LIST = "/leave/";
const ALL = "/leave/?status=all";
const CANCELLED = "/leave/?status=cancelled";
const DATES = "/leave/?from=2020-01-01&to=2030-12-31";
const NONE = "/leave/?q=zzzzzz";

parity("leave: list", LIST, LIST, [visit(LIST)], { signIn: true });
parity("leave: every state", ALL, ALL, [visit(ALL)], { signIn: true });
parity("leave: cancelled", CANCELLED, CANCELLED, [visit(CANCELLED)], { signIn: true });
parity("leave: date range", DATES, DATES, [visit(DATES)], { signIn: true });
parity("leave: search finds nothing", NONE, NONE, [visit(NONE)], { signIn: true });
parity("leave: add pop-up", LIST, LIST, [visit(LIST), openAdd], { signIn: true });
parity("leave: cancel pop-up", LIST, LIST, [visit(LIST), openCancel], { signIn: true });
