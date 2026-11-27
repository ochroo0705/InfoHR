import { Fragment, memo, useMemo, type MouseEvent, type ReactNode } from "react";
import type { ReportCellOut, ReportGroupOut } from "../../api/reports";
import { isPorted } from "../../lib/ported";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { cellText, gridTdProps, inlineStyle, ReportCell, type GridCell } from "./ReportCell";
import type { CheckColumn } from "./HeaderRow";
import type { Box, Pos } from "./grid/gridMath";
import type { CellMark } from "./grid/useBulkEdit";
import type { ColumnMark } from "./grid/EditMarks";
import { isOn, isPersonId, isPicked, PICKED_CLASS, type SelState } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";

// The body rows of a report table (_rows.html, and the heading row of _table.html for a grouped table). A grouped table
// draws a heading «label · count» over its rows; an ungrouped one draws its rows only. Both come from the API's groups.
// With `selection`, each row of a person has a checkbox in the selection column, and a click on the row (outside the
// controls) picks it while selection is on, or opens its first link while it is off (report_select.js).

// The person a row is about: its first cell's person (_rows.html's row.0.person). 0 or none means no person, no checkbox.
export function rowPerson(row: ReportCellOut[]): string | null {
  const person = row.length > 0 ? row[0].person : 0;
  if (!person) return null;
  const id = String(person);
  return isPersonId(id) ? id : null;
}

// The controls of a row: a click on them keeps its own action (report_select.js openRowLink).
const CONTROLS = "a, button, input, select, textarea, label";

function within(target: EventTarget, selector: string): boolean {
  return target instanceof Element && target.closest(selector) !== null;
}

// Opens a record's link: in-app for a ported path, else a full load. The grid's Enter uses it too.
export function openRecord(href: string, go: (to: string) => void) {
  if (isPorted(href)) go(href);
  else window.location.href = href;
}

// The link the row opens is the first cell's link, as the document handler did (`td a[href]`). Ctrl, Cmd or a middle click
// opens a new tab; a plain click goes to the record (in-app for a ported path, else a full load). A text selection is not a
// click. A click inside a <table data-grid> is left to the grid's cursor (grid_nav.js), as the document handler did.
function openRowLink(event: MouseEvent<HTMLTableRowElement>, go: (to: string) => void) {
  if (event.defaultPrevented) return;
  if (within(event.target, "table[data-grid]") || within(event.target, CONTROLS)) return;
  if (window.getSelection()?.toString()) return;
  const href = event.currentTarget.querySelector("td a[href]")?.getAttribute("href");
  if (!href) return;
  if (event.button === 1 || event.ctrlKey || event.metaKey) {
    window.open(href, "_blank");
  } else if (event.button === 0) {
    openRecord(href, go);
  }
}

// While selection is on, a click anywhere on a person's row toggles that person and opens nothing (no link, no button).
// It does not stop the event: the cell's own click still moves the grid cursor and focuses the table. A click on the
// row's own checkbox keeps its native toggle: its change event does the pick.
function pickOnRowClick(
  event: MouseEvent<HTMLTableRowElement>,
  selecting: boolean,
  person: string | null,
  picked: boolean,
  pickRow: ReportSelection["pickRow"] | undefined,
) {
  if (!selecting || person === null || !pickRow) return;
  if (within(event.target, "input[data-select-row]")) return;
  event.preventDefault();
  pickRow(person, !picked);
}

// One body row as the keyboard grid sees it (useGridCursor): the text of each cell as drawn, the links of each cell (Enter
// opens the first), and the row's person (Space ticks it). A group heading is one cell with no link and no person.
export interface GridBodyRow {
  texts: string[];
  hrefs: string[];
  person: string | null;
  // The cell behind each grid column (null for the selection cell and a heading): its edit target says whether it opens.
  cells: (ReportCellOut | null)[];
  heading: boolean;
}

// The grid's rows in draw order, the same order ReportRows draws them: a heading row when grouped, then the rows of the
// group. `check` adds the selection cell in front of each row (text «✓» when its person is picked, as the checkbox reads).
export function gridBodyRows(
  groups: ReportGroupOut[],
  grouped: boolean,
  check: boolean,
  state: SelState | null,
): GridBodyRow[] {
  const out: GridBodyRow[] = [];
  for (const group of groups) {
    if (grouped) {
      out.push({ texts: [`${group.label} · ${group.count}`], hrefs: [""], person: null, cells: [null], heading: true });
    }
    for (const row of group.rows) {
      const person = rowPerson(row);
      const picked = state !== null && person !== null && isPicked(state, person);
      const texts = row.map(cellText);
      const hrefs = row.map((cell) => cell.href);
      out.push({
        texts: check ? [picked ? "✓" : "", ...texts] : texts,
        hrefs: check ? ["", ...hrefs] : hrefs,
        person,
        cells: check ? [null, ...row] : [...row],
        heading: false,
      });
    }
  }
  return out;
}

// The grid cursor of the table as the rows draw it: the cell cursor, its Shift range, and the click and double click.
export interface RowsCursor {
  active: Pos | null;
  range: Box | null;
  onCellClick: (r: number, c: number, shift: boolean) => void;
  onCellDoubleClick?: (r: number, c: number) => void;
  // The open cell editor: drawn in its cell (grid row r, grid column c). `panel` is isPanelEditor of the editor.
  editor?: { r: number; c: number; node: ReactNode; panel: boolean } | null;
  // The cell whose editor is loading or saving (drawn faded).
  busy?: Pos | null;
  // The bulk edit's marks, keyed "row:column" (useBulkEdit).
  marks?: ReadonlyMap<string, CellMark> | null;
  // The editable-column mark of each grid column, when the marks are on (EditMarks.columnMarks).
  colMarks?: ReadonlyArray<ColumnMark> | null;
}

// The editor of one row, as its BodyRow gets it: the grid column it sits in, what to draw, and whether it floats.
interface RowEditing {
  c: number;
  node: ReactNode;
  panel: boolean;
}

// One body row. Memoised: it gets only primitives and stable callbacks, so an arrow press re-renders the two rows whose
// cursor cell changed, not the whole table.
interface BodyRowProps {
  r: number;
  row: ReportCellOut[];
  check: CheckColumn | null;
  person: string | null;
  picked: boolean;
  selecting: boolean;
  pickRow?: ReportSelection["pickRow"];
  cursorOn: boolean;
  activeCol: number | null; // the cursor's column when the cursor is on this row
  rangeCols: { c0: number; c1: number } | null; // the Shift range's columns when this row is in the range
  editing: RowEditing | null; // the open editor, when it is in this row
  busyCol: number | null; // the grid column of the busy cell, when it is in this row
  marks: ReadonlyMap<number, CellMark> | null; // the bulk edit's marks of this row, by grid column
  colMarks: ReadonlyArray<ColumnMark> | null; // the editable-column marks, by grid column (null when the marks are off)
  onCellClick: (r: number, c: number, shift: boolean) => void;
  onCellDoubleClick?: (r: number, c: number) => void;
  go: (to: string) => void;
  hasSelection: boolean;
}

const BodyRow = memo(function BodyRow({
  r,
  row,
  check,
  person,
  picked,
  selecting,
  pickRow,
  cursorOn,
  activeCol,
  rangeCols,
  editing,
  busyCol,
  marks,
  colMarks,
  onCellClick,
  onCellDoubleClick,
  go,
  hasSelection,
}: BodyRowProps) {
  const cellGrid = (c: number): GridCell | undefined =>
    cursorOn
      ? {
          r,
          c,
          active: activeCol === c,
          inRange: rangeCols !== null && c >= rangeCols.c0 && c <= rangeCols.c1,
          onClick: (shift) => onCellClick(r, c, shift),
          onDoubleClick: onCellDoubleClick ? () => onCellDoubleClick(r, c) : undefined,
          mark: marks?.get(c) ?? null,
        }
      : undefined;
  const onRowClick = (event: MouseEvent<HTMLTableRowElement>) => {
    if (selecting) return;
    openRowLink(event, go);
  };
  const checkGrid = check ? cellGrid(0) : undefined;
  const offset = check ? 1 : 0;
  return (
    <tr
      data-person={hasSelection && person !== null ? person : undefined}
      className={picked ? PICKED_CLASS : undefined}
      aria-selected={hasSelection && person !== null ? picked : undefined}
      onClickCapture={hasSelection ? (event) => pickOnRowClick(event, selecting, person, picked, pickRow) : undefined}
      onClick={onRowClick}
      onAuxClick={onRowClick}
    >
      {check ? (
        <td
          data-r={checkGrid?.r}
          data-c={checkGrid?.c}
          {...gridTdProps(checkGrid, check.css)}
          style={inlineStyle(check.style)}
        >
          {hasSelection && person !== null ? (
            <input
              type="checkbox"
              data-select-row
              autoComplete="off"
              aria-label="Мөр сонгох"
              checked={picked}
              onChange={() => pickRow?.(person, !picked)}
            />
          ) : null}
        </td>
      ) : null}
      {row.map((cell, cellIndex) => {
        const c = cellIndex + offset;
        const open = editing !== null && editing.c === c;
        return (
          <ReportCell
            key={cellIndex}
            cell={cell}
            grid={cellGrid(c)}
            editor={open ? editing.node : undefined}
            panel={open && editing.panel}
            busy={busyCol === c}
            mark={colMarks?.[c]}
          />
        );
      })}
    </tr>
  );
});

export function ReportRows({
  groups,
  grouped,
  tableSpan,
  check = null,
  selection = null,
  cursor = null,
}: {
  groups: ReportGroupOut[];
  grouped: boolean;
  tableSpan: number;
  check?: CheckColumn | null;
  selection?: ReportSelection | null;
  cursor?: RowsCursor | null;
}) {
  const go = useTransitionNavigate();
  const selecting = selection !== null && isOn(selection.state);
  const pickRow = selection?.pickRow;
  const cursorOn = cursor !== null;
  const onCellClick = cursor?.onCellClick ?? noop;
  // The bulk marks of each row, grouped by row (memoised: the rows keep their props while the marks do not change).
  const markRows = useMemo(() => groupMarks(cursor?.marks ?? null), [cursor?.marks]);
  const colMarks = cursor?.colMarks ?? null;
  const onCellDoubleClick = cursor?.onCellDoubleClick;
  // The grid row of each body row: a group heading is a row of its own, counted as gridBodyRows counts it.
  let index = 0;
  const rowCursor = (r: number) => ({
    activeCol: cursor?.active && cursor.active.r === r ? cursor.active.c : null,
    rangeCols:
      cursor?.range && r >= cursor.range.r0 && r <= cursor.range.r1
        ? { c0: cursor.range.c0, c1: cursor.range.c1 }
        : null,
    editing:
      cursor?.editor && cursor.editor.r === r
        ? { c: cursor.editor.c, node: cursor.editor.node, panel: cursor.editor.panel }
        : null,
    busyCol: cursor?.busy && cursor.busy.r === r ? cursor.busy.c : null,
  });
  return (
    <>
      {groups.map((group, groupIndex) => {
        const headRow = grouped ? index++ : -1;
        const head = rowCursor(headRow);
        const headGrid: GridCell | undefined = grouped && cursorOn
          ? {
              r: headRow,
              c: 0,
              active: head.activeCol === 0,
              inRange: head.rangeCols !== null,
              onClick: (shift) => onCellClick(headRow, 0, shift),
              onDoubleClick: onCellDoubleClick ? () => onCellDoubleClick(headRow, 0) : undefined,
            }
          : undefined;
        return (
          <Fragment key={groupIndex}>
            {grouped ? (
              <tr>
                <td
                  colSpan={tableSpan}
                  data-r={headGrid?.r}
                  data-c={headGrid?.c}
                  {...gridTdProps(headGrid, "font-semibold text-slate-900")}
                >
                  {group.label} · {group.count}
                </td>
              </tr>
            ) : null}
            {group.rows.map((row, rowIndex) => {
              const r = index++;
              const person = rowPerson(row);
              const picked = selection !== null && person !== null && isPicked(selection.state, person);
              const { activeCol, rangeCols, editing, busyCol } = rowCursor(r);
              const marks = markRows.get(r) ?? null;
              return (
                <BodyRow
                  key={rowIndex}
                  r={r}
                  row={row}
                  check={check}
                  person={person}
                  picked={picked}
                  selecting={selecting}
                  pickRow={pickRow}
                  cursorOn={cursorOn}
                  activeCol={activeCol}
                  rangeCols={rangeCols}
                  editing={editing}
                  busyCol={busyCol}
                  marks={marks}
                  colMarks={colMarks}
                  onCellClick={onCellClick}
                  onCellDoubleClick={onCellDoubleClick}
                  go={go}
                  hasSelection={selection !== null}
                />
              );
            })}
          </Fragment>
        );
      })}
    </>
  );
}

const noop = () => {};

// The marks keyed "row:column" as one map per row, keyed by column.
function groupMarks(marks: ReadonlyMap<string, CellMark> | null): Map<number, Map<number, CellMark>> {
  const rows = new Map<number, Map<number, CellMark>>();
  marks?.forEach((mark, key) => {
    const [r, c] = key.split(":").map(Number);
    const row = rows.get(r) ?? new Map<number, CellMark>();
    row.set(c, mark);
    rows.set(r, row);
  });
  return rows;
}
