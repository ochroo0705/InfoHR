import { expect, test, type Locator, type Page } from "@playwright/test";
import { parity, type Step } from "./harness";

// Reports, step 5f: the cell editors of a report table (the keyboard grid's F2 editor, UI_RULES §4 «Inline cell editing»
// and «Corrections from report cells»). Django: `td[data-edit]` cells open the editor form `form[data-cell-form]` in the cell
// (`_cell_editor.html`); a correction (`td[data-correct]`) opens the floating panel `form.cell-pop` (`_correct_editor.html`).
// React: the same form (`CellEditor.tsx`, `data-cell-form`) in the cell's <td> (ReportCell.tsx), opened by F2 on the cursor
// cell (useGridCursor, useCellEdit). Read only: the spec opens one plain editor and one correction editor on each side,
// compares the first body row of the table after each step (the editor open, then closed again with Esc), and never
// presses Enter, never clicks a save or a bulk control, and never changes a value. Run as `hr` (signIn: true) on
// /reports/staff-list/, at 1280 and 375 px, light and dark (harness defaults).
//
// Plain cell: «Ажлын утас» (work_phone, `edit="work_phone"` in staff_list.py, a default column of the staff list, so it is
// shown without changing the viewer's columns; «Регистрийн дугаар» is not a default column). Correction cell: «Хэлтэс»
// (department, `correct="department"`), which opens the correction editor with its reason box. If the viewer's job record
// is not in force today the correction editor is only a message (still `form[data-cell-form]`), so both states compare.
//
// Compared: the first body row of the table (`table[data-grid] tbody tr`, clip, .first() in the harness). The row is taken
// rather than the editor alone, because the editor's cell is the only element both sides share; a correction panel that
// reaches below the row is cropped at the row's edge on both sides alike. Nothing is masked: the staff list shows the same
// data on both sides and the same day.
//
// Selectors that are guesses (no running page checked them; the first run decides):
// - Column lookup by header text: the last `thead` row that is not the sticky clone (`thead:not([data-sticky-head])`),
//   the `th` whose text contains the label, and the same index in the first body row. If React's header or the checkbox
//   column differs, this is the first thing to change.
// - React has no `data-edit` attribute on its cells (the edit target is in the API, not the DOM), so the spec never
//   selects editable cells by it: it picks the column by its label and relies on the editor opening after F2.
// Known differences: the correction test's focus ring (see the test below and EXPECTED_DIFFS.md, section «Step 5f»).

test.setTimeout(120_000);

const STAFF = "/reports/staff-list/";
const PLAIN_LABEL = "Ажлын утас";
const CORRECT_LABEL = "Хэлтэс";
// The editor form on either side (both use data-cell-form).
const EDITOR = "form[data-cell-form]";
// The first body row of the report table (the clip); the editor's cell is inside it.
const FIRST_ROW = "table[data-grid] tbody tr";
// The settle time after the editor opens or closes: the React editor fades in, the Django one does not.
const SETTLE_MS = 300;

// The body cell under the column whose header text contains `label`, in the first body row (guessed selectors, see above).
async function cellUnder(page: Page, label: string): Promise<Locator> {
  const heads = page.locator("table[data-grid] thead:not([data-sticky-head]) tr").last().locator("th");
  const texts = await heads.allInnerTexts();
  const index = texts.findIndex((text) => text.replace(/\s+/g, " ").includes(label));
  expect(index, `column «${label}» in the header`).toBeGreaterThanOrEqual(0);
  return page.locator(FIRST_ROW).first().locator("td").nth(index);
}

// Clicks the cell (a click moves the grid cursor and focuses the table on both sides), then opens its editor with F2.
function openEditor(label: string): Step {
  return async (page) => {
    await page.locator("h1").first().waitFor();
    await page.locator(FIRST_ROW).first().waitFor();
    await (await cellUnder(page, label)).click();
    await page.keyboard.press("F2");
    await expect(page.locator(EDITOR).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(SETTLE_MS);
  };
}

// Cancels the open editor with Escape (no request, nothing saved) and waits until no editor is left.
// Django's correction panel does not take the keys after it opens: select.js upgrades its box after the focus has moved, so
// the focus is on the page and Escape does nothing (grid_nav.js editorKey needs the focus inside the editor). Then a click
// on the page heading closes it on both sides (an outside click cancels without saving). See EXPECTED_DIFFS.md, «Step 5f».
const closeEditor: Step = async (page) => {
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  if ((await page.locator(EDITOR).count()) > 0) await page.locator("h1").first().click();
  await expect(page.locator(EDITOR)).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(SETTLE_MS);
};

// Plain editor: open, compare (the parity harness compares after each step), then Esc, compare again.
parity("report cell editors: plain cell (register number), open then Esc", STAFF, STAFF, [openEditor(PLAIN_LABEL), closeEditor], {
  signIn: true,
  clip: FIRST_ROW,
});

// Correction editor: the department cell opens the floating correction panel; Esc closes it.
// Accepted difference (EXPECTED_DIFFS.md, «Step 5f»): the only pixels that differ are the focus ring of the React
// department box (the field keeps the focus; Django's loses it while select.js upgrades it). Limit 0.035, not 0.01.
parity("report cell editors: correction (department), open then Esc", STAFF, STAFF, [openEditor(CORRECT_LABEL), closeEditor], {
  signIn: true,
  clip: FIRST_ROW,
  maxDiffPixelRatio: 0.035,
});
