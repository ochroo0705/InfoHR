import { useState } from "react";
import { useAttentionMore, type AttentionMoreOut, type GroupOut, type ItemOut } from "../../api/today";
import { AttentionChip } from "./AttentionChip";
import { AttentionItem, type ToggleHandler } from "./AttentionItem";

const MORE_BUTTON_CLASS =
  "min-h-7 rounded-full border border-slate-300 bg-surface px-2.5 py-0.5 text-xs font-medium text-slate-600 hover:border-violet-300 hover:text-violet-700";
const GAP_BUTTON_CLASS =
  "inline-flex min-h-7 items-center rounded-full border border-slate-300 bg-surface px-2.5 py-0.5 text-xs font-medium text-slate-600 hover:border-violet-300 hover:text-violet-700";

// The items of a loaded answer: lines for a dated group (dismiss actions), name chips for an undated one.
function MoreItems({ dated, items, onToggle }: { dated: boolean; items: ItemOut[]; onToggle: ToggleHandler }) {
  return (
    <>
      {items.map((item) =>
        dated ? (
          <AttentionItem key={item.key} item={item} action="dismiss" onToggle={onToggle} />
        ) : (
          <AttentionChip key={item.key} item={item} onToggle={onToggle} />
        ),
      )}
    </>
  );
}

// «Бүгдийг харах (N) →» of a group (`_attention_more_button.html`, `_attention_more.html`). The first click sends no
// `all`, so the server returns every item past GROUP_LIMIT in one answer, as the template does. Dated group: the button
// sits in `<li data-more>` and the items are `<li>` lines. Undated: the button sits among the chips. Render it only
// when `group.more > 0`. A failed request shows the button again; a click retries.
export function AttentionMore({ group, onToggle }: { group: GroupOut; onToggle: ToggleHandler }) {
  const [requested, setRequested] = useState(false);
  const query = useAttentionMore(requested ? { kind: group.kind, urgency: String(group.urgency) } : null);

  if (query.data) {
    return <MoreItems dated={group.dated} items={query.data.items} onToggle={onToggle} />;
  }

  const button = (
    <button
      type="button"
      data-more-button
      disabled={query.isFetching}
      onClick={() => (requested ? void query.refetch() : setRequested(true))}
      className={MORE_BUTTON_CLASS}
      title="Бүгдийг харуулах"
    >
      Бүгдийг харах ({group.more}) →
    </button>
  );
  return group.dated ? <li data-more>{button}</li> : button;
}

// The missing-data people of one «Өгөгдөл дутуу» row (`_attention.html` gap `<details>`, `_attention_more.html` with
// `all=1`). When `enabled` (the row is opened), it loads the first page (`all=1&offset=0`) as name chips, then
// «+ N бусад →» loads the next offset and appends. Pages already shown are kept: a failed or loading page keeps the
// button (a click while loading does nothing; after a failure a click retries that page).
export function GapPeople({
  group,
  onToggle,
  enabled,
}: {
  group: GroupOut;
  onToggle: ToggleHandler;
  enabled: boolean;
}) {
  // Pages that loaded before the page now requested.
  const [pages, setPages] = useState<AttentionMoreOut[]>([]);
  // The offset of the page requested now.
  const [offset, setOffset] = useState(0);
  const query = useAttentionMore(
    enabled ? { kind: group.kind, urgency: String(group.urgency), all: "1", offset: String(offset) } : null,
  );
  const current = query.data;
  // The button follows the last page that loaded, so it survives a failed or loading request.
  const latest = current ?? pages[pages.length - 1];
  const shown = current ? [...pages, current] : pages;

  const loadNext = () => {
    if (query.isFetching || !enabled) return;
    if (current) {
      setPages((prev) => [...prev, current]);
      setOffset(current.next_offset);
    } else {
      void query.refetch();
    }
  };

  return (
    <>
      {shown.flatMap((page) => page.items).map((item) => (
        <AttentionChip key={item.key} item={item} onToggle={onToggle} />
      ))}
      {latest && latest.more > 0 ? (
        <button
          type="button"
          data-gap-more
          disabled={query.isFetching}
          onClick={loadNext}
          className={GAP_BUTTON_CLASS}
          title="Дараагийн хэсгийг харуулах"
        >
          + {latest.more} бусад →
        </button>
      ) : null}
    </>
  );
}
