// Pure helpers of the keyboard grid (port of the pure section of app/static/js/grid_nav.js, UI_RULES §4 «Keyboard grid»).
// No DOM and no React: the grid hook calls these. Each function keeps the JS name, argument order and semantics, so a
// reader can diff the two files. Rows are 0-based; `Box` is an inclusive rectangle of rows r0..r1 and columns c0..c1.

export type Pos = { r: number; c: number };
export type Box = { r0: number; r1: number; c0: number; c1: number };
export type Cell = { text: string; r: number; c: number };
export type ColumnKind = "" | "edit" | "correct";
export type GridCellFlags = { edit: boolean; correct: boolean };

// The subset of a KeyboardEvent that isPrintable reads.
export type KeyLike = { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean };

const PAGE = 10;

// True when the answer is the login page: an expired session makes @login_required redirect every fetch to
// /login/?next=..., and fetch follows it, so the status is 200 and only the final URL shows it.
export function sessionLost(res: { url: string }): boolean {
  try {
    return new URL(res.url, "http://localhost/").pathname.startsWith("/login");
  } catch {
    return false;
  }
}

// The next position for a key. `pos` is {r, c}; `widths` is the cell count of each row. Returns null for a key
// that is not a move. Columns are clamped to the target row's width (a group-title row has one wide cell).
export function move(pos: Pos, key: string, widths: readonly number[], ctrl = false): Pos | null {
  const last = widths.length - 1;
  if (last < 0) return null;
  const clampC = (r: number, c: number) => Math.max(0, Math.min(c, widths[r] - 1));
  let { r, c } = pos;
  switch (key) {
    case "ArrowUp":
      r = ctrl ? 0 : r - 1;
      break;
    case "ArrowDown":
      r = ctrl ? last : r + 1;
      break;
    case "ArrowLeft":
      c = ctrl ? 0 : c - 1;
      break;
    case "ArrowRight":
      c = ctrl ? widths[r] - 1 : c + 1;
      break;
    case "Home":
      if (ctrl) r = 0;
      c = 0;
      break;
    case "End":
      if (ctrl) r = last;
      c = widths[Math.max(0, Math.min(r, last))] - 1;
      break;
    case "PageUp":
      r -= PAGE;
      break;
    case "PageDown":
      r += PAGE;
      break;
    case "Tab":
      c += 1;
      if (c >= widths[r]) {
        if (r >= last) return pos;
        r += 1;
        c = 0;
      }
      break;
    case "ShiftTab":
      c -= 1;
      if (c < 0) {
        if (r <= 0) return pos;
        r -= 1;
        c = widths[r] - 1;
      }
      break;
    default:
      return null;
  }
  r = Math.max(0, Math.min(r, last));
  return { r, c: clampC(r, c) };
}

// The rectangle between the anchor and the cursor, as {r0, r1, c0, c1}.
export function box(a: Pos, b: Pos): Box {
  return {
    r0: Math.min(a.r, b.r),
    r1: Math.max(a.r, b.r),
    c0: Math.min(a.c, b.c),
    c1: Math.max(a.c, b.c),
  };
}

// Text grid → tab-separated lines, the shape Excel pastes as cells. Tabs and line breaks inside a cell become spaces.
export function toTsv(grid: ReadonlyArray<ReadonlyArray<string | number>>): string {
  return grid
    .map((row) => row.map((t) => String(t).replace(/[\t\r\n]+/g, " ").trim()).join("\t"))
    .join("\n");
}

// Clipboard text → rows of cells, as Excel writes it: lines end at \n (\r\n is fine), cells at \t. A cell that starts
// with a quote runs to the closing quote; "" inside it is one quote, and tabs or line breaks inside stay in the cell.
// One trailing line break adds no row.
export function parseTsv(text: string): string[][] {
  const s = String(text);
  const rows: string[][] = [];
  if (s === "") return rows;
  const isBreak = (i: number) => s[i] === "\n" || (s[i] === "\r" && s[i + 1] === "\n");
  // Reads an unquoted run up to the next tab or line break. Returns the cell and the index after it.
  const readPlain = (start: number, cell: string) => {
    let i = start;
    while (i < s.length && s[i] !== "\t" && !isBreak(i)) cell += s[i++];
    return { cell, i };
  };
  let row: string[] = [];
  let i = 0;
  for (;;) {
    let cell = "";
    if (s[i] === '"') {
      i += 1;
      while (i < s.length) {
        if (s[i] === '"') {
          if (s[i + 1] === '"') {
            cell += '"';
            i += 2;
            continue;
          }
          i += 1; // the closing quote
          break;
        }
        cell += s[i++];
      }
      // anything after the closing quote, up to the next delimiter
      ({ cell, i } = readPlain(i, cell));
    } else {
      ({ cell, i } = readPlain(i, cell));
    }
    row.push(cell);
    if (i >= s.length) {
      rows.push(row);
      break;
    }
    if (s[i] === "\t") {
      i += 1;
      continue;
    }
    i += s[i] === "\r" ? 2 : 1; // a line break ends the row
    rows.push(row);
    row = [];
    if (i >= s.length) break;
  }
  return rows;
}

// The cells a paste writes: {r, c, text}. A single value (1×1) onto a Shift range fills the whole range; otherwise the
// rows are laid from `origin` right and down. Rows past widths.length and cells past a row's width are dropped.
export function planPaste(
  origin: Pos,
  rows: readonly (readonly string[])[],
  widths: readonly number[],
  rangeBox: Box | null,
): Cell[] {
  const out: Cell[] = [];
  const fits = (r: number, c: number) => r >= 0 && r < widths.length && c >= 0 && c < widths[r];
  if (rows.length === 1 && rows[0].length === 1 && rangeBox) {
    const text = rows[0][0];
    for (let r = rangeBox.r0; r <= rangeBox.r1; r++) {
      for (let c = rangeBox.c0; c <= rangeBox.c1; c++) {
        if (fits(r, c)) out.push({ r, c, text });
      }
    }
    return out;
  }
  rows.forEach((cells, i) => {
    const r = origin.r + i;
    if (r >= widths.length) return;
    cells.forEach((text, j) => {
      const c = origin.c + j;
      if (fits(r, c)) out.push({ r, c, text });
    });
  });
  return out;
}

// Fill down: every cell below the top row of the range gets the top row's text of its column (textAt(r0, c)).
export function planFill(rangeBox: Box, textAt: (r: number, c: number) => string): Cell[] {
  const out: Cell[] = [];
  for (let c = rangeBox.c0; c <= rangeBox.c1; c++) {
    const text = textAt(rangeBox.r0, c);
    for (let r = rangeBox.r0 + 1; r <= rangeBox.r1; r++) out.push({ r, c, text });
  }
  return out;
}

// Every cell of the range gets the same text.
export function planSet(rangeBox: Box, text: string): Cell[] {
  const out: Cell[] = [];
  for (let r = rangeBox.r0; r <= rangeBox.r1; r++) {
    for (let c = rangeBox.c0; c <= rangeBox.c1; c++) out.push({ r, c, text });
  }
  return out;
}

// A key that types a character: one character (not a name like "Enter"), with no Ctrl, Meta or Alt.
export function isPrintable(e: KeyLike): boolean {
  return typeof e.key === "string" && Array.from(e.key).length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
}

// The elements that belong to an open cell editor: its form, and the popup of a choice or a date box. The widgets portal
// their popups to document.body (outside the form and the table's cell), so a click or a key in a popup is marked with
// data-widget-popup. React events from a portal still bubble through the React tree to the cell and the table, so the
// cell and the grid check this too.
export const EDITOR_SURFACE = "[data-cell-form], [data-widget-popup]";
export function inEditorSurface(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(EDITOR_SURFACE) !== null;
}

// A key of an input method in composition (IME): the grid ignores it, so it is not taken, not buffered and not prevented.
export function isComposingKey(e: { key: string; nativeEvent?: { isComposing?: boolean } }): boolean {
  return e.nativeEvent?.isComposing === true || e.key === "Process" || e.key === "Dead";
}

// Keys typed while an editor is still loading (phase 2): "Ctrl+A", "Backspace" and the printable characters change
// the text; Enter, Tab, ShiftTab and Escape are the actions that run once the editor is open.
const CONTROL_KEYS: readonly string[] = ["Enter", "Tab", "ShiftTab", "Escape"];

// The buffered keys before the first action key (the text part) and that action key, or null when there is none.
export function splitBuffered(keys: readonly string[]): { text: string[]; action: string | null } {
  const cut = keys.findIndex((k) => CONTROL_KEYS.includes(k));
  return cut < 0
    ? { text: [...keys], action: null }
    : { text: keys.slice(0, cut), action: keys[cut] };
}

// The text after the buffered text keys. A character is added (replacing the text when Ctrl+A came before it),
// Backspace removes the last character (or the whole text after Ctrl+A), Ctrl+A marks the text as selected.
export function applyBuffered(value: string, keys: readonly string[]): string {
  let v = value;
  let selected = false;
  for (const k of keys) {
    if (k === "Ctrl+A") {
      selected = true;
      continue;
    }
    if (k === "Backspace") {
      v = selected ? "" : Array.from(v).slice(0, -1).join("");
      selected = false;
      continue;
    }
    if (CONTROL_KEYS.includes(k)) continue;
    if (selected) {
      v = "";
      selected = false;
    }
    v += k;
  }
  return v;
}

// Editable-column marks (UI_RULES §4b). `rows` is an array of rows, each an array of cells {edit, correct}: edit when
// the cell is editable (data-edit), correct when it needs a reason (data-correct). Returns one kind per column index:
// "correct" when any cell in the column is a correction cell, else "edit" when any cell is editable, else "".
// Ragged rows are fine: the result is as wide as the widest row.
export function columnKinds(rows: readonly (readonly GridCellFlags[])[]): ColumnKind[] {
  const width = rows.reduce((m, row) => Math.max(m, row.length), 0);
  const kinds: ColumnKind[] = new Array<ColumnKind>(width).fill("");
  rows.forEach((row) =>
    row.forEach((cell, c) => {
      if (cell.correct) kinds[c] = "correct";
      else if (cell.edit && kinds[c] === "") kinds[c] = "edit";
    }),
  );
  return kinds;
}
