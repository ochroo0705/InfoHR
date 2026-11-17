import { useRef, type ChangeEvent, type InputHTMLAttributes, type KeyboardEvent } from "react";
import { cn } from "../lib/utils";
import { caretAfter, format } from "./money";

// Money box (port of app/static/js/money.js; docs/UI_RULES.md §2b). A text box, never a number box: digits are grouped
// by commas as the user types, and the server ignores the commas. The caret stays after the same digit it was after.
// - The native input event of the user's typing reaches Modal's auto-dirty as it is; no extra event is needed here.
//   Only a value set by script (not by typing) would need one, and this box never sets its value that way.
// - Backspace just after a comma, or Delete just before one, removes the digit beyond it (money.js keydown rule).

export interface MoneyInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  name: string;
  value: string;
  onChange: (value: string) => void;
}

export function MoneyInput({ name, value, onChange, onKeyDown, className, ...rest }: MoneyInputProps) {
  const field = useRef<HTMLInputElement>(null);

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const el = e.currentTarget;
    const raw = el.value;
    const next = format(raw);
    // money.js line 20: nothing to reformat, so the caret is left where it is.
    if (next === raw) {
      onChange(next);
      return;
    }
    const caret = el.selectionStart;
    el.value = next;
    if (caret != null && document.activeElement === el) {
      const pos = caretAfter(raw, caret, next);
      el.setSelectionRange(pos, pos);
    }
    onChange(next);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const el = e.currentTarget;
    const at = el.selectionStart;
    if (at != null && at === el.selectionEnd) {
      if (e.key === "Backspace" && el.value.charAt(at - 1) === ",") el.setSelectionRange(at - 1, at - 1);
      if (e.key === "Delete" && el.value.charAt(at) === ",") el.setSelectionRange(at + 1, at + 1);
    }
    onKeyDown?.(e);
  };

  return (
    <input
      ref={field}
      type="text"
      name={name}
      value={format(value)}
      inputMode="decimal"
      autoComplete="off"
      data-money=""
      className={cn("w-full rounded-lg border border-slate-300 px-3 py-2 text-sm", className)}
      onChange={handleChange}
      onKeyDown={handleKeyDown}
      {...rest}
    />
  );
}
