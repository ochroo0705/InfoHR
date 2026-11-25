import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Recruitment vacancy page (step 4e): /recruitment/vacancies/<id>/ with its stage filter, the edit pop-up and the add
// candidate pop-up. Django recruitment/vacancy_detail.html, _stage_bar.html, _candidate_rows.html, _stage_chip.html,
// _slot_line.html, against VacancyPage, StageBar, its candidate table, StageChip, SlotLine, VacancyModal and
// CandidateModal. Same paths on both sides; run as `hr`. Read-only: pop-ups are opened and closed, nothing is saved (the
// demo DB is shared; writes are covered by the API and Vitest tests).
//
// Vacancy 1 is open, vacancy 3 is closed (amber line, no add button). Known differences are in EXPECTED_DIFFS.md,
// section «Step 4e (recruitment)».

test.setTimeout(60_000);

const MODAL = ".fixed.inset-0.z-50";

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

// Step: the «Засах» button opens the edit pop-up (no save).
const openEdit: Step = async (page) => {
  await page.getByRole("button", { name: "Засах", exact: true }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

// Step: the «Ажил хүсэгч нэмэх» button opens the add candidate pop-up (no save).
const openAddCandidate: Step = async (page) => {
  await page.getByRole("button", { name: "Ажил хүсэгч нэмэх" }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const OPEN = "/recruitment/vacancies/1/";
const ALL_STAGES = "/recruitment/vacancies/1/?stage=all";
const OFFER = "/recruitment/vacancies/1/?stage=offer";
const CLOSED = "/recruitment/vacancies/3/";

parity("recruitment vacancy: open, default stage", OPEN, OPEN, [visit(OPEN)], { signIn: true });
parity("recruitment vacancy: every stage", ALL_STAGES, ALL_STAGES, [visit(ALL_STAGES)], { signIn: true });
parity("recruitment vacancy: offer stage", OFFER, OFFER, [visit(OFFER)], { signIn: true });
parity("recruitment vacancy: edit pop-up", OPEN, OPEN, [visit(OPEN), openEdit], { signIn: true });
parity("recruitment vacancy: add candidate pop-up", OPEN, OPEN, [visit(OPEN), openAddCandidate], { signIn: true });
parity("recruitment vacancy: closed (amber line, no add button)", CLOSED, CLOSED, [visit(CLOSED)], { signIn: true });
