import type { RecruitStageItemOut } from "../../api/recruitment";
import { cn } from "../../lib/utils";

// The stage bar of a vacancy page (app/recruitment/templates/recruitment/_stage_bar.html): one pill per stage with its
// count in grey. The active one is violet with aria-current="true". The page keeps the choice in the address; a pick
// only reports the key (the Django bar swaps the list; here the page does).

export interface StageBarProps {
  items: RecruitStageItemOut[];
  active: string;
  onPick: (key: string) => void;
}

export function StageBar({ items, active, onPick }: StageBarProps) {
  return (
    <nav className="flex flex-wrap gap-1.5 text-sm" aria-label="Шат">
      {items.map((item) => {
        const current = item.key === active;
        return (
          <button
            key={item.key}
            type="button"
            aria-current={current ? "true" : undefined}
            onClick={() => onPick(item.key)}
            className={cn(
              "whitespace-nowrap rounded-full border px-3 py-1.5",
              current ? "border-violet-600 bg-violet-600 text-white" : "border-slate-300 bg-surface text-slate-700 hover:bg-slate-50",
            )}
          >
            {item.label}
            <span className={cn("ml-1", current ? "text-white/80" : "text-slate-500")}>{item.count}</span>
          </button>
        );
      })}
    </nav>
  );
}
