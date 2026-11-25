import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Recruitment candidate page (step 4e): /recruitment/candidates/<id>/ with the reject pop-up. Django
// recruitment/candidate_detail.html, candidate_reject.html, _files.html, _comments.html and the stage history against
// CandidatePage, RejectModal, Files, Comments and the stage line. Same paths on both sides; run as `hr`. Read-only: the
// reject pop-up is opened and closed, nothing is rejected, moved, hired or uploaded (the demo DB is shared; writes are
// covered by the API and Vitest tests).
//
// The demo candidates have no fixed ids in this spec. Each candidate is reached from a vacancy stage list by clicking
// its first row's name link, on each side separately (both sides read the same database). When the stage has no
// candidate, that case skips rather than fails. Known differences are in EXPECTED_DIFFS.md, section «Step 4e
// (recruitment)».

test.setTimeout(60_000);

const MODAL = ".fixed.inset-0.z-50";

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
}

// Step: open the vacancy's stage list and click the first candidate's name link (skips when the stage is empty).
function openFirstCandidate(source: string): Step {
  return async (page) => {
    await openPath(page, source);
    await settle(page);
    const link = page.locator('tbody a[href^="/recruitment/candidates/"]').first();
    if ((await link.count()) === 0) {
      test.skip(true, `No candidate in ${source} in the demo data.`);
      return;
    }
    await link.click();
    await page.waitForURL(/\/recruitment\/candidates\/\d+\/$/);
    await settle(page);
  };
}

// Step: the «Татгалзах» button opens the reject pop-up (no submit).
const openReject: Step = async (page) => {
  await page.getByRole("button", { name: "Татгалзах", exact: true }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

// Open candidates: vacancy 1 (open) at the interview stage.
const OPEN_SOURCE = "/recruitment/vacancies/1/?stage=interview";
// Rejected candidates: the rejected stage of vacancy 1.
const REJECTED_SOURCE = "/recruitment/vacancies/1/?stage=rejected";
// Hired candidates: the hired stage of vacancy 4 (filled).
const HIRED_SOURCE = "/recruitment/vacancies/4/?stage=hired";

parity("recruitment candidate: open", OPEN_SOURCE, OPEN_SOURCE, [openFirstCandidate(OPEN_SOURCE)], { signIn: true });
parity("recruitment candidate: reject pop-up", OPEN_SOURCE, OPEN_SOURCE, [openFirstCandidate(OPEN_SOURCE), openReject], {
  signIn: true,
});
parity("recruitment candidate: rejected", REJECTED_SOURCE, REJECTED_SOURCE, [openFirstCandidate(REJECTED_SOURCE)], {
  signIn: true,
});
parity("recruitment candidate: hired", HIRED_SOURCE, HIRED_SOURCE, [openFirstCandidate(HIRED_SOURCE)], { signIn: true });
