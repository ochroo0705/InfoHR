import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useLeaveList, type LeaveListOut } from "../../api/leave";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { LeaveCancelModal } from "./LeaveCancelModal";
import { LeaveFilters } from "./LeaveFilters";
import { LeaveFormModal } from "./LeaveFormModal";
import { LeaveNav } from "./LeaveNav";
import { LeaveTable } from "./LeaveTable";
import { parseLeaveParams, toSearch } from "./leaveParams";

// Port of app/leave/templates/leave/list.html at /leave/: the leave list. Classes, Mongolian text and the element order are
// copied from the template. The filters live in the address (replaced, not pushed); every value and text comes from the
// API. This page lays them out and keeps the open pop-up.
const TITLE = "Чөлөө, амралт";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

// The open pop-up: set by the add button, a row (edit) and the cancel button; the pop-up components clear it on close.
export type LeaveModal = { kind: "add" } | { kind: "edit"; id: number } | { kind: "cancel"; id: number };

// The page root's data-modal: "add", "edit:<id>", "cancel:<id>", or absent when no pop-up is open.
export function modalAttribute(modal: LeaveModal | null): string | undefined {
  if (modal === null) return undefined;
  return modal.kind === "add" ? "add" : `${modal.kind}:${modal.id}`;
}

export function LeavePage() {
  useMainWidth(MAIN_WIDTH);
  const [search, setSearch] = useSearchParams();
  const params = parseLeaveParams(search);
  const query = useLeaveList(params);
  const [modal, setModal] = useState<LeaveModal | null>(null);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The batches of the filter on screen. While a new filter loads there are none: the batches of the last settled filter
  // (`good`) stay on screen, stale and inert, until the new first batch arrives (as SlotsPage).
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<LeaveListOut[] | null>(null);
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

  // With the `employee` link the server sets q to that person's name, and the search box shows it. The reply counts
  // only when it answers this address's employee (a batch of an older filter is never used). Typing in the box drops
  // the employee link (LeaveFilters' change), as Django's form does.
  const linkedToReply =
    params.employee !== "" && view.filters.employee !== null && String(view.filters.employee) === params.employee;
  const searchQ = linkedToReply ? view.filters.q : params.q;

  // The modal is closed by the pop-up itself (save, cancel, Болих, Esc, ✕).
  const closeModal = () => setModal(null);

  return (
    <div data-modal={modalAttribute(modal)}>
      <h1 className="sr-only">{TITLE}</h1>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <LeaveNav current="list" canSettings={view.can_settings} />
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {view.report_url ? (
            <a href={view.report_url} className="text-sm text-violet-700 hover:underline">
              Тайлан гаргах
            </a>
          ) : null}
          {view.can_record ? (
            <button
              type="button"
              disabled={!settled}
              onClick={() => setModal({ kind: "add" })}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Чөлөө бүртгэх
            </button>
          ) : null}
        </div>
      </div>

      {view.not_configured ? (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
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
      {view.missing_holidays.map((year) => (
        <p key={year.year} className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {`${year.year} оны баярын өдөр бүртгээгүй байна — ажлын өдөр буруу тоологдоно. `}
          {year.can_register ? (
            <AppLink to={`/leave/holidays/?year=${year.year}`} className="underline">
              Бүртгэх
            </AppLink>
          ) : null}
        </p>
      ))}

      <LeaveFilters
        params={{ ...params, q: searchQ }}
        types={view.types}
        onChange={(next) => setSearch(toSearch(next), { replace: true })}
      />

      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      {tableShown ? (
        <LeaveTable
          rows={rows}
          canRecord={view.can_record}
          emptyText={view.empty_text}
          hasMore={settled && query.hasNextPage}
          loadingMore={settled && query.isFetchingNextPage}
          onMore={() => {
            if (settled) void query.fetchNextPage();
          }}
          onEdit={(id) => setModal({ kind: "edit", id })}
          onCancel={(id) => setModal({ kind: "cancel", id })}
          settling={!settled}
        />
      ) : null}
      {modal === null ? null : modal.kind === "cancel" ? (
        <LeaveCancelModal id={modal.id} onClose={closeModal} />
      ) : (
        <LeaveFormModal
          mode={modal.kind === "edit" ? { kind: "edit", id: modal.id } : { kind: "add" }}
          canSettings={view.can_settings}
          onClose={closeModal}
        />
      )}
    </div>
  );
}
