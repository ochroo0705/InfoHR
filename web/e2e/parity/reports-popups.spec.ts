import { expect, test, type Page } from "@playwright/test";
import { parity, type Step } from "./harness";

// Reports, step 5b: the report pop-ups «Багана» (columns), «Шүүлтүүр» (rules), «Хэлбэр» (format) and «Хадгалах» (save a
// new saved view). Django: reports/report.html ribbon buttons (data-tool="columns|rules|format", and the «Хадгалах»
// button with hx-get view_new) load _columns_modal.html, _rules_modal.html, _format_modal.html and _view_modal.html into
// <body>. React: ToolRibbon.tsx opens ColumnsModal, RulesModal, FormatModal and SavedViewModal (mode "new") through the
// shared Modal widget. Same path on both sides: /reports/staff-list/, run as `hr` (signIn: true), at 1280 and 375 px,
// light and dark (harness defaults). One parity() case per pop-up; each test opens one pop-up and compares it.
//
// What is compared: the pop-up panel only (clip). The Django panel is the first child of `.fixed.inset-0.z-50`
// (the overlay), and so is the React Modal's role="dialog" panel, so one selector, PANEL, matches both sides.
// Each step clicks the ribbon button (by data-tool, or by its caption for «Хадгалах», which has no data-tool), waits for
// the panel, waits for the network to go idle and then 400 ms for the enter animation to finish. The rules pop-up
// shows its blank rule row as the page renders it; nothing is typed.
//
// Read-only: no step presses Apply, Хадгалах inside a pop-up, or any other submit control. Pop-ups are opened and never
// closed by the spec, and nothing is saved (the demo DB is shared; writes are covered by the API and Vitest tests).
//
// Known differences: the format pop-up (all variants), the save-view pop-up height (React 4 px taller, all variants) and
// the columns pop-up at 375 px (ratio just over 1%) still differ; see .superpowers/sdd/2026-11-25-frontend-split-step5b-popups-saved-views/parity-run-report.md.
// Expected differences go in EXPECTED_DIFFS.md, section «Step 5b (report pop-ups)».
// Known unavoidable difference to watch for: the Django panels have no enter animation (the legacy modal.js rule), while
// the React Modal plays its enter fade and lift (styles/motion.css, hr-fade and hr-pop). The 400 ms wait lets both sides
// reach rest before the shot; if a run differs only in the panel's position or opacity, it is this timing, so re-run first.

test.setTimeout(60_000);

const STAFF_LIST = "/reports/staff-list/";
// The overlay of both sides is `.fixed.inset-0.z-50`, and the panel is its first child: Django's div (no role) and React's
// Modal panel (role="dialog") are both direct children of that overlay.
const PANEL = ".fixed.inset-0.z-50 > div";
const SETTLE_MS = 400;

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
}

// Step: a ribbon tool button (data-tool) opens its pop-up.
function openTool(tool: "columns" | "rules" | "format"): Step {
  return async (page) => {
    await settle(page);
    await page.locator(`[data-tool="${tool}"]`).first().click();
    await expect(page.locator(PANEL).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(SETTLE_MS);
  };
}

// Step: the «Хадгалах» button of the saved-view group opens the new saved-view pop-up. Matched by caption, because the
// Django button has no data-tool attribute.
const openSave: Step = async (page) => {
  await settle(page);
  await page.getByRole("button", { name: "Хадгалах" }).first().click();
  await expect(page.locator(PANEL).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(SETTLE_MS);
};

parity("reports pop-up: columns (Багана)", STAFF_LIST, STAFF_LIST, [openTool("columns")], {
  signIn: true,
  clip: PANEL,
});

parity("reports pop-up: rules (Шүүлтүүр), blank rule row", STAFF_LIST, STAFF_LIST, [openTool("rules")], {
  signIn: true,
  clip: PANEL,
});

parity("reports pop-up: format (Хэлбэр)", STAFF_LIST, STAFF_LIST, [openTool("format")], {
  signIn: true,
  clip: PANEL,
});

parity("reports pop-up: save new view (Хадгалах)", STAFF_LIST, STAFF_LIST, [openSave], {
  signIn: true,
  clip: PANEL,
});
