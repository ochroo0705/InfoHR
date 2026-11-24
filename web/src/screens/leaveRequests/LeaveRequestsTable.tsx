import { useRef, type KeyboardEvent } from "react";
import type { LeaveRequestRowOut } from "../../api/leaveRequests";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { cn } from "../../lib/utils";

// The leave requests table (app/leave/templates/leave/requests.html and _request_rows.html). Classes, Mongolian text and
// element order are copied from the templates. Unlike the leave list, the table does not fold into cards on a phone: it
// scrolls sideways inside its card, as Django does.
//
// A row opens its request's pop-up (`onOpen`). Keyboard (UI_RULES §4, as the leave list's LeaveTable): every row is a tab
// stop, Enter or Space on the row itself opens it, keys from an inner element are ignored, and the row shows a focus
// outline. The row has no role="button". A blank cell shows «—».
//
// The more batch loads when its pill scrolls into view (useMoreSentinel) or on click (the keyboard way).

const COLUMNS = 8;
const DASH = "—";

export interface LeaveRequestsTableProps {
  rows: LeaveRequestRowOut[];
  // The server's text for an empty list (empty_text).
  emptyText: string;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  // Opens the request's pop-up with its id.
  onOpen: (id: number) => void;
  // True while the rows on screen are the last settled ones of an older filter: inert, and no empty-row text is drawn.
  settling?: boolean;
}

export function LeaveRequestsTable({
  rows,
  emptyText,
  hasMore,
  loadingMore,
  onMore,
  onOpen,
  settling = false,
}: LeaveRequestsTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !settling);

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, id: number) {
    // Keys from an inner control are not the row's.
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
            <th className="py-2">Ажилтан</th>
            <th>Төрөл</th>
            <th>Хугацаа</th>
            <th className="text-right">Ажлын өдөр</th>
            <th className="pl-6">Шат</th>
            <th className="pl-6">Батлах</th>
            <th className="pl-6">Төлөв</th>
            <th className="pl-6">Хүлээж эхэлсэн</th>
          </tr>
        </thead>
        <tbody id="rows">
          {rows.map((row) => (
            <tr
              key={row.id}
              tabIndex={0}
              title="Нээх"
              className="border-t border-slate-100 hover:bg-violet-50 cursor-pointer focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
              onClick={() => onOpen(row.id)}
              onKeyDown={(event) => onRowKeyDown(event, row.id)}
            >
              <td className="py-2">{row.employee_name || DASH}</td>
              <td>{row.leave_type || DASH}</td>
              <td>{`${row.start} – ${row.end}`}</td>
              <td className="text-right">{row.working_days}</td>
              <td className="pl-6">
                {row.waiting && row.current_step !== null && row.step_count !== null
                  ? `${row.current_step}/${row.step_count}`
                  : DASH}
              </td>
              <td className="pl-6 text-slate-500">{row.rule || DASH}</td>
              <td className="pl-6">{row.status_label || DASH}</td>
              <td className="pl-6 text-slate-500">{row.waiting && row.since ? row.since : DASH}</td>
            </tr>
          ))}
          {/* Empty state: once the filter has settled and no row came back (Django's `not items and not offset`). */}
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
