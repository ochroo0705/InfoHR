import { AppLink } from "../../lib/AppLink";
import { RowMenu } from "../../widgets/RowMenu";

// The leave pages' switch (app/leave/templates/leave/_nav.html): three views as one segmented switch, and the setup
// pages in one «Тохиргоо ▾» menu, shown only to who may change the leave settings (`canSettings`).
// The tabs are all shown; the ones not yet ported are full page loads through AppLink.
// The menu is the shared RowMenu (UI_RULES §2b-2): items close it on click, Escape closes it and returns focus to the
// summary, and an outside click closes it.

export type LeaveView = "list" | "balances" | "calendar";

export interface LeaveNavProps {
  current: LeaveView;
  canSettings: boolean;
}

const TABS: { view: LeaveView; to: string; label: string }[] = [
  { view: "list", to: "/leave/", label: "Бүртгэл" },
  { view: "balances", to: "/leave/balances/", label: "Үлдэгдэл" },
  { view: "calendar", to: "/leave/calendar/", label: "Багийн хуанли" },
];

const SWITCH_CLASS = "inline-flex shrink-0 overflow-hidden rounded-lg border border-slate-300 text-sm";
const TAB_BASE = "px-3 py-2";
const TAB_ON = "bg-violet-600 text-white";
const TAB_OFF = "bg-surface text-slate-700 hover:bg-slate-50";
const MENU_LINK_CLASS = "block rounded px-3 py-2 text-sm hover:bg-slate-50";

export function LeaveNav({ current, canSettings }: LeaveNavProps) {
  return (
    <>
      <nav className={SWITCH_CLASS} aria-label="Чөлөө, амралтын харагдац">
        {TABS.map((tab) => {
          const on = tab.view === current;
          return (
            <AppLink
              key={tab.view}
              to={tab.to}
              aria-current={on ? "page" : undefined}
              className={`${TAB_BASE} ${on ? TAB_ON : TAB_OFF}`}
            >
              {tab.label}
            </AppLink>
          );
        })}
      </nav>
      {canSettings && (
        <RowMenu summary="Тохиргоо ▾">
          <AppLink to="/leave/holidays/" className={MENU_LINK_CLASS}>
            Баярын өдрүүд
          </AppLink>
          <AppLink to="/leave/settings/" className={MENU_LINK_CLASS}>
            Амралтын төрөл, тохиргоо
          </AppLink>
        </RowMenu>
      )}
    </>
  );
}
