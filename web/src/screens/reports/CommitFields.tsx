import { useRef, useState, type FocusEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { DatePicker } from "../../widgets/DatePicker";

// The commit-on-leave boxes of the report filter bar. The template's date and number boxes send their value on the
// change event, which a browser fires on commit: blur, Enter, or a day picked from the calendar. Typing alone sends
// nothing (datepicker.js; _filters.html). A box keeps the typed text as a draft and calls onCommit once, on one of
// those three. The draft is reset to `value` whenever `value` or `syncKey` (the address) changes.

const POPUP_CLASS = "dp-popup";
const PICK_SELECTOR = "button.dp-day, button.dp-link";

function inPopup(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(`.${POPUP_CLASS}`) !== null;
}

// A calendar button that picks a value (a day or month, «Өнөөдөр», «Энэ сар», «Цэвэрлэх»). The navigation buttons
// (‹ ›) and the year and month selects inside the calendar are not picks.
function isPick(target: EventTarget | null): boolean {
  return inPopup(target) && target instanceof Element && target.closest(PICK_SELECTOR) !== null;
}

// The shown text, plus a ref copy that the handlers read within the same event (state is not re-rendered yet there).
function useDraft(value: string, syncKey: string) {
  const key = `${value}\u0000${syncKey}`;
  const [synced, setSynced] = useState(key);
  const [draft, setDraft] = useState(value);
  const draftRef = useRef(value);
  if (synced !== key) {
    setSynced(key);
    setDraft(value);
    draftRef.current = value;
  }
  const typed = (next: string) => {
    draftRef.current = next;
    setDraft(next);
  };
  return { draft, draftRef, typed };
}

export interface DateFieldProps {
  name: string;
  value: string; // YYYY-MM-DD, or "" for no date
  syncKey: string; // the address; a change of it resets the draft
  ariaLabel: string;
  placeholder: string;
  className: string; // the text box's classes (the template's)
  onCommit: (value: string) => void;
}

// A date box: the shared DatePicker (not a native date input), committed on blur, Enter or a pick.
export function DateField({
  name,
  value,
  syncKey,
  ariaLabel,
  placeholder,
  className,
  onCommit,
}: DateFieldProps): ReactNode {
  const { draft, draftRef, typed } = useDraft(value, syncKey);
  // A press on a pick button moves focus out of the box; that is not a leave, the pick's own click commits instead.
  // Any other press in the calendar (a nav arrow, a year or month select) is a leave like any other: the typed date
  // commits on the blur.
  const pressedPick = useRef(false);
  const commit = () => {
    if (draftRef.current !== value) onCommit(draftRef.current);
  };
  return (
    <span
      className="contents"
      onMouseDown={(e) => {
        pressedPick.current = isPick(e.target);
      }}
      onBlur={(e: FocusEvent<HTMLSpanElement>) => {
        if (!(e.target instanceof HTMLInputElement)) return;
        const toPick = pressedPick.current || isPick(e.relatedTarget);
        pressedPick.current = false;
        if (toPick) return;
        commit();
      }}
      onKeyDown={(e: KeyboardEvent<HTMLSpanElement>) => {
        if (e.key !== "Enter" || !(e.target instanceof HTMLInputElement)) return;
        e.preventDefault();
        commit();
      }}
      onClick={(e: MouseEvent<HTMLSpanElement>) => {
        // Runs after the calendar's own pick (or «Цэвэрлэх» / «Өнөөдөр»), which has already set the draft.
        if (!isPick(e.target)) return;
        pressedPick.current = false;
        commit();
      }}
    >
      <DatePicker
        name={name}
        value={draft}
        onChange={typed}
        ariaLabel={ariaLabel}
        placeholder={placeholder}
        className={className}
      />
    </span>
  );
}

export interface NumberFieldProps {
  name: string;
  value: string;
  syncKey: string;
  ariaLabel: string;
  placeholder?: string;
  min?: number;
  max?: number;
  className: string;
  dataFilter?: string; // the template's data-filter on the box itself (the year box has one)
  onCommit: (value: string) => void;
}

// A number box, committed on blur or Enter (the template's change event for a number box).
export function NumberField({
  name,
  value,
  syncKey,
  ariaLabel,
  placeholder,
  min,
  max,
  className,
  dataFilter,
  onCommit,
}: NumberFieldProps): ReactNode {
  const { draft, draftRef, typed } = useDraft(value, syncKey);
  const commit = () => {
    if (draftRef.current !== value) onCommit(draftRef.current);
  };
  return (
    <input
      type="number"
      name={name}
      data-filter={dataFilter}
      min={min}
      max={max}
      placeholder={placeholder}
      aria-label={ariaLabel}
      value={draft}
      className={className}
      onChange={(e) => typed(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        commit();
      }}
    />
  );
}
