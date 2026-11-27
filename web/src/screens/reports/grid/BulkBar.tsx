import { useEffect, useRef, type KeyboardEvent } from "react";

// The bar above a report table while a bulk edit runs (grid_nav.js showBar): the message (the counts, or the progress or
// the failure) and its buttons. The first button takes the focus when the bar changes, so Enter takes it. Escape closes it
// through `onEscape` (the hook decides whether it may close now).

export interface BarAction {
  label: string;
  main?: boolean; // the main button (violet)
  run: () => void;
}

export interface BulkBarProps {
  message: string;
  actions: BarAction[];
  onEscape: () => void;
}

// The same classes as grid_nav.js BAR, BTN and BTN_MAIN.
const BAR = "selection-bar mb-1 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm";
const BTN = "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-slate-800 hover:bg-slate-50";
const BTN_MAIN = "rounded-lg bg-violet-700 px-3 py-1.5 text-white hover:bg-violet-800";

export function BulkBar({ message, actions, onEscape }: BulkBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  // The focus moves to the first button whenever the message or the buttons change.
  const changeKey = `${message}|${actions.map((a) => a.label).join("|")}`;
  useEffect(() => {
    barRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [changeKey]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    onEscape();
  };

  return (
    <div ref={barRef} role="status" data-bulk-bar className={BAR} onKeyDown={onKeyDown}>
      <span>{message}</span>
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          onClick={action.run}
          className={action.main ? BTN_MAIN : BTN}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
