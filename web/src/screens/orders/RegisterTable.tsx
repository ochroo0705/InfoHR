import { useRef, type AriaAttributes, type MouseEvent } from "react";
import { useLocation } from "react-router";
import type { OrderRegisterOut, OrderRegisterRowOut } from "../../api/orderRegister";
import { cn } from "../../lib/utils";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { useMoreSentinel } from "./useMoreSentinel";

// The register table (orders/_order_register_rows.html) and its rows (_order_register_items.html). Classes, Mongolian
// text and element order are copied from the templates. React decides nothing: the number and date text, the chip
// classes, the awaiting chip, the sort heads, the checkbox (pickable) and the row click (opens) all come from the API.

type SortHead = OrderRegisterOut["sort_heads"][string];
type AriaSort = AriaAttributes["aria-sort"];

export interface RegisterTableProps {
  rows: OrderRegisterRowOut[];
  sort: string;
  sortHeads: OrderRegisterOut["sort_heads"];
  canManage: boolean;
  picked: ReadonlySet<string>;
  onPick: (key: string, checked: boolean) => void;
  onPickAll: (checked: boolean) => void;
  onOpen: (row: OrderRegisterRowOut) => void;
  onSort: (next: string) => void;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  // True while the rows on screen are the last settled ones of an older filter: no empty-row message is drawn then.
  settling?: boolean;
  // False keeps the pill from loading by scrolling into view (after a failed batch); its click still calls onMore.
  autoLoad?: boolean;
}

function ariaSort(value: string): AriaSort | undefined {
  return value ? (value as AriaSort) : undefined;
}

// The address a sort click leads to: the router's current location with the sort replaced, so the filters stay in a
// new-tab link. Built from the router (not window.location), so it follows the page's own address.
function sortHrefFrom(pathname: string, search: string, next: string): string {
  const params = new URLSearchParams(search);
  params.set("sort", next);
  return `${pathname}?${params.toString()}`;
}

// A sortable head (`<a class="hover:text-violet-700">` with the arrow after it). A plain click sorts in place; a
// modified click keeps the browser's own behaviour (a new tab) on the href.
function SortLink({
  head,
  href,
  label,
  onSort,
}: {
  head: SortHead;
  href: string;
  label: string;
  onSort: (next: string) => void;
}) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onSort(head.next);
  }
  return (
    <>
      <a href={href} onClick={handleClick} className="hover:text-violet-700">
        {label}
      </a>
      {head.arrow && (
        <>
          {" "}
          <span aria-hidden="true">{head.arrow}</span>
        </>
      )}
    </>
  );
}

export function RegisterTable({
  rows,
  sort,
  sortHeads,
  canManage,
  picked,
  onPick,
  onPickAll,
  onOpen,
  onSort,
  hasMore,
  loadingMore,
  onMore,
  settling = false,
  autoLoad = true,
}: RegisterTableProps) {
  const go = useTransitionNavigate();
  const location = useLocation();
  const sortHref = (next: string) => sortHrefFrom(location.pathname, location.search, next);
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && autoLoad);

  const pickable = rows.filter((row) => row.pickable);
  const allPicked = pickable.length > 0 && pickable.every((row) => picked.has(row.key));

  // A row with opens=detail shows its order's pop-up; opens=employee goes to the employee page (a ported path).
  function openRow(row: OrderRegisterRowOut) {
    if (row.opens === "detail") onOpen(row);
    else go(`/employees/${row.employee_id}/`);
  }

  const head = (h: SortHead) => ariaSort(h.aria);

  return (
    <table className="w-full text-sm" data-sort={sort}>
      <thead className="text-left text-slate-500">
        <tr>
          {canManage && (
            <th className="w-8">
              <input
                type="checkbox"
                id="order-pick-all"
                aria-label="Бүгдийг сонгох"
                className="rounded border-slate-300"
                checked={allPicked}
                onChange={(event) => onPickAll(event.target.checked)}
              />
            </th>
          )}
          <th className="py-2 whitespace-nowrap" aria-sort={head(sortHeads.number)}>
            <SortLink head={sortHeads.number} href={sortHref(sortHeads.number.next)} label="Дугаар" onSort={onSort} />
          </th>
          <th className="whitespace-nowrap" aria-sort={head(sortHeads.date)}>
            <SortLink head={sortHeads.date} href={sortHref(sortHeads.date.next)} label="Тушаалын огноо" onSort={onSort} />
          </th>
          <th aria-sort={head(sortHeads.employee)}>
            <SortLink head={sortHeads.employee} href={sortHref(sortHeads.employee.next)} label="Ажилтан" onSort={onSort} />
          </th>
          <th>Хэлтэс</th>
          <th>Тушаалын утга</th>
          <th className="whitespace-nowrap">Төлөв</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.key}
            className={cn(
              "cursor-pointer border-t border-slate-100 hover:bg-violet-50",
              row.cancelled && "text-slate-400 line-through",
            )}
            // Row click, as the Django `<tr hx-get>` / `onclick` (parity): no separate keyboard path is added. A row
            // with opens=employee keeps the router navigation (useTransitionNavigate).
            onClick={() => openRow(row)}
          >
            {canManage && (
              <td className="w-8" onClick={(event) => event.stopPropagation()}>
                {row.pickable && (
                  <input
                    type="checkbox"
                    value={row.order_id ?? undefined}
                    aria-label="Тушаал сонгох"
                    className="order-pick rounded border-slate-300"
                    checked={picked.has(row.key)}
                    onChange={(event) => onPick(row.key, event.target.checked)}
                  />
                )}
              </td>
            )}
            <td className="py-2 whitespace-nowrap">
              {row.number_muted ? <span className="text-slate-400">{row.number_label}</span> : row.number_label}
            </td>
            <td className="whitespace-nowrap">{row.date_label}</td>
            <td>{row.employee_name}</td>
            <td>{row.department}</td>
            <td>{row.summary}</td>
            <td>
              <div className="flex flex-wrap items-center gap-1">
                <span className={row.chip_class}>{row.state_label}</span>
                {row.awaiting_chip && <span className={row.awaiting_chip.class_name}>{row.awaiting_chip.label}</span>}
              </div>
            </td>
          </tr>
        ))}
        {/*
          Empty state. The page passes rows only after the first batch has arrived, so this is the first batch with no
          row. It is equivalent to Django's `not rows and not offset`, because the server sends next_offset null when no
          row follows.
        */}
        {rows.length === 0 && !hasMore && !settling && (
          <tr>
            <td colSpan={7} className="py-6 text-center text-slate-400">
              Тушаал олдсонгүй
            </td>
          </tr>
        )}
        {hasMore && (
          <tr data-more-row>
            <td colSpan={7} className="px-4 py-3 text-center">
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
  );
}
