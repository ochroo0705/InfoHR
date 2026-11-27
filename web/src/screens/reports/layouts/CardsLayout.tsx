import { useRef } from "react";
import { useReportCards, type ReportCardsOut } from "../../../api/reports";
import { useMoreSentinel } from "../../../lib/useMoreSentinel";
import { CardItem } from "./CardItem";

// The cards layout (app/reports/templates/reports/layouts/cards.html, _cards_batch.html): a responsive grid of the rows
// as cards. `first` is the page's own first batch; further batches come from the cards route through the «Цааш харуулах»
// pill, which loads one batch when it scrolls into view (the same pill as the table). `dataUpdatedAt` is the page query's
// time: a page refetch starts the batches again from the new first batch.

export interface CardsLayoutProps {
  reportKey: string;
  query: string; // the address query, sent as typed
  first: ReportCardsOut;
  total: number; // every filtered row, the same as first.total
  dataUpdatedAt?: number;
}

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function CardsLayout({ reportKey, query, first, total, dataUpdatedAt = 0 }: CardsLayoutProps) {
  const cards = useReportCards(reportKey, query, first, dataUpdatedAt);
  const moreRef = useRef<HTMLButtonElement>(null);

  const items = (cards.data?.pages ?? []).flatMap((page) => page.items);
  const hasMore = cards.hasNextPage;
  const loadingMore = cards.isFetchingNextPage;
  const failed = cards.isError;
  // After a failed batch the pill is not loaded by scrolling into view; its click still asks again.
  const onMore = () => {
    if (!loadingMore) void cards.fetchNextPage();
  };
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !failed);

  if (total === 0) {
    return <p className="mt-4 py-6 text-center text-sm text-slate-400">Өгөгдөл олдсонгүй</p>;
  }

  return (
    <>
      {failed ? (
        <p role="alert" className="mt-4 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item, index) => (
          <CardItem key={index} item={item} />
        ))}
        {hasMore ? (
          <div className="col-span-full flex justify-center py-4">
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
          </div>
        ) : null}
      </div>
    </>
  );
}
