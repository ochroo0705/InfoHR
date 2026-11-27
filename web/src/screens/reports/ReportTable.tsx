import { useEffect, useRef } from "react";
import { useReportRows, type ReportGroupOut, type ReportTableOut } from "../../api/reports";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { ScrollHost } from "../../widgets/Scrollbar";
import { HeaderRow, type CheckColumn, type HeaderSelect } from "./HeaderRow";
import { ReportCell, inlineStyle } from "./ReportCell";
import { ReportRows, rowPerson } from "./ReportRows";
import { SelectionBar } from "./SelectionBar";
import { headerMark, isOn, isPicked } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";
import { useStickyHeader } from "./useStickyHeader";

// The table of a report page (app/reports/templates/reports/_table.html, _rows.html, _batch_rows.html). The API draws the
// heads, the cells, the groups and the footer; this component only lays them out and loads the next batch.
// Cells are read-only here, and there is no editing (step 5f). `table` is the page's own first batch; further batches come
// from the rows route through the «Цааш харуулах» pill. With `selection` (a selectable table of a report with a person),
// the selection column has its checkboxes and the selection bar sits above the table (step 5d).

// The row selection of the page. `api` is the hook's result; the page passes this only when the report is selectable.
export interface ReportTableSelection {
  api: ReportSelection;
  urls: Record<string, string>;
  maxPeople: number;
  reportKey: string;
}

export interface ReportTableProps {
  reportKey: string;
  query: string; // the address query, sent as typed (see api/reports.ts)
  table: ReportTableOut;
  dataUpdatedAt: number; // the page query's dataUpdatedAt: a page refetch seeds a new rows query from the new first batch
  inert?: boolean; // the table is inert while a new address loads: no sticky header copy is drawn meanwhile
  selection?: ReportTableSelection;
}

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function ReportTable({ reportKey, query, table, dataUpdatedAt, inert = false, selection }: ReportTableProps) {
  const rows = useReportRows(reportKey, query, table, dataUpdatedAt);
  const moreRef = useRef<HTMLButtonElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  // The selection column: a blank placeholder, with the API's class and pinned offset (_table.html). Its footer cell is
  // classed only when the first columns are pinned (Django's check_pinned).
  const check: CheckColumn | null = table.selectable ? { css: table.check_css, style: table.check_style } : null;
  const footerCheck: CheckColumn | null = check && table.pin > 0 ? check : check ? { css: "", style: "" } : null;

  const grouped = table.groups.some((group) => group.label !== "");
  const pages = rows.data?.pages ?? [];
  // The fixed copy of the header is measured again when the address, the answer or the batches loaded change.
  useStickyHeader(tableRef, `${query}|${dataUpdatedAt}|${pages.length}`, inert);
  const loaded: ReportGroupOut[] = pages.flatMap((page) => page.groups);
  // An ungrouped table is one unlabelled group: its batches run on as one list of rows.
  const shown: ReportGroupOut[] = grouped
    ? loaded
    : [{ label: "", count: 0, rows: loaded.flatMap((group) => group.rows) }];

  // The person ids of the rows on screen, in draw order. They are registered with the selection on every render, as the
  // hook's contract asks, so the header box, the «all matching» offer and the picks read the rows as drawn.
  const visibleIds: string[] = shown.flatMap((group) =>
    group.rows.flatMap((row) => {
      const id = rowPerson(row);
      return id === null ? [] : [id];
    }),
  );
  if (selection) selection.api.setVisibleIds(visibleIds);
  const state = selection?.api.state ?? null;
  const selecting = state !== null && isOn(state);
  // body[data-selecting] is what the stylesheet reads to stop text selection in the picked rows (report_select.js sync).
  useEffect(() => {
    if (!selecting) return;
    document.body.dataset.selecting = "1";
    return () => {
      delete document.body.dataset.selecting;
    };
  }, [selecting]);
  const headSelect: HeaderSelect | null =
    selection && state ? { mark: headerMark(state, visibleIds), onPick: selection.api.pickVisible } : null;

  const hasMore = rows.hasNextPage;
  const loadingMore = rows.isFetchingNextPage;
  const failed = rows.isError;
  // After a failed batch the pill is not loaded by scrolling into view; its click still asks again.
  const onMore = () => {
    if (!loadingMore) void rows.fetchNextPage();
  };
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !failed);

  const footer = table.footer && table.footer.length > 0 ? table.footer : null;

  return (
    <>
      {failed ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      {selection && state ? (
        <SelectionBar
          reportKey={selection.reportKey}
          query={query}
          total={table.count}
          urls={selection.urls}
          selection={selection.api}
          pickedCount={state.all ? table.count : state.ids.size}
          allVisiblePicked={visibleIds.length > 0 && visibleIds.every((id) => isPicked(state, id))}
          hasMore={hasMore}
          overCap={table.count > selection.maxPeople}
          maxPeople={selection.maxPeople}
        />
      ) : null}
      <ScrollHost fit className="ptable ptable-fit">
        <table ref={tableRef} data-grid="" tabIndex={0} aria-label="Хүснэгт: сумаар шилжинэ">
          <thead>
            <HeaderRow heads={table.heads} check={check} select={headSelect} />
          </thead>
          <tbody>
            {table.count === 0 ? (
              <tr>
                <td colSpan={table.table_span} className="py-6 text-center text-slate-400">
                  Өгөгдөл олдсонгүй
                </td>
              </tr>
            ) : (
              <>
                <ReportRows
                  groups={shown}
                  grouped={grouped}
                  tableSpan={table.table_span}
                  check={check}
                  selection={selection?.api ?? null}
                />
                {hasMore ? (
                  <tr data-more-row>
                    <td colSpan={table.table_span} className="px-4 py-3 text-center">
                      <button
                        ref={moreRef}
                        type="button"
                        data-more-batch
                        onClick={onMore}
                        className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-surface px-4 py-1.5 text-sm text-slate-600 hover:border-violet-300 hover:text-violet-700"
                      >
                        <svg
                          aria-hidden="true"
                          className={
                            loadingMore
                              ? "htmx-indicator h-4 w-4 animate-spin htmx-request"
                              : "htmx-indicator h-4 w-4 animate-spin"
                          }
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
                ) : null}
              </>
            )}
          </tbody>
          {footer ? (
            <tfoot>
              <tr className="border-t border-slate-300 font-semibold">
                {footerCheck ? (
                  <td className={footerCheck.css || undefined} style={inlineStyle(footerCheck.style)} />
                ) : null}
                {footer.map((cell, index) => (
                  <ReportCell key={index} cell={cell} />
                ))}
              </tr>
            </tfoot>
          ) : null}
        </table>
      </ScrollHost>
    </>
  );
}
