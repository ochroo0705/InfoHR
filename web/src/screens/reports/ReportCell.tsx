import type { CSSProperties, MouseEvent, ReactNode, Ref } from "react";
import type { ReportCellOut } from "../../api/reports";
import { AppLink } from "../../lib/AppLink";
import type { CellMark } from "./grid/useBulkEdit";
import { markClass, type ColumnMark } from "./grid/EditMarks";
import { inEditorSurface } from "./grid/gridMath";

// One cell of a report table: the <td> of _rows.html / the footer of _table.html, with the text of _cell.html. Every
// class and offset comes from the API (css, style); React only turns the text into what the template draws. The text is
// drawn as text, never as HTML.

// Port of the `mnt` filter (employees/templatetags/hr.py) over `group()` (employees/money.py): "2500000.00" -> "2,500,000₮",
// "800000" -> "800,000₮", "1234.5" -> "1,234.50₮". A whole amount has no ".00" tail. "" is "—" (what mnt gives for an
// empty value). A value that is not a plain number is shown as sent.
export function moneyText(raw: string): string {
  if (raw === "") return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!match) return raw;
  const [, sign, digits, decimals = ""] = match;
  const cents = decimals.length > 2 ? Number(raw).toFixed(2).split(".")[1] : (decimals + "00").slice(0, 2);
  const whole = digits.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const tail = cents === "00" ? "" : "." + cents;
  return `${sign}${whole}${tail}₮`;
}

// The inline style the API sends as text: only the pinned offset of a column ("left: 12rem", "left: 2.5rem"). Anything
// else (another property, a second declaration) gives no style, so the API's text can never set more than the offset.
const PINNED_LEFT = /^left: -?\d+(\.\d+)?rem$/;

export function inlineStyle(text: string): CSSProperties | undefined {
  const match = PINNED_LEFT.exec(text.trim());
  return match ? { left: text.trim().slice("left: ".length) } : undefined;
}

// What a press inside a cell leaves to its own control: a field, a button, or the open editor (no focus change here).
const FIELD_TARGETS = "input, select, textarea, button, summary, a, [contenteditable='true'], [data-cell-form]";

// The text a cell shows. A money cell is formatted from its raw value (a blank value prints nothing); every other cell
// shows the text sent. The keyboard grid copies this same text.
export function cellText(cell: ReportCellOut): string {
  return cell.money ? (cell.value === null ? "" : moneyText(cell.value)) : cell.text;
}

// The keyboard cursor of a body cell (useGridCursor): where the cell sits, whether the cursor or a Shift range is on it,
// and what a click or a double click does.
export interface GridCell {
  r: number;
  c: number;
  active: boolean;
  inRange: boolean;
  onClick: (shift: boolean) => void;
  onDoubleClick?: () => void;
  // The bulk edit's mark of this cell (amber will change, red refused with its reason as the title).
  mark?: CellMark | null;
}

// The class and handlers a cursor cell takes (none of them when the table has no cursor). A click focuses the table, so
// the keys that follow go to the grid (grid_nav.js); a Shift click does not select text.
export function gridTdProps(grid: GridCell | undefined, css: string) {
  const className = [
    css,
    grid?.active && "is-cell-active",
    grid?.inRange && "is-cell-range",
    grid?.mark?.kind === "pending" && "is-cell-pending",
    grid?.mark?.kind === "rejected" && "is-cell-rejected",
  ]
    .filter(Boolean)
    .join(" ");
  return {
    className: className || undefined,
    title: grid?.mark?.kind === "rejected" ? grid.mark.title || undefined : undefined,
    "aria-current": grid?.active ? ("true" as const) : undefined,
    onMouseDown: grid
      ? (event: MouseEvent<HTMLTableCellElement>) => {
          if (inEditorSurface(event.target)) return; // a press in the open editor or its popup belongs to the editor
          if (event.shiftKey) event.preventDefault();
          // A press on a plain part of the cell. Focusing the table on the press would first put the cursor on the first cell
          // (useGridCursor onFocus) and scroll it into view, so a cell scrolled to the right (375 px) moved out from under the
          // pointer and the click missed it. So the press moves the cursor to this cell and focuses the table without scrolling.
          if (event.button !== 0 || (event.target instanceof Element && event.target.closest(FIELD_TARGETS))) return;
          event.preventDefault();
          grid.onClick(event.shiftKey);
          (event.currentTarget.closest("table") as HTMLElement | null)?.focus({ preventScroll: true });
        }
      : undefined,
    onClick: grid
      ? (event: MouseEvent<HTMLTableCellElement>) => {
          // A click inside an open editor or its popup belongs to the editor: it keeps the focus and the cursor stays.
          if (inEditorSurface(event.target)) return;
          grid.onClick(event.shiftKey);
          (event.currentTarget.closest("table") as HTMLElement | null)?.focus({ preventScroll: true });
        }
      : undefined,
    onDoubleClick: grid?.onDoubleClick
      ? (event: MouseEvent<HTMLTableCellElement>) => {
          // A double click inside the open editor or its popup belongs to the editor, not to the cell.
          if (inEditorSurface(event.target)) return;
          grid.onDoubleClick?.();
        }
      : undefined,
  };
}

export function ReportCell({
  cell,
  editor,
  panel = false,
  cellRef,
  grid,
  busy = false,
  mark,
}: {
  cell: ReportCellOut;
  // The editable-column mark of this cell's column (EditMarks.columnMarks), when the marks are on.
  mark?: ColumnMark;
  // The editor of this cell (CellEditor), drawn in place of the text while it is open.
  editor?: ReactNode;
  // A floating panel editor (UI_RULES §4 «Floating cell editor»): the old text stays faded underneath (data-cell-ghost).
  // The caller passes isPanelEditor(editor) from CellEditor, the one place that decides it.
  panel?: boolean;
  // The cell itself, so the editor can measure it (CellEditor anchor).
  cellRef?: Ref<HTMLTableCellElement>;
  // The cell's place in the keyboard grid, when the table has one.
  grid?: GridCell;
  // The cell is loading or saving its editor: it is drawn faded (grid_nav.js opacity-50 while busy).
  busy?: boolean;
}) {
  const text = cellText(cell);
  const busyCss = busy ? [cell.css, "opacity-50"].filter(Boolean).join(" ") : cell.css;
  const css = [busyCss, markClass(mark)].filter(Boolean).join(" ");
  if (editor != null) {
    // The text box of the cell is replaced by the editor; a panel keeps the old text faded under it (grid_nav.js mountEditor).
    return (
      <td
        ref={cellRef}
        data-r={grid?.r}
        data-c={grid?.c}
        {...gridTdProps(grid, [css, panel && "is-popped"].filter(Boolean).join(" "))}
        style={inlineStyle(cell.style)}
      >
        {panel ? <span data-cell-ghost aria-hidden="true">{text}</span> : null}
        {editor}
      </td>
    );
  }
  return (
    <td
      ref={cellRef}
      data-r={grid?.r}
      data-c={grid?.c}
      {...gridTdProps(grid, css)}
      style={inlineStyle(cell.style)}
    >
      {cell.href ? (
        <AppLink to={cell.href} className="text-violet-700 hover:underline">
          {text}
        </AppLink>
      ) : (
        text
      )}
    </td>
  );
}
