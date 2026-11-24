import { useRef, type KeyboardEvent } from "react";
import type { LeaveRowOut } from "../../api/leave";
import { AppLink } from "../../lib/AppLink";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { cn } from "../../lib/utils";

// The leave rows (app/leave/templates/leave/_rows.html, and the table around it in list.html). Classes, Mongolian text
// and element order are copied from the templates; below md each row folds into a card with «Ажилтан: »-style labels.
// The rows come from the API: the state label and chip, the cancel button's text (cancel_label, null unless the user may
// record and the row counts) and the working days all come from there.
//
// A row has one action: a counting row opens the edit pop-up (`onEdit`) when the user may record; any other row goes to
// the employee's page. The employee name is a link of its own and does not trigger the row. The cancel button stops the
// click so it does not also open the edit pop-up.
//
// Keyboard (UI_RULES §4a, as in the employee log): every row is a tab stop (tabIndex=0), Enter or Space on the row itself
// does the row's action, keys from an inner control are ignored, and the row shows a focus-visible outline. The row has no
// role="button" and no inner button of its own.

const COLUMNS = 6;
const COMMENT_MAX = 60;

export interface LeaveTableProps {
  rows: LeaveRowOut[];
  // The user may record leave (the list's can_record): decides whether a counting row opens the edit pop-up.
  canRecord: boolean;
  emptyText: string;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  onEdit: (id: number) => void;
  onCancel: (id: number) => void;
  // True while the rows on screen are the last settled ones of an older filter: inert, and no empty-row text is drawn.
  settling?: boolean;
}

// Django's `truncatechars:60`: a longer text keeps 59 characters and an ellipsis.
export function truncateComment(text: string): string {
  return text.length <= COMMENT_MAX ? text : `${text.slice(0, COMMENT_MAX - 1)}…`;
}

export function LeaveTable({
  rows,
  canRecord,
  emptyText,
  hasMore,
  loadingMore,
  onMore,
  onEdit,
  onCancel,
  settling = false,
}: LeaveTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !settling);
  const goTo = useTransitionNavigate();

  // The row's one action: edit when the user may record and the row counts, else the employee's page.
  function act(row: LeaveRowOut) {
    if (canRecord && row.counts) onEdit(row.id);
    else goTo(`/employees/${row.employee_id}/`);
  }

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: LeaveRowOut) {
    // Keys from an inner control (the name link, the cancel button) are not the row's.
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    act(row);
  }

  return (
    <div
      className={cn("card-soft mt-3 overflow-x-auto px-3 pb-2 md:px-4", settling && "opacity-60 pointer-events-none")}
      aria-busy={settling ? "true" : undefined}
      inert={settling ? true : undefined}
    >
      <table className="w-full text-sm">
        <thead className="sr-only text-left text-slate-500 md:not-sr-only md:table-header-group">
          <tr>
            <th className="py-2">Ажилтан</th>
            <th>Төрөл</th>
            <th>Хугацаа</th>
            <th className="text-right">Ажлын өдөр</th>
            <th className="pl-6">Тайлбар</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="rows">
          {rows.map((row) => {
            const editable = canRecord && row.counts;
            return (
              <tr
                key={row.id}
                tabIndex={0}
                title={editable ? "Засах" : undefined}
                className={cn(
                  "block my-2 rounded-lg border border-slate-200 px-3 py-2 hover:bg-violet-50 cursor-pointer md:table-row md:my-0 md:rounded-none md:border-0 md:border-t md:border-slate-100 md:px-0 md:py-0 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500",
                  !row.counts && "text-slate-400 line-through",
                )}
                onClick={() => act(row)}
                onKeyDown={(event) => onRowKeyDown(event, row)}
              >
                <td className="block py-1 md:table-cell md:py-2">
                  <span className="text-slate-500 md:hidden">Ажилтан: </span>
                  <AppLink
                    to={`/employees/${row.employee_id}/`}
                    onClick={(e) => e.stopPropagation()}
                    className="hover:text-violet-700 hover:underline"
                  >
                    {row.employee_name}
                  </AppLink>
                </td>
                <td className="block py-0.5 md:table-cell">
                  <span className="text-slate-500 md:hidden">Төрөл: </span>
                  {row.leave_type}
                  {row.state_chip ? (
                    <>
                      {" "}
                      <span className="ml-1 rounded bg-slate-100 px-1.5 text-xs no-underline">{row.state}</span>
                    </>
                  ) : null}
                </td>
                <td className="block whitespace-nowrap py-0.5 md:table-cell">
                  <span className="text-slate-500 md:hidden">Хугацаа: </span>
                  {row.start} – {row.end}
                </td>
                <td className="block py-0.5 text-left md:table-cell md:text-right">
                  <span className="text-slate-500 md:hidden">Ажлын өдөр: </span>
                  {row.days}
                </td>
                <td className="block py-0.5 text-slate-500 md:table-cell md:pl-6">
                  {row.comment ? <span className="text-slate-500 md:hidden">Тайлбар: </span> : null}
                  {truncateComment(row.comment)}
                </td>
                <td className="block pt-1 text-left md:table-cell md:pt-0 md:text-right">
                  {canRecord && row.counts && row.cancel_label !== null ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCancel(row.id);
                      }}
                      className="whitespace-nowrap rounded px-2 py-1 text-red-600 hover:bg-red-50"
                    >
                      {row.cancel_label}
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
          {/*
            Empty state: the page passes no rows once the filter has settled and none came back (Django's
            `not items and not offset`).
          */}
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
