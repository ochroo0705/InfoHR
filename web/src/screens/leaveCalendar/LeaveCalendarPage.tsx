import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useLeaveCalendar, type LeaveCalendarOut } from "../../api/leavePages";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { Select, type SelectOption } from "../../widgets/Select";
import { LeaveNav } from "../leave/LeaveNav";
import { CalendarGrid } from "./CalendarGrid";
import { parseCalendarParams, toSearch } from "./calendarParams";

// Port of app/leave/templates/leave/calendar.html at /leave/calendar/: the team calendar. Classes, Mongolian text and the
// element order are copied from the template. The month and the department live in the address (replaced, not pushed);
// the server answers the title, the links and the choices. While a new month loads, the last settled month stays on
// screen, inert, as the leave list does.
const TITLE = "Чөлөөний хуанли";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

// The address for a month and department, with a leading "?" so the link keeps this page's path.
function addressFor(month: string, department: string): string {
  return `?${toSearch({ month, department }).toString()}`;
}

export function LeaveCalendarPage() {
  useMainWidth(MAIN_WIDTH);
  const [search, setSearch] = useSearchParams();
  const params = parseCalendarParams(search);
  const query = useLeaveCalendar({ month: params.month, department: params.department });
  const [good, setGood] = useState<LeaveCalendarOut | null>(null);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  const data = query.data;
  if (data && data !== good) setGood(data);
  const view = data ?? good;
  const settling = data === undefined;

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (data === undefined && query.isError && (query.error as { status?: number } | null)?.status === 403) {
    return <Forbidden />;
  }
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  const departmentOptions: SelectOption[] = [
    { value: "", label: "Бүх хэлтэс" },
    ...view.departments.map((d) => ({ value: String(d.value), label: d.label })),
  ];

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <LeaveNav current="calendar" canSettings={view.can_settings} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-xl font-semibold">{view.title}</h1>
        {view.this_month ? (
          <Link
            to={addressFor(view.this_month, params.department)}
            replace
            className="rounded border border-violet-300 px-3 py-1 text-sm text-violet-700 hover:bg-violet-50"
          >
            Энэ сар
          </Link>
        ) : null}
        {view.prev ? (
          <Link
            to={addressFor(view.prev, params.department)}
            replace
            className="rounded border border-slate-300 px-3 py-1 text-sm"
          >
            {`← ${view.prev}`}
          </Link>
        ) : null}
        {view.next ? (
          <Link
            to={addressFor(view.next, params.department)}
            replace
            className="rounded border border-slate-300 px-3 py-1 text-sm"
          >
            {`${view.next} →`}
          </Link>
        ) : null}
      </div>
      {view.not_configured ? (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {view.not_configured}
          {view.can_settings ? (
            <>
              {" "}
              <AppLink to="/leave/settings/" className="underline">
                Тохируулах
              </AppLink>
            </>
          ) : null}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="calendar-department" className="sr-only">
          Хэлтэс
        </label>
        <Select
          id="calendar-department"
          name="department"
          value={params.department}
          options={departmentOptions}
          search={false}
          className="rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm"
          onChange={(value) => setSearch(toSearch({ month: params.month, department: value }), { replace: true })}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs" data-calendar-legend>
        <span>
          <i className="inline-block h-3 w-3 rounded bg-violet-200"></i> Ээлжийн амралт
        </span>
        <span>
          <i className="inline-block h-3 w-3 rounded bg-amber-200"></i> Бусад чөлөө
        </span>
        <span>
          <i className="inline-block h-3 w-3 rounded bg-sky-200"></i> Урт чөлөө
        </span>
        <span>
          <i className="inline-block h-3 w-3 rounded border border-slate-400 bg-slate-100 dark:bg-slate-300"></i> Ажлын бус
          өдөр (амралт, баяр)
        </span>
        <span>
          <i className="inline-block h-3 w-3 rounded ring-2 ring-inset ring-violet-600 dark:ring-white"></i> Өнөөдөр
        </span>
        <span>
          <b className="font-semibold text-red-600">1</b> Улаан тоо — баярын өдөр
        </span>
      </div>
      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <div className={settling ? "opacity-60 pointer-events-none" : undefined} aria-busy={settling || undefined} inert={settling || undefined}>
        <CalendarGrid view={view} />
      </div>
    </>
  );
}
