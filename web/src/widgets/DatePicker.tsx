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
import { usePresence } from "../lib/presence";
import { cn } from "../lib/utils";
import { isDisabled, isoOf, monthGrid, MONTHS_MN, normalise, normaliseMonth, WEEKDAYS_MN } from "./dateLogic";

// Calendar picker for a date (mode "day", YYYY-MM-DD) or a month (mode "month", YYYY-MM). Port of
// app/static/js/datepicker.js (docs/UI_RULES.md §2): the same Mongolian labels, weeks from Monday, month and year
// dropdowns, a 12-month grid in month mode, and the footer «Цэвэрлэх» with «Өнөөдөр» (or «Энэ сар»). The markup and
// classes are the datepicker.js ones; the look is in styles/motion.css (its .dp-* rules).
// - The text box keeps the name and the typed value. Typing is normalised on blur (20261014, 2026.10.14 -> 2026-10-14).
//   Text that cannot be read is kept as typed, as datepicker.js does.
// - ArrowDown or a click opens the popup; a day or footer button picks and closes it; Tab closes it; Escape closes it
//   and returns focus to the box. Escape closes only the popup: the popup and the box call preventDefault, and Modal
//   ignores an Escape that was already defaultPrevented. With the popup shut, Escape reaches the Modal.
// - The popup goes into document.body, like Select, and is placed under the box. Its exit uses usePresence.

export type DatePickerMode = "day" | "month";

export interface DatePickerProps {
  name: string;
  value: string;
  onChange: (value: string) => void;
  mode?: DatePickerMode;
  id?: string;
  // Limits as YYYY-MM-DD (day mode) or YYYY-MM (month mode). Days or months outside them are disabled.
  min?: string;
  max?: string;
  required?: boolean;
  disabled?: boolean;
  // Replaces the default box classes (FIELD) on the text box, for a caller's own look. Unset: FIELD.
  className?: string;
  // Sets aria-invalid="true" on the text box. Unset: no attribute.
  invalid?: boolean;
  // The hint in an empty box. Unset: the default for the mode (ЖЖЖЖ-СС-ӨӨ, or ЖЖЖЖ-СС in month mode).
  placeholder?: string;
  // The aria-label of the text box. Unset: no attribute.
  ariaLabel?: string;
  // The id of the <form> the text box posts with (the `form` attribute). Unset: no attribute.
  form?: string;
}

type View = { y: number; m: number };

// The box is styled like the other text fields (Select's FIELD), with room on the right for the calendar button.
const FIELD = "w-full rounded-lg border border-slate-300 py-2 pl-3 pr-9 text-sm";
const FALLBACK_FROM_YEAR = 1940;
const YEARS_AFTER_TODAY = 10;

const pad = (n: number): string => (n < 10 ? "0" : "") + n;
const viewOf = (d: Date): View => ({ y: d.getFullYear(), m: d.getMonth() });
const shiftMonth = (v: View, delta: number): View => viewOf(new Date(v.y, v.m + delta, 1));

// A value that is exactly a real date (or month). Anything else is not selected.
function dayOf(value: string): Date | null {
  if (normalise(value) !== value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function monthOf(value: string): Date | null {
  if (normaliseMonth(value) !== value) return null;
  const [y, m] = value.split("-").map(Number);
  return new Date(y, m - 1, 1);
}

// The month the popup opens on: the value, else today, or the min if today is before it (datepicker.js open()).
function startView(value: string, month: boolean, min: string | undefined): View {
  const sel = month ? monthOf(value) : dayOf(value);
  if (sel) return viewOf(sel);
  const today = new Date();
  const lo = min ? (month ? monthOf(min.slice(0, 7)) : dayOf(min)) : null;
  return viewOf(lo && today < lo ? lo : today);
}

export function DatePicker({
  name,
  value,
  onChange,
  mode = "day",
  id,
  min,
  max,
  required = false,
  disabled = false,
  className,
  ariaLabel,
  invalid,
  placeholder,
  form,
}: DatePickerProps): ReactNode {
  const month = mode === "month";
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>(() => viewOf(new Date()));

  const inputRef = useRef<HTMLInputElement | null>(null);
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  // Set by a pick or a clear; the effect below then fires input and change once the new value is shown.
  const notifyPick = useRef(false);
  const popupRef = useRef<HTMLDivElement | null>(null);

  const presence = usePresence(open);
  const showPopup = open || presence.mounted;
  const setPopup = useCallback(
    (el: HTMLDivElement | null) => {
      popupRef.current = el;
      presence.ref(el);
    },
    [presence.ref],
  );

  // Month mode compares YYYY-MM strings, so the limits are cut to their month.
  const lo = month ? min?.slice(0, 7) : min;
  const hi = month ? max?.slice(0, 7) : max;
  const selected = month ? monthOf(value) : dayOf(value);
  const today = new Date();
  const todayIso = isoOf(today);
  const todayMonth = `${today.getFullYear()}-${pad(today.getMonth() + 1)}`;

  // Opens on the current view; reopening an open picker does nothing (datepicker.js open()).
  const openPicker = () => {
    if (disabled || open) return;
    setView(startView(value, month, min));
    setOpen(true);
  };

  const pick = (next: string) => {
    if (next !== value) {
      notifyPick.current = true;
      onChange(next);
    }
    setOpen(false);
    inputRef.current?.focus();
  };

  // A pick (or a clear) fires input and change on the box, as datepicker.js does, after React has committed the value.
  // Modal's auto-dirty listens for these events.
  useEffect(() => {
    if (!notifyPick.current) return;
    notifyPick.current = false;
    const field = inputRef.current;
    if (!field) return;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  }, [value]);

  // A mousedown outside the popup and the box closes it; so does a resize (datepicker.js close()).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: Event) => {
      const target = e.target as Node;
      if (popupRef.current?.contains(target) || wrapRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDown, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  // Places the popup under the box, or above it when there is no room below (datepicker.js place()).
  const place = useCallback(() => {
    const popup = popupRef.current;
    const anchor = inputRef.current;
    if (!popup || !anchor) return;
    const r = anchor.getBoundingClientRect();
    const h = popup.offsetHeight;
    const w = popup.offsetWidth;
    let top = r.bottom + 4;
    if (top + h > window.innerHeight - 8 && r.top - h - 4 > 8) top = r.top - h - 4;
    popup.style.top = `${top}px`;
    popup.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const onScroll = () => place();
    document.addEventListener("scroll", onScroll, true);
    return () => document.removeEventListener("scroll", onScroll, true);
  }, [open, view, month, place]);

  // Typed text: a readable date moves the popup to its month (datepicker.js input listener).
  const onTyped = (e: ChangeEvent<HTMLInputElement>) => {
    const typed = e.target.value;
    onChange(typed);
    const d = month ? monthOf(typed) : dayOf(typed);
    if (d && open) setView(viewOf(d));
  };

  // On blur the typed text is normalised. Text that cannot be read stays as typed (trimmed, as datepicker.js does).
  const onBlur = () => {
    const trimmed = value.trim();
    const next = (month ? normaliseMonth(trimmed) : normalise(trimmed)) ?? trimmed;
    if (next !== value) {
      // datepicker.js fires input and change after normalising on blur (line 233); same here.
      notifyPick.current = true;
      onChange(next);
    }
  };

  const onInputKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      if (!open) {
        e.preventDefault();
        openPicker();
      }
    } else if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
      }
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  // Escape inside the popup closes it and returns focus to the box. preventDefault keeps Modal open.
  // Tab inside the popup (after a click on an arrow or the month/year select) closes it too, as Tab in the box does.
  // datepicker.js closes on Tab only from the box; closing from the popup as well is a deliberate small fix.
  const onPopupKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Tab") {
      setOpen(false);
      return;
    }
    if (e.key !== "Escape") return;
    e.preventDefault();
    setOpen(false);
    inputRef.current?.focus();
  };

  // The year dropdown and the year arrows cover the limits, or 1940 to ten years after today.
  const fromYear = Math.min(lo ? +lo.slice(0, 4) : FALLBACK_FROM_YEAR, view.y);
  const toYear = Math.max(hi ? +hi.slice(0, 4) : today.getFullYear() + YEARS_AFTER_TODAY, view.y);
  const years: number[] = [];
  for (let y = toYear; y >= fromYear; y -= 1) years.push(y);

  const clear = (
    <button type="button" className="dp-link dp-muted" hidden={required} onClick={() => pick("")}>
      Цэвэрлэх
    </button>
  );

  const dayBody = (
    <>
      <div className="dp-head">
        <button
          type="button"
          className="dp-nav"
          aria-label="Өмнөх сар"
          onClick={() => setView((v) => shiftMonth(v, -1))}
        >
          ‹
        </button>
        <select
          className="dp-select"
          aria-label="Он"
          value={String(view.y)}
          onChange={(e) => setView({ y: +e.target.value, m: view.m })}
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        <select
          className="dp-select"
          aria-label="Сар"
          value={String(view.m)}
          onChange={(e) => setView({ y: view.y, m: +e.target.value })}
        >
          {MONTHS_MN.map((name, i) => (
            <option key={name} value={i}>
              {name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="dp-nav"
          aria-label="Дараах сар"
          onClick={() => setView((v) => shiftMonth(v, 1))}
        >
          ›
        </button>
      </div>
      <div className="dp-grid" role="grid">
        {WEEKDAYS_MN.map((d, i) => (
          <div key={d} className={cn("dp-dow", i > 4 && "dp-weekend")}>
            {d}
          </div>
        ))}
        {monthGrid(view.y, view.m).map((cell, i) => {
          const isSelected = selected !== null && cell.iso === value;
          return (
            <button
              key={cell.iso}
              type="button"
              className={cn(
                "dp-day",
                !cell.inMonth && "dp-other",
                i % 7 > 4 && "dp-weekend",
                cell.iso === todayIso && "dp-today",
                isSelected && "dp-selected",
              )}
              aria-selected={isSelected ? "true" : undefined}
              disabled={isDisabled(cell.iso, lo, hi)}
              onClick={() => pick(cell.iso)}
            >
              {Number(cell.iso.slice(8))}
            </button>
          );
        })}
      </div>
      <div className="dp-foot">
        {clear}
        <button type="button" className="dp-link" onClick={() => pick(todayIso)}>
          Өнөөдөр
        </button>
      </div>
    </>
  );

  const monthBody = (
    <>
      <div className="dp-head">
        <button
          type="button"
          className="dp-nav"
          aria-label="Өмнөх жил"
          disabled={view.y <= fromYear}
          onClick={() => setView({ y: view.y - 1, m: 0 })}
        >
          ‹
        </button>
        <select
          className="dp-select"
          aria-label="Он"
          value={String(view.y)}
          onChange={(e) => setView({ y: +e.target.value, m: 0 })}
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="dp-nav"
          aria-label="Дараах жил"
          disabled={view.y >= toYear}
          onClick={() => setView({ y: view.y + 1, m: 0 })}
        >
          ›
        </button>
      </div>
      <div className="dp-months" role="grid">
        {MONTHS_MN.map((name, i) => {
          const cell = `${view.y}-${pad(i + 1)}`;
          const isSelected = selected !== null && cell === value;
          const isToday = view.y === today.getFullYear() && i === today.getMonth();
          return (
            <button
              key={name}
              type="button"
              className={cn("dp-day dp-month", isToday && "dp-today", isSelected && "dp-selected")}
              aria-selected={isSelected ? "true" : undefined}
              disabled={isDisabled(cell, lo, hi)}
              onClick={() => pick(cell)}
            >
              {name}
            </button>
          );
        })}
      </div>
      <div className="dp-foot">
        {clear}
        <button type="button" className="dp-link" onClick={() => pick(todayMonth)}>
          Энэ сар
        </button>
      </div>
    </>
  );

  return (
    <>
      <span ref={wrapRef} className="dp-wrap">
        <input
          ref={inputRef}
          id={id}
          name={name}
          form={form}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          aria-invalid={invalid || undefined}
          aria-label={ariaLabel}
          className={className ?? FIELD}
          value={value}
          required={required}
          disabled={disabled}
          maxLength={month ? 7 : 10}
          placeholder={placeholder ?? (month ? "ЖЖЖЖ-СС" : "ЖЖЖЖ-СС-ӨӨ")}
          title={month ? "Жил-сар" : "Жил-сар-өдөр"}
          onChange={onTyped}
          onBlur={onBlur}
          onClick={openPicker}
          onKeyDown={onInputKey}
        />
        <button
          type="button"
          tabIndex={-1}
          aria-label="Хуанли нээх"
          className="dp-icon"
          onClick={() => {
            if (open) {
              setOpen(false);
            } else {
              openPicker();
              inputRef.current?.focus();
            }
          }}
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <rect x="3" y="4.5" width="14" height="12" rx="2" />
            <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
          </svg>
        </button>
      </span>
      {showPopup
        ? createPortal(
            <div
              ref={setPopup}
              className="dp-popup"
              role="dialog"
              aria-label={month ? "Сар сонгох" : "Огноо сонгох"}
              data-leaving={presence.leaving ? "" : undefined}
              inert={presence.leaving}
              onKeyDown={onPopupKey}
            >
              {month ? monthBody : dayBody}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
