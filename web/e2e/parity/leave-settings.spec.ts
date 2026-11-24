import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Leave settings (step 4d3): /leave/settings/ and the leave-type pop-up. Django leave/settings.html, _type_form.html
// against LeaveSettingsPage and TypeModal. Same path on both sides; run as `admin`. Read-only: the pop-ups are opened,
// nothing is saved or deleted (the demo DB is shared).
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4d3 (leave balances, calendar, holidays, settings)».

test.setTimeout(60_000);

const MODAL = ".fixed.inset-0.z-50";

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
}

const visit: Step = async (page) => {
  await openPath(page, SETTINGS);
  await settle(page);
};

// Step: the «Төрөл нэмэх» button opens the add pop-up.
const openAdd: Step = async (page) => {
  await page.getByRole("button", { name: "Төрөл нэмэх" }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

// Step: the first type row opens the edit pop-up.
const openEdit: Step = async (page) => {
  await page.locator("tbody tr").first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const SETTINGS = "/leave/settings/";

parity("leave settings: page", SETTINGS, SETTINGS, [visit], { signIn: true });
parity("leave settings: add type pop-up", SETTINGS, SETTINGS, [visit, openAdd], { signIn: true });
parity("leave settings: edit type pop-up", SETTINGS, SETTINGS, [visit, openEdit], { signIn: true });
