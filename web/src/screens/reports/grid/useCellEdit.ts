import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchEditor,
  NO_FORM_MSG,
  SESSION_LOST_TEXT,
  SessionLost,
  type ReportEditor,
  type ReportEditTarget,
} from "../../../api/reportsEdit";
import { isPrintable, type Pos } from "./gridMath";

// The open state of the cell editor of a report table (port of the open, buffer, save and cancel part of
// app/static/js/grid_nav.js startEdit, bufferKey, openFailed, cancelEdit and submit's table update; UI_RULES §4 «Inline
// cell editing»). One editor at a time. While the editor loads, the keys typed are kept in the session (`buffer`) and
// handed to CellEditor with the opening key (`initialText`), as grid_nav.js does.
//
// Saved texts are keyed by the cell's TARGET identity (`targetKey`: route, person, field, kind, key, record, salary), not
// by its grid position, so a row that moves keeps its text. They live in one "epoch": a new epoch starts on every address
// change and every refetch of the rows (`resetKey`). A save that finishes in another epoch writes nothing, and an A to B
// and back to A round trip starts empty, because the map is cleared with the epoch, not hidden.

// The note F2 or a double click shows on a cell that cannot be edited (grid_nav.js NO_EDIT_MSG). It stays for 3 s.
export const NO_EDIT_MSG = "Энэ баганыг эндээс засах боломжгүй";
const NOTE_MS = 3000;

// The editor of one cell. `editor` is null while it loads. `buffered` is one array for the whole session, so a key typed
// after the answer arrived but before the editor mounted is still handed to it. `epoch` is the epoch it opened in.
export interface CellEditSession {
  pos: Pos;
  epoch: number;
  editor: ReportEditor | null;
  initialText?: string;
  buffered: string[];
}

// A line above the table: a note (F2 on a cell that cannot be edited) or the failure to open an editor.
export interface CellEditNotice {
  text: string;
  tone: "note" | "error";
}

export interface CellEditOptions {
  // The address and the rows' data version. A new address or a refetch starts a new epoch.
  resetKey: string;
  // The edit target of the cell at a grid position, or null when the cell cannot be edited.
  targetAt: (pos: Pos) => ReportEditTarget | null;
}

export interface CellEditText {
  target: ReportEditTarget;
  text: string;
}

export interface CellEdit {
  editing: Pos | null; // the cell whose editor is open or loading
  session: CellEditSession | null; // the open session, as last rendered
  loading: boolean; // the editor is open but still loading
  saving: boolean; // a save is running (the editor is locked, clicks and cancels do nothing)
  overrides: ReadonlyMap<string, string>; // saved texts, keyed by targetKey
  notice: CellEditNotice | null;
  open(pos: Pos, typed?: string): void; // a no-op while another editor is open or the cell has no target
  current(): CellEditSession | null; // the session now (read from a ref, so a key in the render gap sees it)
  isSaving(): boolean; // a save runs now (read from a ref)
  buffer(key: string): void; // keeps a key typed while the editor loads
  currentEpoch(): number;
  setSaving(on: boolean, epoch: number): void;
  setTexts(entries: readonly CellEditText[], epoch?: number): void; // writes many saved texts (bulk uses this too)
  onSaved(target: ReportEditTarget, text: string, epoch: number): void; // closes the editor, keeps the text
  cancel(): void; // closes the editor with nothing saved; a no-op while a save runs
  note(text: string): void;
  dismissNotice(): void;
}

// The identity of a cell's edit target: the same person's same field is the same key wherever the row sits.
export function targetKey(t: ReportEditTarget): string {
  return [t.route, t.person, t.field, t.kind, t.key, t.record, t.salary ? 1 : 0].join("|");
}

// The key name grid_nav.js bufferKey records for a key typed while the editor loads, or null when the key is not kept
// (other shortcuts and the arrows are left to the grid, which ignores them while the editor loads).
export function bufferName(e: { key: string; shiftKey: boolean; ctrlKey: boolean; metaKey: boolean; altKey: boolean }): string | null {
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && (e.key === "a" || e.key === "A")) return "Ctrl+A";
  if (ctrl) return null;
  if (e.key === "Backspace") return "Backspace";
  if (e.key === "Enter") return "Enter";
  if (e.key === "Tab") return e.shiftKey ? "ShiftTab" : "Tab";
  if (e.key === "Escape") return "Escape";
  if (isPrintable(e)) return e.key;
  return null;
}

const NO_OVERRIDES: ReadonlyMap<string, string> = new Map();

export function useCellEdit({ resetKey, targetAt }: CellEditOptions): CellEdit {
  const [session, setSession] = useState<CellEditSession | null>(null);
  // Mirrors `session` synchronously: the key handlers and the request answers read it, not the last render.
  const sessionRef = useRef<CellEditSession | null>(null);
  // The epoch: a counter that moves whenever the reset key changes. Set while rendering (a pure function of resetKey,
  // so a second render with the same key changes nothing).
  const epochRef = useRef({ key: resetKey, n: 0 });
  if (epochRef.current.key !== resetKey) epochRef.current = { key: resetKey, n: epochRef.current.n + 1 };
  const [held, setHeld] = useState<{ epoch: number; map: ReadonlyMap<string, string> }>({
    epoch: epochRef.current.n,
    map: NO_OVERRIDES,
  });
  const savingRef = useRef(false);
  const [saving, setSavingState] = useState(false);
  const [notice, setNotice] = useState<CellEditNotice | null>(null);
  // Counts the requests and the closes: an answer to an older request is dropped.
  const seq = useRef(0);
  const targetRef = useRef(targetAt);
  targetRef.current = targetAt;
  const noteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const commit = useCallback((next: CellEditSession | null) => {
    sessionRef.current = next;
    setSession(next);
  }, []);

  // A new address or a refetch: the editor closes, the saving flag clears and the saved texts are cleared.
  useEffect(() => {
    seq.current += 1;
    savingRef.current = false;
    setSavingState(false);
    setNotice(null);
    setHeld({ epoch: epochRef.current.n, map: NO_OVERRIDES });
    commit(null);
  }, [resetKey, commit]);

  useEffect(
    () => () => {
      if (noteTimer.current) clearTimeout(noteTimer.current);
    },
    [],
  );

  const open = useCallback(
    (pos: Pos, typed?: string) => {
      if (sessionRef.current || savingRef.current) return;
      const target = targetRef.current(pos);
      if (!target) return;
      const token = ++seq.current;
      setNotice(null);
      commit({ pos, epoch: epochRef.current.n, editor: null, initialText: typed, buffered: [] });
      fetchEditor(target).then(
        (editor) => {
          if (token !== seq.current) return;
          const prev = sessionRef.current;
          if (!prev || prev.editor !== null) return;
          // The same buffer array goes on: keys typed after this line still reach the editor.
          commit({ ...prev, editor });
        },
        (err: unknown) => {
          // The editor did not open: nothing is drawn, and the message says so (grid_nav.js openFailed).
          if (token !== seq.current) return;
          commit(null);
          setNotice({ text: err instanceof SessionLost ? SESSION_LOST_TEXT : NO_FORM_MSG, tone: "error" });
        },
      );
    },
    [commit],
  );

  const current = useCallback(() => sessionRef.current, []);

  const isSaving = useCallback(() => savingRef.current, []);

  const buffer = useCallback((key: string) => {
    sessionRef.current?.buffered.push(key);
  }, []);

  const currentEpoch = useCallback(() => epochRef.current.n, []);

  const setSaving = useCallback((on: boolean, epoch: number) => {
    if (epoch !== epochRef.current.n) return;
    savingRef.current = on;
    setSavingState(on);
  }, []);

  const setTexts = useCallback((entries: readonly CellEditText[], epoch: number = epochRef.current.n) => {
    if (epoch !== epochRef.current.n || entries.length === 0) return;
    setHeld((prev) => {
      const map = new Map(prev.epoch === epoch ? prev.map : NO_OVERRIDES);
      for (const entry of entries) map.set(targetKey(entry.target), entry.text);
      return { epoch, map };
    });
  }, []);

  const onSaved = useCallback(
    (target: ReportEditTarget, text: string, epoch: number) => {
      // A save from another epoch writes nothing and closes nothing: the address changed while it ran.
      if (epoch !== epochRef.current.n) return;
      setTexts([{ target, text }], epoch);
      savingRef.current = false;
      setSavingState(false);
      const open = sessionRef.current;
      if (open && open.epoch === epoch) commit(null);
    },
    [commit, setTexts],
  );

  const cancel = useCallback(() => {
    if (savingRef.current) return;
    seq.current += 1;
    commit(null);
  }, [commit]);

  const note = useCallback((text: string) => {
    if (noteTimer.current) clearTimeout(noteTimer.current);
    setNotice({ text, tone: "note" });
    noteTimer.current = setTimeout(() => {
      noteTimer.current = null;
      setNotice((now) => (now?.tone === "note" ? null : now));
    }, NOTE_MS);
  }, []);

  const dismissNotice = useCallback(() => setNotice(null), []);

  return {
    editing: session ? session.pos : null,
    session,
    loading: session !== null && session.editor === null,
    saving,
    overrides: held.epoch === epochRef.current.n ? held.map : NO_OVERRIDES,
    notice,
    open,
    current,
    isSaving,
    buffer,
    currentEpoch,
    setSaving,
    setTexts,
    onSaved,
    cancel,
    note,
    dismissNotice,
  };
}
