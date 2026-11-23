import { useEffect, type ReactNode } from "react";
import type { LogTabsOut } from "../../api/logs";
import { AppLink } from "../../lib/AppLink";
import { useMainWidth } from "../../shell/mainWidth";

// Port of the header row of app/logs/templates/logs/employee.html and _tabs.html: the log pages switch (UI_RULES §7),
// the Excel link and the hidden h1. Classes and the tab labels are copied from the templates. The tabs come from the
// API (`tabs`), so a user sees only the log he may open. The page title and the wide width follow OrdersPage.
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const TITLES = {
  employee: "Ажилтны бүртгэл",
  system: "Системийн бүртгэл",
} as const;

export type LogFrameProps = {
  current: "employee" | "system";
  tabs: LogTabsOut;
  excel: string | null;
  children: ReactNode;
};

export function LogFrame({ current, tabs, excel, children }: LogFrameProps) {
  useMainWidth(MAIN_WIDTH);
  const title = TITLES[current];

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = title + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [title]);

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <nav className="inline-flex shrink-0 overflow-hidden rounded-lg border border-slate-300 text-sm" aria-label="Бүртгэлийн харагдац">
          {tabs.employee && (
            <AppLink
              to="/logs/"
              aria-current={current === "employee" ? "page" : undefined}
              className={`px-3 py-2 ${current === "employee" ? "bg-violet-600 text-white" : "bg-surface text-slate-700 hover:bg-slate-50"}`}
            >
              Ажилтны бүртгэл
            </AppLink>
          )}
          {tabs.system && (
            <AppLink
              to="/logs/system/"
              aria-current={current === "system" ? "page" : undefined}
              className={`px-3 py-2 ${current === "system" ? "bg-violet-600 text-white" : "bg-surface text-slate-700 hover:bg-slate-50"}`}
            >
              Системийн бүртгэл
            </AppLink>
          )}
        </nav>
        {excel !== null && (
          <a
            id="log-excel"
            href={excel}
            className="ml-auto shrink-0 rounded-lg border border-slate-300 bg-surface px-3 py-2 text-sm hover:bg-slate-50"
          >
            Excel
          </a>
        )}
      </div>
      <h1 className="sr-only">{title}</h1>
      {children}
    </>
  );
}
