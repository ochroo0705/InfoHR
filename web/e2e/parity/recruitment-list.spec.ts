import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Recruitment vacancy list (step 4e): /recruitment/ with its status filter, the search and the «Ажлын байр нээх» pop-up.
// Django recruitment/vacancy_list.html and _vacancy_rows.html, _vacancy_status.html against VacanciesPage, its vacancy
// table and VacancyModal (the add pop-up). Same path on both sides; run as `hr` (sees the add button). Read-only: the
// pop-up is opened and closed, nothing is saved (the demo DB is shared; writes are covered by the API and Vitest tests).
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4e (recruitment)».

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

// Step: the «Ажлын байр нээх» button opens the add pop-up.
const openAdd: Step = async (page) => {
  await page.getByRole("button", { name: "Ажлын байр нээх" }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const OPEN = "/recruitment/";
const CLOSED = "/recruitment/?status=closed";
const FILLED = "/recruitment/?status=filled";
const ALL = "/recruitment/?status=all";
// The search only finds the closed vacancy «Жолооч» when the status filter lets it through, so the status is "all" too.
const SEARCH = "/recruitment/?status=all&q=" + encodeURIComponent("Жолооч");

parity("recruitment list: open", OPEN, OPEN, [visit(OPEN)], { signIn: true });
parity("recruitment list: closed", CLOSED, CLOSED, [visit(CLOSED)], { signIn: true });
parity("recruitment list: filled", FILLED, FILLED, [visit(FILLED)], { signIn: true });
parity("recruitment list: every status", ALL, ALL, [visit(ALL)], { signIn: true });
parity("recruitment list: search", SEARCH, SEARCH, [visit(SEARCH)], { signIn: true });
parity("recruitment list: add pop-up", OPEN, OPEN, [visit(OPEN), openAdd], { signIn: true });
