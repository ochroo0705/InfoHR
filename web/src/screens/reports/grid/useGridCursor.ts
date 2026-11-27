import { useCallback, useRef, useState, type FocusEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { box, inEditorSurface, isComposingKey, isPrintable, move, toTsv, type Box, type Pos } from "./gridMath";

// The keyboard cursor of a report table (UI_RULES §4 «Keyboard grid on report tables», port of the key and cursor part of
// app/static/js/grid_nav.js). The table is read from the React row model, not from the DOM: `rows` holds, for each body
// row in draw order, the text of each cell as the user sees it (a group heading row is one cell wide). A batch appended
// at the end keeps the cursor and any range; a new address (`resetKey`) clears them.
// The returned handlers are stable while `resetKey` is the same, so memoised rows do not re-render on every key.

export type GridKeyEvent = ReactKeyboardEvent<Element>;

export interface GridCursorOptions {
  rows: readonly (readonly string[])[];
  resetKey: string;
  // Enter on a cell that no edit hook took: opens the row's link (the cell's own link first). Receives the cell.
  onOpenRow?: (r: number, c: number) => void;
  // Space: ticks the row's box. Return false when the row has no box (the key then does nothing).
  onToggleRow?: (r: number) => boolean | void;
  // Keys an editor takes first (F2, Enter, a typed character) on the cursor cell. Return true when the key was taken.
  onEditKey?: (pos: Pos, e: GridKeyEvent) => boolean;
  // Ctrl+D (fill down) and Delete (clear) on the cursor cell, with the cursor's range (the cell alone when there is no
  // Shift range). When set, the key is taken and its default is prevented; the bulk edit answers here.
  onBulkKey?: (pos: Pos, range: Box, e: GridKeyEvent) => void;
}

export interface GridCursor {
  active: Pos | null;
  range: Box | null;
  onKeyDown: (e: GridKeyEvent) => void;
  onFocus: (e: FocusEvent<Element>) => void;
  onCellClick: (r: number, c: number, shift: boolean) => void;
  clear: () => void;
}

interface Held {
  key: string;
  active: Pos | null;
  anchor: Pos | null;
}

// The state of an address; a state from another address reads as empty.
function fresh(h: Held, key: string): Held {
  return h.key === key ? h : { key, active: null, anchor: null };
}

// A position inside the rows, or null (rows shrunk or a cell is gone).
function valid(p: Pos | null, rows: readonly (readonly string[])[]): Pos | null {
  if (!p || p.r < 0 || p.r >= rows.length) return null;
  return p.c >= 0 && p.c < rows[p.r].length ? p : null;
}

// Fields inside a body cell keep their own keys (the row's checkbox, the editor, the «Цааш харуулах» pill).
const FIELD = "input, select, textarea, button, summary, [contenteditable='true']";

// Keys are the grid's when the table itself has focus, or a body cell inside it does. Header links and fields do not drive
// the cursor (grid_nav.js isField).
export function isGridTarget(e: GridKeyEvent): boolean {
  const t = e.target;
  if (!(t instanceof Element)) return false;
  if (inEditorSurface(t)) return false; // a popup of a choice or date box, portaled out of the cell
  if (t === e.currentTarget) return true;
  return t.closest("tbody td") !== null && t.closest(FIELD) === null;
}

const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]";

// Moves focus to the first focusable element after the table, for a forward Tab at its last cell. The table's own
// descendants (its header links) follow it in the document, so the browser would otherwise step into them.
function focusAfter(table: Element): boolean {
  const next = Array.from(document.querySelectorAll<HTMLElement>(FOCUSABLE)).find(
    (el) =>
      !table.contains(el) &&
      el.tabIndex >= 0 &&
      (table.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
  );
  if (!next) return false;
  next.focus();
  return true;
}

export function useGridCursor(options: GridCursorOptions): GridCursor {
  const { rows, resetKey } = options;
  const [held, setHeld] = useState<Held>({ key: resetKey, active: null, anchor: null });
  // Mirrors `held` synchronously, so two keys before a render read the state the first one left.
  const heldRef = useRef<Held>(held);
  // The latest options, read by the stable handlers below.
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const commit = useCallback((next: Held) => {
    heldRef.current = next;
    setHeld(next);
  }, []);

  const cur = fresh(held, resetKey);
  const active = valid(cur.active, rows);
  const anchor = valid(cur.anchor, rows);
  const range = active && anchor ? box(anchor, active) : null;

  const onKeyDown = useCallback(
    (e: GridKeyEvent) => {
      const { rows: current, onOpenRow, onToggleRow, onEditKey, onBulkKey } = optionsRef.current;
      // A key another handler took, an IME key, or a key outside the grid's cells is not the cursor's.
      if (e.defaultPrevented || isComposingKey(e) || !isGridTarget(e) || current.length === 0) return;
      const state = fresh(heldRef.current, resetKey);
      const at = valid(state.active, current);
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key;

      if (ctrl && (key === "c" || key === "C")) {
        if (!at) return;
        if (window.getSelection?.()?.toString()) return; // the user selected text: the browser copies it
        const b = state.anchor && valid(state.anchor, current) ? box(state.anchor, at) : box(at, at);
        const grid: string[][] = [];
        for (let r = b.r0; r <= b.r1; r++) {
          const line: string[] = [];
          for (let c = b.c0; c <= b.c1; c++) line.push(current[r]?.[c] ?? "");
          grid.push(line);
        }
        void navigator.clipboard?.writeText(toTsv(grid)).catch(() => {});
        e.preventDefault();
        return;
      }
      if (at && onBulkKey && ((ctrl && (key === "d" || key === "D")) || (key === "Delete" && !ctrl))) {
        const range = state.anchor && valid(state.anchor, current) ? box(state.anchor, at) : box(at, at);
        onBulkKey(at, range, e);
        e.preventDefault();
        return;
      }
      if (key === "Escape") {
        commit({ key: resetKey, active: state.active, anchor: null });
        return;
      }
      if (key === " ") {
        if (at && onToggleRow && onToggleRow(at.r) !== false) e.preventDefault();
        return;
      }
      if (key === "Enter") {
        if (!at || onEditKey?.(at, e)) return;
        e.preventDefault();
        onOpenRow?.(at.r, at.c);
        return;
      }
      if (key === "F2") {
        if (at) onEditKey?.(at, e);
        return;
      }
      if (at && isPrintable(e) && onEditKey?.(at, e)) return;

      const pos = at ?? { r: 0, c: 0 };
      const moveKey = key === "Tab" && e.shiftKey ? "ShiftTab" : key;
      const moved = move(pos, moveKey, current.map((row) => row.length), ctrl);
      if (!moved) return;
      // With no cursor yet, the first move key puts the cursor on the first cell (row 0, column 0) and moves nothing.
      const next = at ? moved : pos;
      const isTab = moveKey === "Tab" || moveKey === "ShiftTab";
      if (at && isTab && next.r === pos.r && next.c === pos.c) {
        // The last cell: a forward Tab leaves the table for the next focusable element. Shift+Tab at the first cell
        // is left to the browser, which goes back out of the table.
        if (moveKey === "Tab" && focusAfter(e.currentTarget)) e.preventDefault();
        return;
      }
      const extend = e.shiftKey && moveKey.startsWith("Arrow");
      commit({ key: resetKey, active: next, anchor: extend ? (valid(state.anchor, current) ?? pos) : null });
      e.preventDefault();
    },
    [resetKey, commit],
  );

  // Tab into the table from above lands on the cell the cursor was on, or the first cell.
  const onFocus = useCallback(
    (e: FocusEvent<Element>) => {
      const current = optionsRef.current.rows;
      if (e.target !== e.currentTarget || current.length === 0) return;
      const state = fresh(heldRef.current, resetKey);
      if (valid(state.active, current)) return;
      commit({ key: resetKey, active: { r: 0, c: 0 }, anchor: null });
    },
    [resetKey, commit],
  );

  // A click only moves the cursor. Shift+click extends the range from the cursor, as the Django grid did.
  const onCellClick = useCallback(
    (r: number, c: number, shift: boolean) => {
      const current = optionsRef.current.rows;
      const state = fresh(heldRef.current, resetKey);
      const from = valid(state.active, current);
      if (shift && from) {
        commit({ key: resetKey, active: { r, c }, anchor: valid(state.anchor, current) ?? from });
        return;
      }
      commit({ key: resetKey, active: { r, c }, anchor: null });
    },
    [resetKey, commit],
  );

  const clear = useCallback(() => commit({ key: resetKey, active: null, anchor: null }), [resetKey, commit]);

  return { active, range, onKeyDown, onFocus, onCellClick, clear };
}
