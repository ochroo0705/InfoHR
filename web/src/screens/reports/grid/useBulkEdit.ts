import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReportCellOut } from "../../../api/reports";
import {
  bulkCells,
  SessionLost,
  type BulkResult,
  type ReportEditTarget,
} from "../../../api/reportsEdit";
import { box, parseTsv, planFill, planPaste, planSet, type Box, type Cell, type Pos } from "./gridMath";
import type { BarAction } from "./BulkBar";
import { targetKey, type CellEditText } from "./useCellEdit";

// The bulk edit of a report table (port of the bulk part of app/static/js/grid_nav.js, UI_RULES §4 «Bulk edit on report
// tables»). Every batch is first a dry run (apply false): the server checks each cell and the table shows the preview.
// Хадгалах sends the changed cells with apply true; after that Буцаах sends the old texts back as a new batch. Only cells
// whose edit target has the route "cell" take part; the rest are counted as «засах боломжгүй». One preview at a time.
// A new address (resetKey) discards the preview. An answer that comes after that, or after a discard, changes nothing.

// Django bulk_edit.MAX_CELLS and its TOO_MANY text.
export const MAX_CELLS = 500;
export const TOO_MANY = "Нэг удаад 500 хүртэл нүд";
// The words of grid_nav.js for the bar's progress and for a request that got no answer.
const CHECKING = "Шалгаж байна…";
const SAVING = "Хадгалж байна…";
const UNDOING = "Буцааж байна…";
const NO_ANSWER = "Холбогдож чадсангүй. Дахин оролдоно уу.";
// After an undo the bar closes by itself (grid_nav.js UNDO_MS).
const UNDO_MS = 4000;

// A mark on a grid cell: amber will change (pending), red refused with the reason as its title (rejected).
export interface CellMark {
  kind: "pending" | "rejected";
  title?: string;
}

// What the hook reads of each body row: the text drawn and the cell behind each column (null for the check column and
// a group heading).
export interface BulkLookupRow {
  texts: readonly string[];
  cells: readonly (ReportCellOut | null)[];
}

export interface BulkEditOptions {
  resetKey: string;
  rows: readonly BulkLookupRow[];
  currentEpoch: () => number;
  setTexts: (entries: readonly CellEditText[], epoch: number) => void;
  // Called after the bar closes by a discard (the table takes the focus back).
  onClosed?: () => void;
}

export interface BulkEdit {
  marks: ReadonlyMap<string, CellMark>; // keyed "row:column"
  previews: ReadonlyMap<string, string>; // the text a pending cell will show, keyed by targetKey
  bar: { message: string; actions: BarAction[] } | null;
  active: () => boolean; // a batch or its bar is showing (read now, not from the last render)
  paste: (origin: Pos, text: string, range: Box | null) => void;
  fillDown: (range: Box) => void;
  clear: (range: Box) => void;
  setRange: (range: Box, text: string) => void;
  onKey: (e: BulkKeyEvent) => boolean; // keys while a batch shows: held, except Tab and the browser's shortcuts
  escape: () => void;
}

type Phase = "busy" | "preview" | "saving" | "saved" | "undoing" | "undone" | "error";

// The keys a batch's preview reads. Tab, F5 and the browser's shortcuts (Ctrl, Meta, Alt) are not the batch's: they pass
// through, so the bar's buttons stay reachable by Tab.
export interface BulkKeyEvent {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  preventDefault: () => void;
}

// One cell of a batch. `state` moves preview -> saved or failed (save) and saved -> undone (undo).
interface BulkEntry {
  pos: Pos;
  target: ReportEditTarget;
  req: string; // the text typed or pasted
  old: string; // the text shown before, trimmed
  ok: boolean; // the server accepted the cell in the dry run
  text: string; // the text the server answered (ok only)
  error: string;
  changed: boolean; // ok and the text differs from old
  state: "preview" | "saved" | "failed" | "undone";
}

interface BulkState {
  key: string; // the address (resetKey) the batch belongs to
  epoch: number;
  phase: Phase;
  message: string;
  entries: BulkEntry[];
}

interface Target {
  pos: Pos;
  target: ReportEditTarget;
  req: string;
  old: string;
}

type Outcome = BulkResult["cells"][number];

function messageOf(err: unknown): string {
  return err instanceof Error && err.message ? err.message : NO_ANSWER;
}

function countsText(changed: number, rejected: number, skipped: number): string {
  return `${changed} нүд өөрчлөгдөнө · ${rejected} алдаатай · ${skipped} засах боломжгүй`;
}

// The cells that may take part, and how many were skipped. A cell outside its row is not counted (the grid has no such
// cell); a cell that is not an edit target of route "cell" is skipped; so is a second cell of the same person and field.
function planTargets(rows: readonly BulkLookupRow[], cells: readonly Cell[]): { list: Target[]; skipped: number } {
  const list: Target[] = [];
  const seen = new Set<string>();
  let skipped = 0;
  for (const { r, c, text } of cells) {
    const row = rows[r];
    if (!row || c < 0 || c >= row.texts.length) continue;
    const target = row.cells[c]?.edit ?? null;
    if (!target || target.route !== "cell") {
      skipped += 1;
      continue;
    }
    const key = `${target.person}|${target.field}`;
    if (seen.has(key)) {
      skipped += 1;
      continue;
    }
    seen.add(key);
    list.push({ pos: { r, c }, target, req: text, old: row.texts[c].trim() });
  }
  return { list, skipped };
}

// The server's outcomes matched back to a cell by person and field.
function outcomesByKey(outcomes: readonly Outcome[]): Map<string, Outcome> {
  const map = new Map<string, Outcome>();
  for (const o of outcomes) map.set(`${o.person}|${o.field}`, o);
  return map;
}

function toCell(e: BulkEntry) {
  return { person: e.target.person, field: e.target.field, text: e.req, old: e.old };
}

function entryFor(t: Target, o: Outcome | undefined): BulkEntry {
  const ok = Boolean(o && o.ok);
  const text = ok ? o?.text || "" : "";
  return {
    pos: t.pos,
    target: t.target,
    req: t.req,
    old: t.old,
    ok,
    text,
    error: ok ? "" : o?.error || NO_ANSWER,
    changed: ok && text !== t.old,
    state: "preview",
  };
}

function busyPhase(phase: Phase): boolean {
  return phase === "busy" || phase === "saving" || phase === "undoing";
}

export function useBulkEdit(options: BulkEditOptions): BulkEdit {
  const { resetKey } = options;
  // The latest options, read by the handlers (which stay stable).
  const optionsRef = useRef(options);
  optionsRef.current = options;
  // The batch now. A ref mirrors the state, so an answer can tell whether its batch is still the one shown.
  const [cur, setCur] = useState<BulkState | null>(null);
  const curRef = useRef<BulkState | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const publish = useCallback((next: BulkState | null) => {
    curRef.current = next;
    setCur(next);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  // A new address discards the batch.
  useEffect(() => {
    curRef.current = null;
    setCur(null);
    clearTimer();
  }, [resetKey, clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  const discard = useCallback(() => {
    const st = curRef.current;
    if (!st || busyPhase(st.phase)) return;
    clearTimer();
    publish(null);
    optionsRef.current.onClosed?.();
  }, [clearTimer, publish]);

  // Хадгалах: the changed cells are saved with apply true. A refused save restores every cell (no marks, no new texts).
  const save = useCallback(() => {
    const st = curRef.current;
    if (!st || st.phase !== "preview") return;
    const todo = new Set(st.entries.filter((e) => e.changed));
    if (todo.size === 0) return;
    const saving: BulkState = { ...st, phase: "saving", message: SAVING };
    publish(saving);
    bulkCells([...todo].map(toCell), true).then(
      (data) => {
        if (curRef.current !== saving) return;
        const got = outcomesByKey(data.cells);
        const entries = saving.entries.map((e) => {
          if (!todo.has(e)) return e;
          const o = got.get(`${e.target.person}|${e.target.field}`);
          return o?.ok
            ? { ...e, state: "saved" as const, text: o.text || "" }
            : { ...e, state: "failed" as const, error: o?.error || NO_ANSWER };
        });
        const saved = entries.filter((e) => e.state === "saved");
        optionsRef.current.setTexts(
          saved.map((e) => ({ target: e.target, text: e.text })),
          saving.epoch,
        );
        const notSaved = entries.filter((e) => !e.ok || e.state === "failed").length;
        publish({
          ...saving,
          phase: "saved",
          entries,
          message: `${saved.length} нүд хадгалагдлаа` + (notSaved ? ` · ${notSaved} хадгалагдсангүй` : ""),
        });
      },
      (err: unknown) => {
        if (curRef.current !== saving) return;
        publish({ ...saving, phase: "error", message: messageOf(err), entries: [] });
      },
    );
  }, [publish]);

  // Буцаах: the saved cells get their old texts back, as a new batch with apply true. A stale cell is refused by the server.
  const undo = useCallback(() => {
    const st = curRef.current;
    if (!st || st.phase !== "saved") return;
    const todo = new Set(st.entries.filter((e) => e.state === "saved"));
    if (todo.size === 0) return;
    const undoing: BulkState = { ...st, phase: "undoing", message: UNDOING };
    publish(undoing);
    bulkCells(
      [...todo].map((e) => ({ person: e.target.person, field: e.target.field, text: e.old, old: e.text })),
      true,
    ).then(
      (data) => {
        if (curRef.current !== undoing) return;
        const got = outcomesByKey(data.cells);
        const entries = undoing.entries.map((e) => {
          if (!todo.has(e)) return e;
          const o = got.get(`${e.target.person}|${e.target.field}`);
          return o?.ok ? { ...e, state: "undone" as const } : e;
        });
        const undone = entries.filter((e) => e.state === "undone");
        optionsRef.current.setTexts(
          undone.map((e) => ({ target: e.target, text: e.old })),
          undoing.epoch,
        );
        const left = todo.size - undone.length;
        publish({
          ...undoing,
          phase: "undone",
          entries,
          message: `Буцаалаа: ${undone.length}` + (left ? ` · ${left} буцаагдсангүй` : ""),
        });
        clearTimer();
        timerRef.current = setTimeout(() => {
          timerRef.current = null;
          if (curRef.current?.phase === "undone") discard();
        }, UNDO_MS);
      },
      (err: unknown) => {
        if (curRef.current !== undoing) return;
        if (err instanceof SessionLost) {
          // Nothing was undone; the saved cells keep their saved text when the bar closes.
          publish({ ...undoing, phase: "error", message: messageOf(err) });
          return;
        }
        publish({ ...undoing, phase: "saved", message: messageOf(err) });
      },
    );
  }, [clearTimer, discard, publish]);

  // Starts a batch from the grid's cells: builds the targets, then asks for the dry run (or refuses the batch).
  const start = useCallback(
    (cells: readonly Cell[]) => {
      if (curRef.current) return;
      const { rows, currentEpoch, resetKey: key } = optionsRef.current;
      const { list, skipped } = planTargets(rows, cells);
      const epoch = currentEpoch();
      // The cap counts the editable cells actually posted, not the cells of the range (as Django's parse_body does).
      if (list.length > MAX_CELLS) {
        publish({ key, epoch, phase: "error", message: TOO_MANY, entries: [] });
        return;
      }
      if (list.length === 0) {
        // Every target was skipped: say so, so Delete on such cells is not silent.
        if (skipped === 0) return;
        publish({
          key,
          epoch,
          phase: "preview",
          message: countsText(0, 0, skipped),
          entries: [],
        });
        return;
      }
      const checking: BulkState = { key, epoch, phase: "busy", message: CHECKING, entries: [] };
      publish(checking);
      bulkCells(
        list.map((t) => ({ person: t.target.person, field: t.target.field, text: t.req, old: t.old })),
        false,
      ).then(
        (data) => {
          if (curRef.current !== checking) return;
          const got = outcomesByKey(data.cells);
          const entries = list.map((t) => entryFor(t, got.get(`${t.target.person}|${t.target.field}`)));
          const changed = entries.filter((e) => e.changed).length;
          const rejected = entries.filter((e) => !e.ok).length;
          publish({
            ...checking,
            phase: "preview",
            entries,
            message: countsText(changed, rejected, skipped),
          });
        },
        (err: unknown) => {
          if (curRef.current !== checking) return;
          publish({ ...checking, phase: "error", message: messageOf(err), entries: [] });
        },
      );
    },
    [publish],
  );

  const rangeOf = (at: Pos, range: Box | null): Box => range ?? box(at, at);

  const paste = useCallback(
    (origin: Pos, text: string, range: Box | null) => {
      const rows = optionsRef.current.rows;
      const widths = rows.map((row) => row.texts.length);
      start(planPaste(origin, parseTsv(text), widths, range));
    },
    [start],
  );

  const fillDown = useCallback(
    (range: Box) => {
      const rows = optionsRef.current.rows;
      start(planFill(range, (r, c) => (rows[r]?.texts[c] ?? "").trim()));
    },
    [start],
  );

  const clear = useCallback((range: Box) => start(planSet(range, "")), [start]);

  const setRange = useCallback((range: Box, text: string) => start(planSet(range, text.trim())), [start]);

  const escape = discard;

  const onKey = useCallback(
    (e: BulkKeyEvent): boolean => {
      const st = curRef.current;
      if (!st) return false;
      if (e.key === "Tab" || e.key === "F5" || e.ctrlKey || e.metaKey || e.altKey) return false;
      e.preventDefault();
      if (e.key === "Escape") {
        discard();
      } else if (e.key === "Enter" && st.phase === "preview") {
        save();
      }
      return true;
    },
    [discard, save],
  );

  // The bar's message and buttons for the phase (grid_nav.js showBar calls).
  const visible = cur && cur.key === resetKey ? cur : null;
  const bar = useMemo(() => {
    if (!visible) return null;
    const { phase, entries, message } = visible;
    let actions: BarAction[] = [];
    if (phase === "preview") {
      const changed = entries.some((e) => e.changed);
      actions = changed
        ? [
            { label: "Хадгалах", main: true, run: save },
            { label: "Болих", run: discard },
          ]
        : [{ label: "Хаах", main: true, run: discard }];
    } else if (phase === "saved") {
      const saved = entries.some((e) => e.state === "saved");
      actions = [
        ...(saved ? [{ label: "Буцаах", run: undo }] : []),
        { label: "Хаах", run: discard },
      ];
    } else if (phase === "undone" || phase === "error") {
      actions = [{ label: "Хаах", main: true, run: discard }];
    }
    return { message, actions };
  }, [visible, save, undo, discard]);

  // The marks and the texts of the cells of the batch. A saved, failed or undone cell shows its own state.
  const marks = useMemo(() => {
    const map = new Map<string, CellMark>();
    for (const e of visible?.entries ?? []) {
      const key = `${e.pos.r}:${e.pos.c}`;
      if (e.state === "failed" || (e.state === "preview" && !e.ok)) {
        map.set(key, { kind: "rejected", title: e.error });
      } else if (e.state === "preview" && e.changed) {
        map.set(key, { kind: "pending" });
      }
    }
    return map;
  }, [visible]);

  const previews = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of visible?.entries ?? []) {
      if (e.state === "preview" && e.changed) map.set(targetKey(e.target), e.text);
    }
    return map;
  }, [visible]);

  const active = useCallback(() => curRef.current !== null, []);

  return { marks, previews, bar, active, paste, fillDown, clear, setRange, onKey, escape };
}
