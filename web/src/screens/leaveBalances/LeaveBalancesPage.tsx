import { useEffect, useRef, type KeyboardEvent } from "react";
import { useLeaveBalances, type LeaveBalanceRowOut } from "../../api/leavePages";
import { AppLink } from "../../lib/AppLink";
import { cn } from "../../lib/utils";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { Forbidden } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { ScrollHost } from "../../widgets/Scrollbar";
import { LeaveNav } from "../leave/LeaveNav";

// Port of app/leave/templates/leave/balances.html and _balance_rows.html at /leave/balances/: the leave balances of the
// visible people. Classes, Mongolian text and the element order are copied from the templates. The rows come from the
// API batch by batch; the not-configured text, the sentence with today's date and the empty text come from there too.
// A row opens the employee page. The row keeps the keyboard rule of the leave list (LeaveTable): a tab stop, Enter and
// Space open it, keys from the name link are its own, and there is no role="button" on the row.
const TITLE = "Амралтын үлдэгдэл";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const COLUMNS = 5;
const NO_PERIOD = "Одоогийн ажлын жилд эрх бүртгэгдээгүй";
const WAITING_TITLE = "Ажилд орсноос хойш хангалттай сар болоогүй";

// The pill of the days left: red below zero, green above, grey at zero.
function leftClass(left: number): string {
  if (left < 0) return "bg-red-100 text-red-700";
  if (left > 0) return "bg-emerald-100 text-emerald-800";
  return "bg-slate-100 text-slate-500";
}

interface BalanceRowProps {
  row: LeaveBalanceRowOut;
  onOpen: (employeeId: number) => void;
}

function BalanceRow({ row, onOpen }: BalanceRowProps) {
  const { period } = row;

  // The row's one action is the employee page. Keys from an inner control (the name link) are not the row's.
  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onOpen(row.employee_id);
  }

  return (
    <tr
      tabIndex={0}
      className="hover:bg-violet-50 cursor-pointer focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
      onClick={() => onOpen(row.employee_id)}
      onKeyDown={onKeyDown}
    >
      <td>
        <AppLink
          to={`/employees/${row.employee_id}/`}
          onClick={(e) => e.stopPropagation()}
          className="hover:text-violet-700 hover:underline"
        >
          {row.employee_name}
        </AppLink>
        {row.waiting ? (
          <span
            data-waiting
            className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            title={WAITING_TITLE}
          >
            {`Эрх ${row.waiting}-аас`}
          </span>
        ) : null}
      </td>
      {period ? (
        <>
          <td className="whitespace-nowrap">
            {period.start} – {period.end}
          </td>
          <td className="text-right">{period.granted}</td>
          <td className="text-right">{period.taken}</td>
          <td className="text-right">
            <span
              className={cn(
                "inline-block min-w-10 rounded-full px-2 py-0.5 text-center font-semibold",
                leftClass(period.left),
              )}
            >
              {period.left}
            </span>
          </td>
        </>
      ) : (
        <td colSpan={4} className="text-slate-500">
          {NO_PERIOD}
        </td>
      )}
    </tr>
  );
}

export function LeaveBalancesPage() {
  useMainWidth(MAIN_WIDTH);
  const query = useLeaveBalances();
  const goTo = useTransitionNavigate();
  const moreRef = useRef<HTMLButtonElement>(null);
  const hasMore = query.hasNextPage;
  const loadingMore = query.isFetchingNextPage;
  useMoreSentinel(moreRef, () => {
    if (!loadingMore) void query.fetchNextPage();
  }, hasMore && !loadingMore);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  const pages = query.data?.pages;
  const first = pages?.[0];

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (first === undefined && query.isError && (query.error as { status?: number } | null)?.status === 403) {
    return <Forbidden />;
  }
  if (pages === undefined || first === undefined) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  const rows = pages.flatMap((page) => page.rows);

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <LeaveNav current="balances" canSettings={first.can_settings} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{TITLE}</h1>
      </div>
      {first.not_configured ? (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {first.not_configured}
          {first.can_settings ? (
            <>
              {" "}
              <AppLink to="/leave/settings/" className="underline">
                Тохируулах
              </AppLink>
            </>
          ) : null}
        </p>
      ) : null}
      <p className="mt-2 text-sm text-slate-500">
        {`Ээлжийн амралтын хоног: одоогийн ажлын жилээр (${first.today} байдлаар). Үлдэгдлийг өөр систем бүртгэнэ, энд зөвхөн харна.`}
      </p>
      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <ScrollHost fit className="ptable ptable-fit card-soft mt-3">
        <table>
          <thead>
            <tr>
              <th>Ажилтан</th>
              <th>Хүчинтэй хугацаа</th>
              <th className="text-right">Эрх</th>
              <th className="text-right">Авсан</th>
              <th className="text-right">Үлдэгдэл</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <BalanceRow key={row.employee_id} row={row} onOpen={(id) => goTo(`/employees/${id}/`)} />
            ))}
            {rows.length === 0 && !hasMore && (
              <tr>
                <td colSpan={COLUMNS} className="py-6 text-center text-slate-500">
                  {first.empty_text}
                </td>
              </tr>
            )}
            {hasMore && (
              <tr data-more-row>
                <td colSpan={COLUMNS} className="px-4 py-3 text-center">
                  <button
                    ref={moreRef}
                    type="button"
                    data-more-batch
                    onClick={() => {
                      if (!loadingMore) void query.fetchNextPage();
                    }}
                    className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-surface px-4 py-1.5 text-sm text-slate-600 hover:border-violet-300 hover:text-violet-700"
                  >
                    <svg
                      aria-hidden="true"
                      className={cn("htmx-indicator h-4 w-4 animate-spin", loadingMore && "htmx-request")}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
                    </svg>
                    Цааш харуулах
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </ScrollHost>
    </>
  );
}
