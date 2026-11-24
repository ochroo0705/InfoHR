import { ScrollHost } from "../../widgets/Scrollbar";
import { useRef } from "react";
import type { LogSystemRowOut } from "../../api/logs";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { cn } from "../../lib/utils";
import { ChangeList } from "./ChangeList";

// The rows of the system log (_system_rows.html and _system_items.html). Classes, Mongolian text and element order are
// copied from the templates. React decides nothing: the date and time text, the actor text, the category and action
// labels, the target type and the ip all come from the API as given. Rows lead nowhere, so they have no hover class and
// no click handler (UI_RULES §4).

const COL_SPAN = 7;

export interface SystemLogTableProps {
  rows: LogSystemRowOut[];
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  // True while the rows on screen are the last settled ones of an older address: no empty-row message is drawn then.
  settling?: boolean;
  // False keeps the pill from loading by scrolling into view (after a failed batch); its click still calls onMore.
  autoLoad?: boolean;
}

export function SystemLogTable({
  rows,
  hasMore,
  loadingMore,
  onMore,
  settling = false,
  autoLoad = true,
}: SystemLogTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && autoLoad);

  return (
    <ScrollHost fit className="ptable ptable-fit card-soft">
      <table>
        <thead>
          <tr>
            <th>Огноо</th>
            <th>
              Хэн
              <span className="block w-36 whitespace-normal text-xs font-normal text-slate-400">
                Нэвтрэх нэр (буруу оруулсан байж болно)
              </span>
            </th>
            <th>Ангилал</th>
            <th>Үйлдэл</th>
            <th className="min-w-40">Зорилт</th>
            <th className="w-full">Дэлгэрэнгүй</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="align-top">
              <td className="whitespace-nowrap">
                {row.date} <span className="text-xs text-slate-400">{row.time}</span>
              </td>
              <td className="whitespace-nowrap">{row.actor_name}</td>
              <td className="whitespace-nowrap">{row.category_label}</td>
              <td className="whitespace-nowrap">{row.action_label}</td>
              <td>
                {row.target_type && <span className="block text-xs text-slate-500">{row.target_type}</span>}
                {row.target_label}
              </td>
              <td>
                <p className="text-slate-700">{row.message}</p>
                <ChangeList changes={row.changes} />
              </td>
              <td className="whitespace-nowrap text-slate-600">{row.ip}</td>
            </tr>
          ))}
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
