import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { getCsrf } from "../api/client";
import { usePresence } from "../lib/presence";
import { cn } from "../lib/utils";

// Dropdown for a choice (port of app/static/js/select.js; docs/UI_RULES.md §2 and §2a). The markup, classes and texts
// are copied from select.js, and the look is in styles/motion.css (its .sel-* rules).
// - Click list: any select that is not a typing box (see below). The real <select> (name, required, value) stays visible and
//   opens a popup list on mousedown or on ArrowDown/ArrowUp/Enter/Space/F4. Keys in the list: arrows, Enter, Escape
//   (back to the select), Tab. The active option scrolls into view. Open uses hr-pop-in; close waits for usePresence.
// - Typing box (select.js isCombo): addUrl, search on, or 8 or more options. search off never gives one; addModal
//   alone does not. The box is also the search; the «Хайх…» hint shows only on focus. The add line «+ "text" нэмэх»
//   shows only when addUrl AND canAdd are set (select.js canAdd: data-add-url plus data-can-add-lists). Callers pass
//   canAdd = useMeta().data.user.perms.includes("lists.manage_lists"): the server sends the perm, the frontend does not
//   derive it. addUrl POSTs {name} and picks the reply {value, label}; addModal (with addUrl and canAdd) calls
//   onAddModal(text) instead. An exact match (case-insensitive) hides the add line. The duplicate-name note shows only
//   after an add whose reply has existed: true; that entry is then picked.
// - Touch devices (pointer: coarse) get a native <select>, except a typing box that has addUrl.
// - The chosen value is always in a hidden field named `name`, so a plain form still submits it.
// - Escape with the list open calls preventDefault in its keydown handler, so Modal (which ignores a defaultPrevented
//   Escape) closes only the list.

export type SelectOption = { value: string; label: string; disabled?: boolean };

export interface SelectProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  id?: string;
  required?: boolean;
  disabled?: boolean;
  // true forces the typing box; false (select.js "off") never gives one, even with addUrl. Default: by addUrl or count.
  search?: boolean;
  // POST {name} here to add an entry on the spot. The reply {value, label} is added to the list and picked.
  addUrl?: string;
  // The add line shows only with addUrl AND canAdd. Pass canAdd = useMeta().data.user.perms.includes("lists.manage_lists").
  canAdd?: boolean;
  // Add through a pop-up instead (needs addUrl and canAdd too): onAddModal(text) is called with the typed text.
  addModal?: boolean;
  onAddModal?: (text: string) => void;
  // The hint shown while the typing box has focus.
  placeholder?: string;
  // Replaces the default box classes (FIELD) on the visible box, for a caller's own look (Soft's soft box). Unset: FIELD.
  className?: string;
  // Sets aria-invalid="true" on the visible box. Unset: no attribute.
  invalid?: boolean;
  // The id of the <form> the box posts with (the `form` attribute). Set on the visible box, the native select and the
  // hidden field, so Enter in a typing box and the posted value both belong to that form. Unset: no attribute.
  form?: string;
}

const SEARCH_FROM = 8;
const HINT = "Хайх…";
const EMPTY_TEXT = "Олдсонгүй";
const DUP_NOTE = "Ийм бичлэг аль хэдийн бүртгэлтэй байсан тул түүнийг сонголоо.";
const NET_ERROR = "Сүлжээний алдаа гарлаа.";
const SERVER_ERROR = "Серверийн алдаа гарлаа. Дахин оролдоно уу.";
const FORBIDDEN_ERROR = "Нэмэх эрхгүй.";
const FIELD = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
const OPEN_KEYS = ["ArrowDown", "ArrowUp", "Enter", " ", "F4"];

type AddReply = {
  value?: string | number;
  label?: string;
  existed?: boolean;
  error?: string;
  field_errors?: Record<string, string[]>;
};
type Row = { kind: "option"; option: SelectOption; index: number } | { kind: "add" };
type Note = { text: string; error: boolean };

const lower = (s: string): string => s.toLocaleLowerCase("mn");

function isCoarse(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
}

// Keeps a new entry in name order, as select.js does: before the first named option that sorts after it.
function insertSorted(list: SelectOption[], entry: SelectOption): SelectOption[] {
  const at = list.findIndex((o) => o.value !== "" && o.label.localeCompare(entry.label) > 0);
  return at < 0 ? [...list, entry] : [...list.slice(0, at), entry, ...list.slice(at)];
}

export function Select(props: SelectProps): ReactNode {
  const [coarse] = useState(isCoarse);
  if (coarse && !props.addUrl) return <NativeSelect {...props} />;
  return <PickerSelect {...props} />;
}

function NativeSelect({
  id,
  name,
  value,
  onChange,
  options,
  required = false,
  disabled = false,
  className,
  invalid,
  form,
}: SelectProps) {
  return (
    <select
      id={id}
      name={name}
      form={form}
      value={value}
      required={required}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      className={className ?? FIELD}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function PickerSelect({
  id,
  name,
  value,
  onChange,
  options,
  required = false,
  disabled = false,
  search,
  addUrl,
  canAdd = false,
  addModal = false,
  onAddModal,
  placeholder = HINT,
  className,
  invalid,
  form,
}: SelectProps) {
  // select.js isCombo: addUrl, or search on, or 8+ options; search off never. addModal alone does not count.
  const combo = search !== false && (Boolean(addUrl) || search === true || options.length >= SEARCH_FROM);
  // The add line needs addUrl and canAdd (select.js canAdd()). addModal only changes how the text is added.
  const addAllowed = Boolean(addUrl) && canAdd;

  // Entries added on the spot. They join the options until the parent's options include them.
  const [added, setAdded] = useState<SelectOption[]>([]);
  const all = added.reduce<SelectOption[]>(
    (list, entry) => (list.some((o) => o.value === entry.value) ? list : insertSorted(list, entry)),
    options,
  );

  const [open, setOpen] = useState(false);
  // typed: the box holds text the user typed (the list is filtered by it). text null: the box shows the chosen label.
  const [typed, setTyped] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [focused, setFocused] = useState(false);
  const [flash, setFlash] = useState<Note | null>(null);

  const presence = usePresence(open);
  const showPopup = open || presence.mounted;

  const triggerRef = useRef<HTMLElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef<(HTMLElement | null)[]>([]);
  const justFocused = useRef(false);
  const focusTimer = useRef<number | null>(null);
  const lastRows = useRef<Row[]>([]);

  const setTrigger = useCallback((el: HTMLElement | null) => {
    triggerRef.current = el;
  }, []);
  // The form field carries the value: the real select (click list) or the hidden field (typing box). A pick fires input
  // and change on it (select.js fires them on the select after a pick). A change from outside does not.
  const formField = useRef<HTMLElement | null>(null);
  const setFormField = useCallback((el: HTMLElement | null) => {
    formField.current = el;
  }, []);
  const setTriggerAndField = useCallback(
    (el: HTMLElement | null) => {
      setTrigger(el);
      setFormField(el);
    },
    [setTrigger, setFormField],
  );
  const notifyPick = useRef(false);

  const setPopup = useCallback(
    (el: HTMLDivElement | null) => {
      popupRef.current = el;
      presence.ref(el);
    },
    [presence.ref],
  );

  const selected = all.find((o) => o.value === value);
  const shownLabel = selected && selected.value !== "" ? selected.label : "";
  const current = text ?? shownLabel;

  const query = typed ? lower((text ?? "").trim()) : "";
  const exact = query !== "" && all.some((o) => lower(o.label.trim()) === query);
  const addVisible = addAllowed && query !== "" && !exact;

  const rows: Row[] = [];
  all.forEach((option, index) => {
    if (!query || lower(option.label.trim()).includes(query)) rows.push({ kind: "option", option, index });
  });
  if (addVisible) rows.push({ kind: "add" });
  // While the list plays its exit, it keeps the rows it had, so it does not jump back to the full list (kept by an effect).
  const shown = open ? rows : lastRows.current;
  const anyRow = shown.length > 0;

  // Only an add reply with existed: true sets a note (see applyEntry); typing never does.
  const note: Note | null = flash;

  // The rows of the last open render, kept for the exit. Written in an effect, not during render.
  useEffect(() => {
    if (open) lastRows.current = rows;
  });

  // Clears a pending focus timer when the box unmounts.
  useEffect(
    () => () => {
      if (focusTimer.current !== null) window.clearTimeout(focusTimer.current);
    },
    [],
  );

  // Position the list under the anchor (select.js place()). It also follows resizes and scrolls outside the list.
  const place = useCallback(() => {
    const popup = popupRef.current;
    const anchor = triggerRef.current;
    if (!popup || !anchor) return;
    const r = anchor.getBoundingClientRect();
    popup.style.minWidth = `${r.width}px`;
    const below = window.innerHeight - r.bottom;
    const h = popup.offsetHeight;
    const top = below < h + 8 && r.top > below ? r.top - h - 4 : r.bottom + 4;
    popup.style.top = `${Math.max(4, top)}px`;
    popup.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - popup.offsetWidth - 4))}px`;
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const onScroll = (e: Event) => {
      if (!popupRef.current?.contains(e.target as Node)) place();
    };
    window.addEventListener("resize", place);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("resize", place);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [open, place]);

  // A click-list opens with its focus on the list, so the keys reach it.
  useEffect(() => {
    if (open && !combo) popupRef.current?.focus();
  }, [open, combo]);

  useEffect(() => {
    if (open) rowRefs.current[active]?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  const close = useCallback(() => {
    setOpen(false);
    setTyped(false);
    setText(null);
  }, []);

  // A mousedown outside the list and its anchor closes the list.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: Event) => {
      const target = e.target as Node;
      if (popupRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      close();
    };
    document.addEventListener("mousedown", onDown, true);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [open, close]);

  const openList = () => {
    if (disabled) return;
    setTyped(false);
    const idx = all.findIndex((o) => o.value === value);
    setActive(idx < 0 ? 0 : idx);
    setOpen(true);
  };

  const moveActive = (delta: number) => setActive((a) => Math.max(0, Math.min(a + delta, rows.length - 1)));

  // Sets a value the user picked or cleared. Only a real change is announced (the effect below).
  const pickValue = (next: string) => {
    if (next === value) return;
    notifyPick.current = true;
    onChange(next);
  };

  // A pick fires input and change on the form field, after React has committed the new value, so React's own
  // onChange sees no new value from them. Modal's auto-dirty listens for these events.
  useEffect(() => {
    if (!notifyPick.current) return;
    notifyPick.current = false;
    const field = formField.current;
    if (!field) return;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  }, [value]);

  const choose = (option: SelectOption) => {
    pickValue(option.value);
    close();
    setFlash(null);
    if (!combo) triggerRef.current?.focus();
  };

  // A typing box left without a pick: an emptied box clears an optional select that has an empty entry.
  const leave = () => {
    const emptyOption = all.find((o) => o.value === "");
    if (!current.trim() && !required && emptyOption && value !== "") pickValue("");
    setText(null);
  };

  const applyEntry = (reply: AddReply) => {
    const entry: SelectOption = { value: String(reply.value), label: String(reply.label) };
    setAdded((prev) =>
      prev.some((o) => o.value === entry.value) || options.some((o) => o.value === entry.value) ? prev : [...prev, entry],
    );
    pickValue(entry.value);
    if (reply.existed) setFlash({ text: DUP_NOTE, error: false });
  };

  const postName = async (url: string, name: string) => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrf(), "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch {
      setFlash({ text: NET_ERROR, error: true });
      return;
    }
    const reply = (await res.json().catch(() => null)) as AddReply | null;
    if (res.ok && reply && reply.value !== undefined && reply.label !== undefined) {
      applyEntry(reply);
      return;
    }
    const message =
      reply?.field_errors?.name?.[0] ?? reply?.error ?? (res.status === 403 ? FORBIDDEN_ERROR : SERVER_ERROR);
    setFlash({ text: message, error: true });
  };

  const addTyped = () => {
    const name = (text ?? "").trim();
    close();
    if (!name) return;
    if (addModal && onAddModal) onAddModal(name);
    else if (addUrl) void postName(addUrl, name);
  };

  // The keys of an open list: the click list (its own focus) and the typing box (its own focus) share them.
  const onListKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (combo && !current.trim()) {
        close();
        leave();
        return;
      }
      const row = rows[active];
      if (!row) return;
      if (row.kind === "add") addTyped();
      else choose(row.option);
    } else if (e.key === "Escape") {
      // Handled here, so Modal (which ignores a defaultPrevented Escape) closes only the list.
      e.preventDefault();
      close();
      if (!combo) triggerRef.current?.focus();
    } else if (e.key === "Tab") {
      close();
      if (!combo) triggerRef.current?.focus();
    }
  };

  const hiddenField = (
    <input ref={setFormField} type="hidden" id={id} name={name} form={form} value={value} readOnly />
  );

  const popup = showPopup
    ? createPortal(
        <div
          ref={setPopup}
          role="listbox"
          tabIndex={-1}
          className="sel-popup"
          data-leaving={presence.leaving ? "" : undefined}
          inert={presence.leaving}
          onKeyDown={combo ? undefined : onListKey}
          onMouseDown={(e) => {
            // Keeps focus where it was (the typing box, or the button); a click on an item still picks it.
            if (!(e.target instanceof HTMLInputElement)) e.preventDefault();
          }}
        >
          <div className="sel-list">
            {shown.map((row, pos) => {
              if (row.kind === "add") {
                return (
                  <button
                    key="add"
                    type="button"
                    role="option"
                    tabIndex={-1}
                    ref={(el) => {
                      rowRefs.current[pos] = el;
                    }}
                    className={cn("sel-item sel-add", pos === active && "sel-active")}
                    onMouseMove={() => setActive(pos)}
                    onClick={addTyped}
                  >
                    {`+ "${(text ?? "").trim()}" нэмэх`}
                  </button>
                );
              }
              const { option, index } = row;
              const isSelected = option.value === value;
              const blank = !option.label.trim();
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  tabIndex={-1}
                  data-index={index}
                  disabled={option.disabled}
                  ref={(el) => {
                    rowRefs.current[pos] = el;
                  }}
                  className={cn(
                    "sel-item",
                    isSelected && "sel-selected",
                    blank && "sel-blank",
                    pos === active && "sel-active",
                  )}
                  onMouseMove={() => setActive(pos)}
                  onClick={() => choose(option)}
                >
                  {blank ? "—" : option.label}
                </button>
              );
            })}
            {anyRow ? null : <div className="sel-empty">{EMPTY_TEXT}</div>}
          </div>
        </div>,
        document.body,
      )
    : null;

  if (combo) {
    return (
      <>
        <input
          ref={setTrigger}
          // select.js names the typing box «sel-» + the select's id; the select keeps the plain id (hiddenField).
          id={id ? `sel-${id}` : undefined}
          form={form}
          type="text"
          role="combobox"
          aria-invalid={invalid || undefined}
          className={cn(className ?? FIELD, "sel-combo")}
          autoComplete="off"
          spellCheck={false}
          value={current}
          placeholder={focused ? placeholder : undefined}
          aria-expanded={open}
          aria-autocomplete="list"
          data-required={required ? "1" : undefined}
          required={required}
          disabled={disabled}
          onFocus={() => {
            setFocused(true);
            setFlash(null);
            openList();
            justFocused.current = true;
            if (focusTimer.current !== null) window.clearTimeout(focusTimer.current);
            focusTimer.current = window.setTimeout(() => {
              focusTimer.current = null;
              if (triggerRef.current instanceof HTMLInputElement) triggerRef.current.select();
            }, 0);
          }}
          onMouseUp={(e) => {
            // The first click after focus must not deselect the text that focus selected.
            if (justFocused.current) {
              e.preventDefault();
              justFocused.current = false;
            }
          }}
          onClick={() => {
            if (!open) openList();
          }}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            if (!open) openList();
            setFlash(null);
            setText(e.target.value);
            setTyped(true);
            // The filter changed: the first row is the active one again (select.js filter()).
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (!open) {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                openList();
              }
              return;
            }
            onListKey(e);
          }}
          onBlur={() => {
            setFocused(false);
            justFocused.current = false;
            close();
            leave();
          }}
        />
        {note ? <small className={cn("sel-note", note.error && "sel-error")}>{note.text}</small> : null}
        {hiddenField}
        {popup}
      </>
    );
  }

  // The real select is the form field (name, required, value) and stays visible, as in select.js. Its mousedown and
  // the open keys show the popup list instead of the native menu; a pick sets the select's value and fires change.
  return (
    <>
      <select
        ref={setTriggerAndField}
        id={id}
        name={name}
        form={form}
        value={value}
        required={required}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-invalid={invalid || undefined}
        className={className ?? FIELD}
        onChange={(e) => {
          // A change event with the value already shown is our own notify (see the effect), not a pick.
          if (e.target.value !== value) onChange(e.target.value);
        }}
        onMouseDown={(e) => {
          if (e.button !== 0 || disabled) return;
          e.preventDefault();
          e.currentTarget.focus();
          if (open) close();
          else openList();
        }}
        onKeyDown={(e) => {
          if (!open && OPEN_KEYS.includes(e.key)) {
            e.preventDefault();
            openList();
          }
        }}
      >
        {/* A value with no matching option (e.g. "" with no empty entry) shows blank, not the first option. */}
        {all.some((o) => o.value === value) ? null : (
          <option value={value} disabled hidden>
            {""}
          </option>
        )}
        {all.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      {popup}
    </>
  );
}
