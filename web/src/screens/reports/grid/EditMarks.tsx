import { useState } from "react";
import type { ReportCellOut } from "../../../api/reports";
import { ToolIcon } from "../ToolIcon";

// The editable-column marks of a report table (app/static/js/grid_nav.js «Editable-column marks», UI_RULES §4b). A column
// with an editable cell gets the teal tint, a column with a correction cell (it needs a reason) the amber one; the legend
// sits above the table; the pencil in the «Тохируулах» group switches the marks, and the choice is kept under the same
// localStorage key as grid_nav.js. Every storage access is in try/catch: a blocked storage still draws the page (marks on).

export const EDIT_KEY = "hr.editMarks";
export const TOGGLE_TEXT = "Засварлах боломжтой баганыг өнгөөр харуулах";
export const TITLE_EDIT = "Шууд засна: нүдээ сонгоод F2, давхар товших эсвэл бичих";
export const TITLE_CORRECT = "Засвар: шалтгаантай";

// The choice on the page. Default on; a stored "0" is off (grid_nav.js marksOn).
export function readMarksOn(): boolean {
  try {
    return window.localStorage.getItem(EDIT_KEY) !== "0";
  } catch {
    return true;
  }
}

// Stores the choice as "1" or "0" (grid_nav.js setMarksOn). Without storage the choice lasts this page only.
export function writeMarksOn(on: boolean): void {
  try {
    window.localStorage.setItem(EDIT_KEY, on ? "1" : "0");
  } catch {
    // no storage: the state of the page still holds the choice
  }
}

// The marks switch of a page: its state and the toggle that flips it and remembers it.
export function useEditMarks(): { on: boolean; toggle: () => void } {
  const [on, setOn] = useState<boolean>(readMarksOn);
  return {
    on,
    toggle: () => {
      const next = !on;
      writeMarksOn(next);
      setOn(next);
    },
  };
}

// The mark of one column: "correct" when any of its cells is a correction, else "edit" when any cell is editable, else "".
export type ColumnMark = "" | "edit" | "correct";

export interface MarkRow {
  heading: boolean;
  cells: ReadonlyArray<ReportCellOut | null>; // one per grid column (null for the selection cell)
}

// The mark of every column, from the loaded body rows (a group heading is not a body row). Same rule as grid_nav.js
// columnKinds: the widest row sets the width, and the correction wins over the plain edit in a column.
export function columnMarks(rows: ReadonlyArray<MarkRow>): ColumnMark[] {
  const width = rows.reduce((max, row) => Math.max(max, row.cells.length), 0);
  const marks: ColumnMark[] = new Array<ColumnMark>(width).fill("");
  for (const row of rows) {
    if (row.heading) continue;
    row.cells.forEach((cell, c) => {
      if (cell?.edit?.route === "correct") marks[c] = "correct";
      else if (cell?.edit && marks[c] === "") marks[c] = "edit";
    });
  }
  return marks;
}

// The class a cell or header takes for its mark (the look is in styles/motion.css, copied from input.css).
export function markClass(mark: ColumnMark | null | undefined): string {
  if (mark === "edit") return "col-edit";
  if (mark === "correct") return "col-correct";
  return "";
}

// The pencil toggle of the «Тохируулах» group. It shows only when the table has an editable column (`kinds` is the page's
// edit_marks); its pressed state follows `on`.
export function EditMarks({ kinds, on, onToggle }: { kinds: string[]; on: boolean; onToggle: () => void }) {
  if (kinds.length === 0) return null;
  return (
    <button
      type="button"
      data-edit-marks-toggle
      aria-pressed={on}
      title={TOGGLE_TEXT}
      aria-label={TOGGLE_TEXT}
      onClick={onToggle}
      className={on ? "text-violet-600 bg-violet-600/15" : undefined}
    >
      <ToolIcon kind="pencil" />
    </button>
  );
}

// The legend above the table: the editable swatch whenever the table has an editable column, the correction swatch only
// when it has a correction column, and the keys line always (grid_nav.js makeLegend). Draws nothing without an editable kind.
export function EditLegend({ kinds }: { kinds: string[] }) {
  if (kinds.length === 0) return null;
  return (
    <div
      data-edit-legend=""
      className="flex flex-wrap items-center gap-x-4 gap-y-1 pb-1 text-xs text-slate-600"
    >
      <span className="inline-flex items-center">
        <span className="edit-swatch" aria-hidden="true" />
        Шууд засна (F2, давхар товших, бичих)
      </span>
      {kinds.includes("correct") ? (
        <span className="inline-flex items-center">
          <span className="correct-swatch" aria-hidden="true" />
          Засвар — шалтгаантай
        </span>
      ) : null}
      <span>Ctrl+V буулгах · Ctrl+D доош хуулах</span>
    </div>
  );
}
