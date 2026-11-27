import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { SAVE_FAIL, saveEdit, type ReportEditor, type ReportEditTarget } from "../../../api/reportsEdit";
import { DatePicker } from "../../../widgets/DatePicker";
import { Select, type SelectOption } from "../../../widgets/Select";
import { applyBuffered, splitBuffered } from "./gridMath";

// The editor of one report cell (port of the editor part of app/static/js/grid_nav.js, UI_RULES §4 «Inline cell editing»
// and «Floating cell editor»). The caller fetched the editor (`fetchEditor`) and passes it in. Keys, as in grid_nav.js:
// - Enter saves and calls onMove("down"); Tab saves and calls onMove("right"); Shift+Tab saves and calls onMove("left").
// - Esc calls onCancel without a request (not while a save runs). A blocked editor: Enter, Tab and Esc only cancel.
// - While a save runs the editor is locked: a second Enter or Tab does nothing, so one request goes out.
// - An open list (a choice box opens its list on focus, as select.js does): Enter and Tab first let the list pick the
//   active item, then save, as grid_nav.js does (select.js runs first, editorKey then submits). Arrows and Escape stay
//   with the list (Escape closes the list only).
// A clash (ok false with `editor`) puts the fresh value and loaded token in the field and keeps the editor open with the
// error. Any other failure keeps the typed text and shows the message under the field (role alert, data-cell-error).
// A correction (editor.reason) has a required reason box and the grey note; an empty reason is refused here without a
// request. A panel editor (isPanelEditor: a correction or a blocked one) is drawn as the floating panel of the cell
// (form.cell-pop; CSS in input.css), placed from `anchor` (the cell): pop-left near the table's right edge, pop-up near
// its bottom edge.
// Keys typed while the editor was loading (Task 10): `initialText` is the printable key that opened the editor; it
// replaces the text (text and number kinds only). `buffered` are the later keys (grid_nav.js bufferKey names: printable
// characters, "Backspace", "Ctrl+A", "Enter", "Tab", "ShiftTab", "Escape"), applied with gridMath splitBuffered and
// applyBuffered. A buffered action (the first Enter, Tab, Shift+Tab or Escape) runs once after the editor opens.

export type MoveDir = "down" | "right" | "left";

// True when the editor is the floating panel of its cell: a correction (reason box) or a blocked one. The one place that
// decides it; the caller passes the same answer to ReportCell as its `panel` prop.
export function isPanelEditor(editor: ReportEditor): boolean {
  return editor.reason || editor.blocked !== "";
}

export interface CellEditorProps {
  target: ReportEditTarget;
  editor: ReportEditor;
  onSaved: (text: string) => void;
  onCancel: () => void;
  onMove: (dir: MoveDir) => void;
  // The cell the editor belongs to. A panel editor measures its table (.ptable or table) from it. Unset: no placement.
  anchor?: HTMLElement | null;
  // The printable key that opened the editor; replaces the starting text (text and number kinds).
  initialText?: string;
  // The keys typed while the editor was loading (see above).
  buffered?: readonly string[];
  // Told when a save starts and when it ends without closing the editor (a failed or refused save). The table locks its
  // cell clicks and cancels while a save runs.
  onSavingChange?: (saving: boolean) => void;
  // Ctrl+Enter: the editor's text (the option's label for a choice, "" for the blank choice) goes to every cell of the
  // range, and the editor closes without saving (grid_nav.js setMany). Unset: Ctrl+Enter saves as Enter does.
  onSetRange?: (text: string) => void;
}

// The reason is required for a correction (the words the correction flow shows for an empty reason).
const REASON_EMPTY = "Засварын шалтгааныг заавал бичнэ үү.";
// The note's full sentence, shown as its tooltip (_correct_editor.html).
const NOTE_TITLE = "Засвар нь энэ мөрийг анхнаас нь өөрчилнө. Шилжүүлэх, цалин нэмэх бол тушаал гаргана.";
// The field's box classes: the shared INPUT look of the Django editor (employees.forms.INPUT, the same as Select's box),
// so a text editor is as tall as its Django twin (a shorter box moved the row by 8 px).
const FIELD = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
// The correction's reason box has its own, smaller look (_correct_editor.html): not the INPUT look.
const REASON = "w-full rounded border border-slate-300 px-2 py-1 text-sm";

type EditKey = "Enter" | "Tab" | "ShiftTab" | "Escape";
const EDIT_KEYS: readonly string[] = ["Enter", "Tab", "ShiftTab", "Escape"];

// The message of a thrown save: SessionLost, EditFailed and an ApiFailure all carry their text in `message`.
function messageOf(err: unknown): string {
  return err instanceof Error && err.message ? err.message : SAVE_FAIL;
}

// The choices of a choice editor. A current value that is not among the choices (it was removed from the list) is kept
// as an option of its own, so the box shows it instead of a blank.
function choiceOptions(editor: ReportEditor): SelectOption[] {
  const options = editor.choices.map((c) => ({ value: c.value, label: c.label }));
  if (editor.value === "" || options.some((o) => o.value === editor.value)) return options;
  return [...options, { value: editor.value, label: editor.label || editor.value }];
}

// True when the key belongs to an open list of this editor: the Select or DatePicker popup (portals), or a box inside the
// form whose list is open.
function inOpenList(target: EventTarget, form: HTMLElement | null): boolean {
  const el = target as HTMLElement;
  if (typeof el.closest !== "function") return false;
  if (el.closest(".sel-popup, .dp-popup") !== null) return true;
  const box = el.closest('[aria-expanded="true"]');
  return box !== null && form !== null && form.contains(box);
}

// The text the editor starts with: the opening key, then the buffered text keys (text and number kinds only).
function startValue(editor: ReportEditor, initialText: string | undefined, buffered: readonly string[]): string {
  const textual = editor.kind === "text" || editor.kind === "number";
  const parts = splitBuffered(buffered);
  if (!textual || (initialText === undefined && parts.text.length === 0)) return editor.value;
  return applyBuffered(initialText ?? editor.value, parts.text);
}

export function CellEditor({
  target,
  editor: initial,
  onSaved,
  onCancel,
  onMove,
  anchor = null,
  initialText,
  buffered = [],
  onSavingChange,
  onSetRange,
}: CellEditorProps) {
  // False once the editor has left the page: a save that answers after that touches no state.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // The editor as last answered: the first one, or the fresh one a clash sent back.
  const [fresh, setFresh] = useState<ReportEditor>(initial);
  const [value, setValueState] = useState(() => startValue(initial, initialText, buffered));
  // The value as of the last change. A pick from an open list changes it before React re-renders, and the save that
  // follows the pick must send the picked value.
  const valueRef = useRef(value);
  // The reason typed for a correction. Kept across a failed save and a clash.
  const [reason, setReason] = useState(initial.reason_text);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // Where a panel editor opens from the cell: left near the table's right edge, up near its bottom edge.
  const [place, setPlace] = useState({ left: false, up: false });
  // A ref, not state: a second Enter in the same tick must see the save already running.
  const busy = useRef(false);
  // An Enter or Tab that the open list handles first; the save runs after the list has picked (bubble phase).
  const pending = useRef<MoveDir | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const reasonRef = useRef<HTMLInputElement | null>(null);
  const played = useRef(false);
  const errorId = useId();
  const options = useMemo(() => (fresh.kind === "choice" ? choiceOptions(fresh) : []), [fresh]);
  const isPanel = isPanelEditor(fresh);

  const setValue = (next: string) => {
    valueRef.current = next;
    setValueState(next);
  };

  // Measured once, when the panel opens (grid_nav.js mountEditor): measuring after the placement classes would flip them.
  useLayoutEffect(() => {
    const form = formRef.current;
    if (!form || !anchor || !isPanelEditor(initial)) return;
    const box = anchor.closest(".ptable") ?? anchor.closest("table");
    if (!box) return;
    const b = box.getBoundingClientRect();
    const r = form.getBoundingClientRect();
    const cell = anchor.getBoundingClientRect();
    setPlace({ left: r.right > b.right, up: r.bottom > b.bottom && cell.bottom - b.top > r.height });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The field takes the focus when the editor opens and again after an error (grid_nav.js focusField). A refused reason
  // takes the focus to the reason box at the moment it is refused (see save). preventScroll: the cursor cell is already
  // in view (ReportTable scrolls it), and a focus that scrolls would move a panel that opens at the table's right edge.
  useEffect(() => {
    if (error === REASON_EMPTY) return;
    formRef.current?.querySelector<HTMLElement>("input:not([type=hidden]), select")?.focus({ preventScroll: true });
  }, [error]);

  async function save(dir: MoveDir) {
    if (busy.current) return;
    if (fresh.reason && reason.trim() === "") {
      // A correction without a reason is refused here: no request. The reason box takes the focus, also when the same
      // message is shown again.
      setError(REASON_EMPTY);
      reasonRef.current?.focus();
      return;
    }
    busy.current = true;
    setSaving(true);
    onSavingChange?.(true);
    setError("");
    let finished = false;
    try {
      const result = await saveEdit(target, {
        value: valueRef.current,
        loaded: fresh.loaded,
        old: fresh.old,
        reason,
        hidden: fresh.hidden,
      });
      if (!alive.current) return; // the editor left the page meanwhile: nothing to show, nothing to close
      if (result.ok) {
        // The editor stays locked: the caller closes it with the saved text.
        finished = true;
        onSaved(result.text);
        onMove(dir);
        return;
      }
      if (result.editor) {
        setFresh(result.editor);
        setValue(result.editor.value);
      }
      setError(result.error || SAVE_FAIL);
    } catch (err) {
      // The typed text and the reason stay as they are: a failed save never loses them.
      if (alive.current) setError(messageOf(err));
    } finally {
      if (!finished) {
        busy.current = false;
        if (alive.current) setSaving(false);
        onSavingChange?.(false);
      }
    }
  }

  // The text Ctrl+Enter sends: a choice gives its option's label (grid_nav.js setMany), a blank choice gives "".
  function rangeText(): string {
    const current = valueRef.current;
    if (fresh.kind === "choice") return options.find((o) => o.value === current)?.label ?? "";
    return current;
  }

  // One key of the editor. A blocked editor only cancels.
  function act(key: EditKey) {
    if (fresh.blocked) {
      onCancel();
      return;
    }
    if (key === "Escape") {
      if (!busy.current) onCancel();
      return;
    }
    void save(key === "Enter" ? "down" : key === "Tab" ? "right" : "left");
  }

  // The keys typed while the editor loaded: the first action key runs once, after the text is in place. A typed text that
  // the editor cannot take (a choice or a date box: startValue ignores it) is not applied, so an Enter or Tab after it does
  // not replay: it would save the stored value as if nothing was typed. Escape still cancels.
  useEffect(() => {
    if (played.current) return;
    played.current = true;
    const parts = splitBuffered(buffered);
    const action = parts.action;
    if (action === null || !EDIT_KEYS.includes(action)) return;
    const textual = initial.kind === "text" || initial.kind === "number";
    const typedIgnored = !textual && (initialText !== undefined || parts.text.length > 0);
    if (typedIgnored && action !== "Escape") return;
    act(action as EditKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Capture phase: the editor's own Enter, Tab and Escape. Inside an open list Enter and Tab are only remembered here
  // and saved after the list has picked (onKeyDownBubble); Escape is left to the list.
  function onKeyDownCapture(e: KeyboardEvent<HTMLFormElement>) {
    if (e.nativeEvent.isComposing) return;
    if (inOpenList(e.target, formRef.current)) {
      if (e.key === "Enter") pending.current = "down";
      else if (e.key === "Tab") pending.current = e.shiftKey ? "left" : "right";
      return;
    }
    if (onSetRange && e.key === "Enter" && (e.ctrlKey || e.metaKey) && !fresh.blocked) {
      e.preventDefault();
      e.stopPropagation();
      if (!busy.current) onSetRange(rangeText());
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      act("Escape");
    } else if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      act("Enter");
    } else if (e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      act(e.shiftKey ? "ShiftTab" : "Tab");
    }
  }

  // Bubble phase: runs after the open list has handled its key, so a pick is already in valueRef.
  function onKeyDownBubble() {
    const dir = pending.current;
    if (dir === null) return;
    pending.current = null;
    if (fresh.blocked) {
      onCancel();
      return;
    }
    void save(dir);
  }

  // The form never submits natively: the keys above are the only way to save.
  const onSubmit = (e: FormEvent<HTMLFormElement>) => e.preventDefault();

  const formClass = ["flex flex-col gap-1", isPanel && "cell-pop", place.left && "pop-left", place.up && "pop-up"]
    .filter(Boolean)
    .join(" ");

  // The error is announced (role alert) and tied to the field it belongs to (aria-invalid, aria-describedby).
  const describe = error ? errorId : undefined;
  const errorLine = error ? (
    <p id={errorId} role="alert" className="text-xs text-red-700" data-cell-error>
      {error}
    </p>
  ) : null;

  if (fresh.blocked) {
    return (
      <form
        ref={formRef}
        data-cell-form
        className={formClass}
        onSubmit={onSubmit}
        onKeyDownCapture={onKeyDownCapture}
        onKeyDown={onKeyDownBubble}
      >
        <p role="alert" className="text-xs text-red-700" data-cell-error>
          {fresh.blocked}
        </p>
      </form>
    );
  }

  // A choice box does not open its list on focus: the list opens by a click or a typed key, as Django's cell editor does
  // (its select is not upgraded on focus). A text box takes the Django field id (id_<name>) so both sides focus one element.
  let field;
  if (fresh.kind === "choice") {
    field = (
      <Select
        name={fresh.name}
        value={value}
        onChange={setValue}
        options={options}
        required={fresh.required}
        disabled={saving}
        ariaLabel={fresh.label}
        invalid={Boolean(error)}
        describedBy={describe}
        openOnFocus={false}
      />
    );
  } else if (fresh.kind === "date") {
    field = (
      <DatePicker
        name={fresh.name}
        value={value}
        onChange={setValue}
        mode="day"
        required={fresh.required}
        disabled={saving}
        ariaLabel={fresh.label}
        invalid={Boolean(error)}
        describedBy={describe}
      />
    );
  } else {
    field = (
      <input
        type="text"
        id={`id_${fresh.name}`}
        name={fresh.name}
        aria-label={fresh.label}
        inputMode={fresh.kind === "number" ? "decimal" : undefined}
        maxLength={fresh.kind === "text" && fresh.maxlength ? fresh.maxlength : undefined}
        required={fresh.required}
        disabled={saving}
        value={value}
        autoComplete="off"
        aria-invalid={error ? true : undefined}
        aria-describedby={describe}
        className={FIELD}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  }

  return (
    <form
      ref={formRef}
      data-cell-form
      className={formClass}
      onSubmit={onSubmit}
      onKeyDownCapture={onKeyDownCapture}
      onKeyDown={onKeyDownBubble}
    >
      {field}
      {fresh.reason ? (
        <input
          ref={reasonRef}
          type="text"
          name="reason"
          aria-label="Засварын шалтгаан"
          placeholder="Засварын шалтгаан"
          required
          maxLength={200}
          disabled={saving}
          value={reason}
          autoComplete="off"
          aria-invalid={error ? true : undefined}
          aria-describedby={describe}
          className={`${REASON} mt-1`}
          onChange={(e) => setReason(e.target.value)}
        />
      ) : null}
      {errorLine}
      {fresh.reason ? (
        <p className="text-xs text-slate-500" title={NOTE_TITLE}>
          {fresh.note}
        </p>
      ) : null}
    </form>
  );
}
