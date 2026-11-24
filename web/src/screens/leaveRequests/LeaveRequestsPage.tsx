import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useLeaveRequests, type LeaveRequestListOut } from "../../api/leaveRequests";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { Select, type SelectOption } from "../../widgets/Select";
import { LeaveRequestsTable } from "./LeaveRequestsTable";
import { RequestDetailModal } from "./RequestDetailModal";
import { parseRequestParams, toSearch, type RequestParams } from "./requestParams";

// Port of app/leave/templates/leave/requests.html at /leave/requests/: the leave requests list. Classes, Mongolian text and
// the element order are copied from the template. The tab and the status live in the address (replaced, not pushed);
// every value and text comes from the API. This page lays them out and keeps the open request's id.
const TITLE = "Чөлөөний хүсэлт";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const MINE_HINT = "Таны батлах ээлжинд хүлээгдэж буй хүсэлтүүд. Мөрийг дарж шийдвэрлэнэ.";
const TAB_BASE = "px-3 py-2";
const TAB_ON = "bg-violet-600 text-white";
const TAB_OFF = "bg-surface text-slate-700 hover:bg-slate-50";
const SELECT_CLASS = "shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm"; // UI_RULES §5

// The page root's data-modal (as LeavePage's): "detail:<id>" while a request's pop-up is open, absent when none is.
export function modalAttribute(openId: number | null): string | undefined {
  return openId === null ? undefined : `detail:${openId}`;
}

export function LeaveRequestsPage() {
  useMainWidth(MAIN_WIDTH);
  const [search, setSearch] = useSearchParams();
  const params: RequestParams = parseRequestParams(search);
  const query = useLeaveRequests(params);
  const [openId, setOpenId] = useState<number | null>(null);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The batches of the filter on screen. While a new filter loads there are none: the batches of the last settled filter
  // (`good`) stay on screen, stale and inert, until the new first batch arrives (as LeavePage).
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<LeaveRequestListOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  // A new filter that failed shows no rows, only the alert. A failed next batch keeps its rows (`settled` is true then).
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (failedNew && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  const statusOptions: SelectOption[] = [
    { value: "", label: "Бүх төлөв" },
    ...view.statuses.map((s) => ({ value: s.value, label: s.label })),
  ];

  return (
    <div data-modal={modalAttribute(openId)}>
      <nav className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-sm" aria-label="Хүсэлтийн харагдац">
        <AppLink
          to="/leave/requests/"
          aria-current={view.tab === "mine" ? "page" : undefined}
          className={`${TAB_BASE} ${view.tab === "mine" ? TAB_ON : TAB_OFF}`}
        >
          Надад ирсэн
        </AppLink>
        {view.can_all ? (
          <AppLink
            to="/leave/requests/?tab=all"
            aria-current={view.tab === "all" ? "page" : undefined}
            className={`${TAB_BASE} ${view.tab === "all" ? TAB_ON : TAB_OFF}`}
          >
            Бүгд
          </AppLink>
        ) : null}
      </nav>
      <h1 className="mt-3 text-xl font-semibold">{TITLE}</h1>
      {view.tab === "mine" ? (
        <p className="mt-1 text-sm text-slate-500">{MINE_HINT}</p>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="request-status" className="sr-only">
            Төлөв
          </label>
          <Select
            id="request-status"
            name="status"
            value={params.status}
            options={statusOptions}
            search={false}
            className={SELECT_CLASS}
            onChange={(v) => setSearch(toSearch({ ...params, status: v }), { replace: true })}
          />
        </div>
      )}

      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      {tableShown ? (
        <LeaveRequestsTable
          rows={rows}
          emptyText={view.empty_text}
          hasMore={settled && query.hasNextPage}
          loadingMore={settled && query.isFetchingNextPage}
          onMore={() => {
            if (settled) void query.fetchNextPage();
          }}
          onOpen={setOpenId}
          settling={!settled}
        />
      ) : null}
      {openId !== null ? (
        <RequestDetailModal key={openId} id={openId} onClose={() => setOpenId(null)} />
      ) : null}
    </div>
  );
}
