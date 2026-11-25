import { cn } from "../../lib/utils";

// The budget line of a vacancy (app/recruitment/templates/recruitment/_slot_line.html). Advisory only: the numbers in a
// slate box, and the amber box when there is a warning. Nothing is drawn for null (no line to show).

export interface SlotLineProps {
  line: { numbers: string; warning: string } | null;
}

export function SlotLine({ line }: SlotLineProps) {
  if (!line) return null;
  return (
    <div className={cn("rounded-lg px-3 py-2 text-sm", line.warning ? "bg-amber-50 text-amber-800" : "bg-slate-50 text-slate-700")}>
      {line.numbers ? `Орон тоо: ${line.numbers}` : null}
      {line.numbers && line.warning ? " — " : null}
      {line.warning}
    </div>
  );
}
