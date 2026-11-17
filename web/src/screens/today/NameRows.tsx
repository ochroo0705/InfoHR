import type { ReactNode } from "react";

// The name link inside a row. Its ::after covers the whole row, so a click anywhere on the row opens the person.
export const NAME_LINK_CLASS =
  "text-violet-700 after:absolute after:inset-0 after:content-[''] focus-visible:outline-none";

export type NameRow = { id: string | number; left: ReactNode; right: string };

export type NameRowsProps = {
  rows: NameRow[];
  // Shown when there are no rows, e.g. «Энэ өдөр чөлөөтэй хүн алга.»
  empty: string;
  emptyClass?: string;
  // Class of the right-hand text. The away list passes "text-right text-slate-500" (_today_away.html).
  rightClass?: string;
};

// The row list of the Today page panels (away, upcoming, hires). `left` holds the name link (use NAME_LINK_CLASS).
export function NameRows({
  rows,
  empty,
  emptyClass = "text-sm text-slate-400",
  rightClass = "text-slate-500",
}: NameRowsProps) {
  if (rows.length === 0) {
    return <p className={emptyClass}>{empty}</p>;
  }
  return (
    <>
      {rows.map((row) => (
        <div
          key={row.id}
          className="relative -mx-2 flex items-baseline justify-between gap-3 rounded-lg border-b border-slate-100 px-2 py-1.5 text-sm transition-colors hover:bg-violet-50 focus-within:bg-violet-50 last:border-0"
        >
          <span>{row.left}</span>
          <span className={rightClass}>{row.right}</span>
        </div>
      ))}
    </>
  );
}
