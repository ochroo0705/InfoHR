import { useRef, type KeyboardEvent } from "react";
import type { SlotRowOut, SlotTotalsOut } from "../../api/slots";
import { cn } from "../../lib/utils";
import { useMoreSentinel } from "../../lib/useMoreSentinel";

// The slot table (employees/slots_list.html table and employees/_slot_rows.html rows). Classes, Mongolian text and
// element order are copied from the templates. The free-count classes and the kind label come from the API; the footer
// totals are the API's totals of the whole year, not the sum of the loaded rows.

export interface SlotsTableProps {
  rows: SlotRowOut[];
  totals: SlotTotalsOut;
  emptyText: string;
  hasMore: boolean;
  onMore: () => void;
  onOpen: (id: number) => void;
  // True while the rows on screen are the last settled ones of an older year: inert, and no empty-row text is drawn.
  settling?: boolean;
  loadingMore?: boolean;
}

const COLUMNS = 6;

export function SlotsTable({ rows, totals, emptyText, hasMore, onMore, onOpen, settling = false, loadingMore = false }: SlotsTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !settling);

  // A row opens its pop-up (Task 5 wires onOpen). Enter or Space on the focused row does the same as a click.
  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, id: number) {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onOpen(id);
  }

  return (
    <div
      className={cn("card-soft mt-3 overflow-x-auto px-4 pb-2", settling && "opacity-60 pointer-events-none")}
      aria-busy={settling ? "true" : undefined}
      inert={settling ? true : undefined}
    >
      <table className="w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="py-2">Албан тушаал</th>
            <th>Салбар</th>
            <th>Төрөл</th>
            <th className="text-right">Орон тоо</th>
            <th className="text-right">Ашиглаж буй</th>
            <th className="text-right">Сул</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              role="button"
              tabIndex={0}
              className="cursor-pointer border-t border-slate-100 hover:bg-violet-50 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
              onClick={() => onOpen(row.id)}
              onKeyDown={(event) => onRowKeyDown(event, row.id)}
            >
              <td className="py-2 font-medium">{row.position}</td>
              <td>{row.branch}</td>
              <td>{row.kind_label}</td>
              <td className="text-right">{row.posts}</td>
              <td className="text-right">{row.used}</td>
              <td className={cn("text-right", row.free_class)}>{row.free}</td>
            </tr>
          ))}
          {/*
            Empty state: the page passes no rows once the year has settled and none came back. Equivalent to Django's
            `not rows and not offset`, because next_offset is null when no row follows.
          */}
          {rows.length === 0 && !hasMore && !settling && (
            <tr>
              <td colSpan={COLUMNS} className="py-6 text-center text-slate-400">
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
        {totals.posts || totals.used || rows.length ? (
          <tfoot>
            <tr className="border-t-2 border-slate-200 font-medium">
              <td className="py-2" colSpan={3}>
                Нийт
              </td>
              <td className="text-right">{totals.posts}</td>
              <td className="text-right">{totals.used}</td>
              <td className="text-right">{totals.free}</td>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
