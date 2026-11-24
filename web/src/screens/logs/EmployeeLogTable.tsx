import { ScrollHost } from "../../widgets/Scrollbar";
import { useRef, type KeyboardEvent, type MouseEvent } from "react";
import type { LogEmployeeRowOut } from "../../api/logs";
import { AppLink } from "../../lib/AppLink";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { cn } from "../../lib/utils";
import { ChangeList } from "./ChangeList";

// The rows of the employee log (_employee_rows.html and _employee_items.html). Classes, Mongolian text and element order
// are copied from the templates. React decides nothing: the date and time text, the kind chip, the actor text, the
// message colour and whether a row opens an order (order_id) all come from the API.
//
// Keyboard (the rule of UI_RULES.md, as in orders/RegisterTable.tsx): a row with an order is a tab stop (tabIndex=0),
// Enter or Space on the row itself opens the order, keys from an inner control (the name link) are ignored, and the row
// shows a focus-visible outline. The row has no role="button" and no inner button. A row without an order gets none of it.

const COL_SPAN = 5;

export interface EmployeeLogTableProps {
  rows: LogEmployeeRowOut[];
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  onOpenOrder: (row: LogEmployeeRowOut) => void;
  // True while the rows on screen are the last settled ones of an older address: no empty-row message is drawn then.
  settling?: boolean;
  // False keeps the pill from loading by scrolling into view (after a failed batch); its click still calls onMore.
  autoLoad?: boolean;
}

export function EmployeeLogTable({
  rows,
  hasMore,
  loadingMore,
  onMore,
  onOpenOrder,
  settling = false,
  autoLoad = true,
}: EmployeeLogTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && autoLoad);

  return (
    <ScrollHost fit className="ptable ptable-fit card-soft">
      <table>
        <thead>
          <tr>
            <th>Огноо</th>
            <th>Ажилтан</th>
            <th>Хэн</th>
            <th>Төрөл</th>
            <th className="w-full">Мессеж, өөрчлөлт</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const hasOrder = row.order_id != null;
            const open = () => onOpenOrder(row);
            return (
              <tr
                key={row.id}
                className={cn(
                  "align-top",
                  hasOrder &&
                    "cursor-pointer hover:bg-violet-50 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500",
                )}
                tabIndex={hasOrder ? 0 : undefined}
                onClick={hasOrder ? open : undefined}
                onKeyDown={
                  hasOrder
                    ? (event: KeyboardEvent<HTMLTableRowElement>) => {
                        // Keys from an inner control (the name link) are not the row's.
                        if (event.target !== event.currentTarget) return;
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        open();
                      }
                    : undefined
                }
              >
                <td className="whitespace-nowrap">
                  {row.date} <span className="text-xs text-slate-400">{row.time}</span>
                </td>
                <td className="whitespace-nowrap">
                  <AppLink
                    to={`/employees/${row.employee_id}/`}
                    onClick={(e: MouseEvent<HTMLAnchorElement>) => e.stopPropagation()}
                    className="text-violet-700 hover:underline"
                  >
                    {row.employee_name}
                  </AppLink>{" "}
                  <span className="text-xs text-slate-500">{row.employee_code}</span>
                </td>
                <td className="whitespace-nowrap">{row.by_name}</td>
                <td>
                  <span className={cn("whitespace-nowrap rounded px-1.5 py-0.5 text-xs", row.kind_class)}>
                    {row.kind_label}
                  </span>
                </td>
                <td>
                  {row.is_note ? (
                    <p className="whitespace-pre-line rounded-lg bg-sky-50 px-3 py-2">{row.message}</p>
                  ) : (
                    <p className={row.is_correction ? "text-amber-700" : "text-slate-700"}>{row.message}</p>
                  )}
                  <ChangeList changes={row.changes} />
                </td>
              </tr>
            );
          })}
          {/*
            Empty state: the page passes rows only after the first batch has arrived, so this is the first batch with no
            row (Django's `not rows and not offset`).
          */}
          {rows.length === 0 && !hasMore && !settling && (
            <tr>
              <td colSpan={COL_SPAN} className="py-6 text-center text-slate-400">
                Бүртгэл олдсонгүй
              </td>
            </tr>
          )}
          {hasMore && (
            <tr data-more-row>
              <td colSpan={COL_SPAN} className="px-4 py-3 text-center">
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
    </ScrollHost>
  );
}
