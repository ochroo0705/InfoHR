import type { TabBadge } from "./hireTabLogic";

export type HireTabItem = { key: string; label: string };

// The tab classes of `add.html`. The active look is the one its showTab() script sets: the base, plus the violet pair
// and font-medium; the inactive look keeps text-slate-600.
const TAB_BASE = "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100";
const TAB_ACTIVE = "bg-violet-50 text-violet-700 font-medium";
const TAB_INACTIVE = "text-slate-600";
const BADGE_BASE = "ml-auto rounded-full px-1.5 text-xs font-semibold";

// The badge tone classes of add.html's badges(): red with white text for errors, emerald text when done.
function badgeClass(tone: TabBadge["tone"]): string {
  if (tone === "error") return `${BADGE_BASE} bg-red-600 text-white`;
  if (tone === "done") return `${BADGE_BASE} text-emerald-700`;
  return BADGE_BASE;
}

// The tab strip of the hire page: a tablist with one button per tab that is passed in. The caller decides which tabs
// exist (the salary tab is absent without the salary right); this only draws them. `badges` is keyed by tab key.
export function HireTabs({
  tabs,
  active,
  badges,
  onSelect,
}: {
  tabs: HireTabItem[];
  active: string;
  badges: Record<string, TabBadge>;
  onSelect: (key: string) => void;
}) {
  return (
    <nav
      role="tablist"
      aria-label="Табууд"
      className="flex gap-1 overflow-x-auto md:w-52 md:shrink-0 md:flex-col md:overflow-visible"
    >
      {tabs.map((tab) => {
        const on = tab.key === active;
        const badge = badges[tab.key] ?? { text: "", tone: "none" as const };
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            data-tab-btn={tab.key}
            aria-selected={on ? "true" : "false"}
            onClick={() => onSelect(tab.key)}
            className={`${TAB_BASE} ${on ? TAB_ACTIVE : TAB_INACTIVE}`}
          >
            {tab.label}{" "}
            <span data-badge={tab.key} className={badgeClass(badge.tone)}>
              {badge.text}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
