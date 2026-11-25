import { useRef } from "react";
import { useReportRows, type ReportGroupOut, type ReportTableOut } from "../../api/reports";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { ScrollHost } from "../../widgets/Scrollbar";
import { HeaderRow, type CheckColumn } from "./HeaderRow";
import { ReportCell, inlineStyle } from "./ReportCell";
import { ReportRows } from "./ReportRows";
import { useStickyHeader } from "./useStickyHeader";

// The table of a report page (app/reports/templates/reports/_table.html, _rows.html, _batch_rows.html). The API draws the
// heads, the cells, the groups and the footer; this component only lays them out and loads the next batch.
// Cells are read-only here: the selection column is a blank placeholder (step 5d draws the checkbox in it) and there is
// no editing (step 5f). `table` is the page's own first batch; further batches come from the rows route through the
// «Цааш харуулах» pill.

export interface ReportTableProps {
  reportKey: string;
  query: string; // the address query, sent as typed (see api/reports.ts)
  table: ReportTableOut;
  dataUpdatedAt: number; // the page query's dataUpdatedAt: a page refetch seeds a new rows query from the new first batch
  inert?: boolean; // the table is inert while a new address loads: no sticky header copy is drawn meanwhile
}

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function ReportTable({ reportKey, query, table, dataUpdatedAt, inert = false }: ReportTableProps) {
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
      <ScrollHost fit className="ptable ptable-fit">
        <table ref={tableRef} data-grid="" tabIndex={0} aria-label="Хүснэгт: сумаар шилжинэ">
          <thead>
            <HeaderRow heads={table.heads} check={check} />
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
