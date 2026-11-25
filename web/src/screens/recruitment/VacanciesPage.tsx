import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router";
import { useVacancies, type RecruitVacancyListOut, type RecruitVacancyRowOut } from "../../api/recruitment";
import { AppLink } from "../../lib/AppLink";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { cn } from "../../lib/utils";
import { NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { Select, type SelectOption } from "../../widgets/Select";
import { useDebouncedField } from "../logs/useDebouncedField";
import { VacancyStatusChip } from "./stageChip";
import { VacancyModal } from "./VacancyModal";

// Port of app/recruitment/templates/recruitment/vacancy_list.html and _vacancy_rows.html at /recruitment/: the vacancy
// list. Classes, Mongolian texts and the element order are copied from the templates. The search and the status live in
// the address (replaced, not pushed); the rows, the counts and the empty text come from the API. Below md each row folds
// into a card with «<label>: »-style captions, as the template does.
//
// Keyboard (UI_RULES §4, the 3d-3 / 4d1 rule): every row is a tab stop, Enter or Space on the row opens the vacancy
// through the router, keys from an inner control (the title link) are ignored. The row has no role="button".

const TITLE = "Ажилд авах";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const SEARCH_PLACEHOLDER = "Нэр, албан тушаал, хэлтсээр хайх";
const COLUMNS = 8;

// The status filter. Open is the default and is left out of the address.
export const DEFAULT_STATUS = "open";
const STATUS_VALUES = ["open", "closed", "filled", "all"];
const STATUS_OPTIONS: SelectOption[] = [
  { value: "open", label: "Нээлттэй" },
  { value: "closed", label: "Хаагдсан" },
  { value: "filled", label: "Бөглөгдсөн" },
  { value: "all", label: "Бүгд" },
];

// An unknown status in the address reads as open, as the server answers it.
export function parseStatus(raw: string | null): string {
  return raw !== null && STATUS_VALUES.includes(raw) ? raw : DEFAULT_STATUS;
}

// The address of the list: q first, then status; empty values and the default status are left out.
export function toSearch(status: string, q: string): URLSearchParams {
  const search = new URLSearchParams();
  if (q) search.append("q", q);
  if (status !== DEFAULT_STATUS) search.append("status", status);
  return search;
}

function httpStatus(error: unknown): number | undefined {
  return (error as { status?: number } | null)?.status;
}

export function VacanciesPage() {
  useMainWidth(MAIN_WIDTH);
  const [search, setSearch] = useSearchParams();
  const status = parseStatus(search.get("status"));
  const q = search.get("q") ?? "";
  const query = useVacancies({ status, q });
  const [addOpen, setAddOpen] = useState(false);
  const goTo = useTransitionNavigate();

  // The search box shows what is typed and writes the address 300 ms after the last key (or at once on Enter).
  const [searchText, setSearchText, flushSearch] = useDebouncedField(q, (text) =>
    setSearch(toSearch(status, text), { replace: true }),
  );

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on this page.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The batches of the filter on screen. While a new filter loads there are none: the batches of the last settled filter
  // stay on screen, inert, until the new first batch arrives (as LeavePage).
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<RecruitVacancyListOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // The module is off (or the page is not there): the app's not-found page.
  if (failedNew && httpStatus(query.error) === 404) return <NotFound />;
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  const onSearchEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    flushSearch();
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{TITLE}</h1>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {view.can_manage ? (
            <AppLink to="/recruitment/purge/" className="text-sm text-violet-700 hover:underline">
              Хуучин татгалзсан ажил хүсэгч цэвэрлэх
            </AppLink>
          ) : null}
          {view.can_manage ? (
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
            >
              Ажлын байр нээх
            </button>
          ) : null}
        </div>
      </div>

      <form
        className="mt-4 flex flex-wrap items-center gap-2 text-sm"
        onSubmit={(event: FormEvent<HTMLFormElement>) => event.preventDefault()}
      >
        <input
          type="search"
          name="q"
          aria-label="Хайх"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          onKeyDown={onSearchEnter}
          placeholder={SEARCH_PLACEHOLDER}
          autoComplete="off"
          className="min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <label htmlFor="vacancy-status" className="sr-only">
          Төлөв
        </label>
        <Select
          id="vacancy-status"
          name="status"
          value={status}
          options={STATUS_OPTIONS}
          search={false}
          className="shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm"
          onChange={(value) => setSearch(toSearch(value, q), { replace: true })}
        />
      </form>

      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      {tableShown ? (
        <VacancyTable
          rows={rows}
          emptyText={view.empty_text}
          hasMore={settled && query.hasNextPage}
          loadingMore={settled && query.isFetchingNextPage}
          onMore={() => {
            if (settled) void query.fetchNextPage();
          }}
          onOpen={(id) => goTo(`/recruitment/vacancies/${id}/`)}
          settling={!settled}
        />
      ) : null}

      {addOpen ? <VacancyModal vacancyId={null} onClose={() => setAddOpen(false)} /> : null}
    </div>
  );
}

interface VacancyTableProps {
  rows: RecruitVacancyRowOut[];
  emptyText: string;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  onOpen: (id: number) => void;
  // True while the rows on screen are the last settled ones of an older filter: inert, and no empty-row text is drawn.
  settling: boolean;
}

function VacancyTable({ rows, emptyText, hasMore, loadingMore, onMore, onOpen, settling }: VacancyTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !settling);

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, id: number) {
    // Keys from an inner control (the title link) are not the row's.
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onOpen(id);
  }

  return (
    <div
      className={cn("card-soft mt-3 overflow-x-auto px-3 pb-2 md:px-4", settling && "pointer-events-none opacity-60")}
      aria-busy={settling ? "true" : undefined}
      inert={settling ? true : undefined}
    >
      <table className="w-full text-sm">
        <thead className="sr-only text-left text-slate-500 md:not-sr-only md:table-header-group">
          <tr>
            <th className="py-2">Ажлын байр</th>
            <th>Төлөв</th>
            <th className="text-right">Шинэ</th>
            <th className="pl-3 text-right">Шалгаруулалт</th>
            <th className="pl-3 text-right">Ярилцлага</th>
            <th className="pl-3 text-right">Санал</th>
            <th className="pl-3 text-right">Ажилд авсан</th>
            <th className="pl-6">Авах эцсийн хугацаа</th>
          </tr>
        </thead>
        <tbody id="rows">
          {rows.map((row) => (
            <tr
              key={row.id}
              tabIndex={0}
              className="block my-2 cursor-pointer rounded-lg border border-slate-200 px-3 py-2 hover:bg-violet-50 md:table-row md:my-0 md:rounded-none md:border-0 md:border-t md:border-slate-100 md:px-0 md:py-0 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
              onClick={() => onOpen(row.id)}
              onKeyDown={(event) => onRowKeyDown(event, row.id)}
            >
              <td className="block py-1 md:table-cell md:py-2">
                <AppLink
                  to={`/recruitment/vacancies/${row.id}/`}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium hover:text-violet-700 hover:underline"
                >
                  {row.title}
                </AppLink>
                <div className="text-xs text-slate-500">
                  {`${row.position} · ${row.department}${row.hiring_manager ? ` · ${row.hiring_manager}` : ""}`}
                </div>
              </td>
              <td className="block py-0.5 md:table-cell">
                <VacancyStatusChip status={row.status} label={row.status_label} />
              </td>
              <td className="mr-3 inline-block py-0.5 md:table-cell md:text-right">
                <span className="text-slate-500 md:hidden">Шинэ: </span>
                {row.counts.new}
              </td>
              <td className="mr-3 inline-block py-0.5 md:table-cell md:pl-3 md:text-right">
                <span className="text-slate-500 md:hidden">Шалгаруулалт: </span>
                {row.counts.screening}
              </td>
              <td className="mr-3 inline-block py-0.5 md:table-cell md:pl-3 md:text-right">
                <span className="text-slate-500 md:hidden">Ярилцлага: </span>
                {row.counts.interview}
              </td>
              <td className="mr-3 inline-block py-0.5 md:table-cell md:pl-3 md:text-right">
                <span className="text-slate-500 md:hidden">Санал: </span>
                {row.counts.offer}
              </td>
              <td className="inline-block py-0.5 md:table-cell md:pl-3 md:text-right">
                <span className="text-slate-500 md:hidden">Ажилд авсан: </span>
                {`${row.counts.hired} / ${row.headcount}`}
              </td>
              <td className="block whitespace-nowrap py-0.5 text-slate-500 md:table-cell md:pl-6">
                <span className="md:hidden">Авах эцсийн хугацаа: </span>
                {row.deadline ?? "—"}
              </td>
            </tr>
          ))}
          {/* Empty state: the page passes no rows once the filter has settled and none came back. */}
          {rows.length === 0 && !hasMore && !settling && (
            <tr>
              <td colSpan={COLUMNS} className="py-6 text-center text-slate-500">
                {emptyText}
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
                    if (!loadingMore) onMore();
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
    </div>
  );
}
