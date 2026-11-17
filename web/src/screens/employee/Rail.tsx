import type { EmployeeHeadOut } from "../../api/employee";
import { AppLink } from "../../lib/AppLink";
import { photoSrc } from "../../lib/photo";
import {
  DepartmentIcon,
  HireDateIcon,
  ManagerIcon,
  PersonalIcon,
  PhoneIcon,
  PositionIcon,
  SalaryIcon,
  WorkIcon,
} from "./icons";

export type EmployeeHead = EmployeeHeadOut;

// The rail link classes of `_rail.html`. The active look is the one detail.html's scroll-spy script sets (.rtab).
function rtabClass(on: boolean, gap: boolean): string {
  const base = `rtab${gap ? " mt-0.5" : ""} flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100`;
  return on ? `${base} bg-violet-50 text-violet-700 font-semibold` : base;
}

// The left rail of the employee page (lg and up, `_rail.html`): the facts card and the section links. `active` is the
// id of the section in view (set by the scroll-spy, Task 9). The rail never decides rights: it filters by `can`.
export function Rail({ head, active }: { head: EmployeeHead; active?: string }) {
  const { facts, can } = head;
  const dash = (value: string) => value || "—";

  return (
    <aside
      id="emp-rail"
      className="sticky top-20 hidden max-h-[calc(100vh-6rem)] w-60 shrink-0 self-start overflow-y-auto overscroll-contain lg:block"
      aria-label="Ажилтны хэсгүүд"
    >
      <div className="sticky top-0 z-10 bg-slate-50 pb-1">
        <AppLink to="/employees/" className="mb-1 block px-3 text-sm text-slate-500 hover:text-violet-700">
          ← Ажилтнууд
        </AppLink>
        <div id="rail-who" className="mb-2 rounded-xl border border-slate-200 bg-surface p-3 shadow-sm">
          <span className="flex items-center gap-3">
            {head.photo_url ? (
              <img
                src={photoSrc(head.photo_url)}
                alt=""
                className="h-10 w-10 shrink-0 rounded-xl object-cover outline-1 -outline-offset-1 outline-black/10"
              />
            ) : (
              <span
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-50 text-lg font-bold text-violet-700"
                aria-hidden="true"
              >
                {head.given_initial}
              </span>
            )}
            <span className="min-w-0">
              <span className="block text-sm leading-snug font-semibold text-slate-900 [text-wrap:balance]">
                {head.full_name}
              </span>
            </span>
          </span>
          <dl
            id="rail-facts"
            className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-2 border-t border-slate-100 pt-3 text-xs leading-snug"
          >
            <dt className="pt-px text-slate-400">
              <PositionIcon />
              <span className="sr-only">Албан тушаал</span>
            </dt>
            <dd className="min-w-0 break-words text-slate-800">{dash(facts.position)}</dd>
            <dt className="pt-px text-slate-400">
              <DepartmentIcon />
              <span className="sr-only">Хэлтэс</span>
            </dt>
            <dd className="min-w-0 break-words text-slate-800">{dash(facts.department)}</dd>
            <dt className="pt-px text-slate-400">
              <ManagerIcon />
              <span className="sr-only">Шууд удирдлага</span>
            </dt>
            <dd className="min-w-0 break-words text-slate-800">{dash(facts.manager)}</dd>
            <dt className="pt-px text-slate-400">
              <HireDateIcon />
              <span className="sr-only">Ажилд орсон</span>
            </dt>
            <dd className="min-w-0 break-words text-slate-800">
              {facts.first_hire_date ? <span className="tabular-nums">{facts.first_hire_date}</span> : "—"}
            </dd>
            <dt className="pt-px text-slate-400">
              <PhoneIcon />
              <span className="sr-only">Утас</span>
            </dt>
            <dd className="min-w-0 break-words text-slate-800">
              {facts.work_phone ? (
                <AppLink to={`tel:${facts.work_phone}`} className="tabular-nums hover:text-violet-700 hover:underline">
                  {facts.work_phone}
                </AppLink>
              ) : (
                "—"
              )}
            </dd>
          </dl>
          {head.leave_left !== null && (
            <p className="mt-3 flex items-baseline justify-between rounded-lg bg-slate-100 px-3 py-2">
              <span className="text-xs text-slate-600">Үлдсэн амралт</span>
              <span className="text-lg leading-none font-semibold text-slate-900 tabular-nums">
                {head.leave_left}
                <span className="ml-1 text-xs font-normal text-slate-500">хоног</span>
              </span>
            </p>
          )}
        </div>
      </div>
      <AppLink
        to="#work"
        className={rtabClass(active === "work", false)}
        aria-current={active === "work" ? "page" : undefined}
      >
        <WorkIcon />
        Ажил
      </AppLink>
      {can.view_salary && (
        <AppLink
          to="#salary"
          className={rtabClass(active === "salary", true)}
          aria-current={active === "salary" ? "page" : undefined}
        >
          <SalaryIcon />
          Цалин, даатгал
        </AppLink>
      )}
      {can.view_personal && (
        <AppLink
          to="#personal"
          className={rtabClass(active === "personal", true)}
          aria-current={active === "personal" ? "page" : undefined}
        >
          <PersonalIcon />
          Хувийн
        </AppLink>
      )}
    </aside>
  );
}
