import { useState, type SyntheticEvent } from "react";
import type { GroupOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { AttentionChip } from "./AttentionChip";
import type { ToggleHandler } from "./AttentionItem";
import { AttentionMore, GapPeople } from "./AttentionMore";

const CHEVRON_PATH =
  "M5.2 7.2a.75.75 0 0 1 1.06 0L10 10.94l3.74-3.74a.75.75 0 1 1 1.06 1.06l-4.27 4.27a.75.75 0 0 1-1.06 0L5.2 8.26a.75.75 0 0 1 0-1.06Z";

// The «Өгөгдөл дутуу» box inside Анхаарах (the gaps block of `_attention.html`). Folded by default; `total` is the
// number of items in all gap groups, shown in the header. Renders nothing when there are no gap groups.
export function AttentionGaps({
  groups,
  total,
  onToggle,
}: {
  groups: GroupOut[];
  total: number;
  onToggle: ToggleHandler;
}) {
  if (groups.length === 0) return null;

  return (
    <details data-attention-gaps className="group/gaps rounded-lg border-l-4 border-slate-300 bg-surface/70 py-2 pl-3 pr-2">
      <summary className="group/head flex min-h-7 cursor-pointer list-none items-center gap-2 select-none">
        <h3 className="font-medium text-slate-700">Өгөгдөл дутуу</h3>
        <span className="text-xs text-slate-500">{total}</span>
        <svg
          className="ml-auto h-4 w-4 shrink-0 text-slate-400 transition-transform group-open/gaps:rotate-180"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path fillRule="evenodd" d={CHEVRON_PATH} clipRule="evenodd" />
        </svg>
      </summary>
      <ul className="mt-1.5 space-y-1">
        {groups.map((group) => (
          <AttentionGapRow key={`${group.kind}:${group.urgency}`} group={group} onToggle={onToggle} />
        ))}
      </ul>
    </details>
  );
}

// One gap group (`<li data-attention-gap>`). With an employee: a row whose own <details> loads the people on its first
// open (htmx `toggle once`), with «Бүгдийг нээх →» and «Бүгдийг мэдлээ» beside it. Without one: the chips inline.
function AttentionGapRow({ group, onToggle }: { group: GroupOut; onToggle: ToggleHandler }) {
  // Turns true on the row's first open and stays true, so the people load once (htmx `toggle once`).
  const [opened, setOpened] = useState(false);
  const label = `${group.label} · ${group.count}`;
  const hasEmployee = group.shown[0]?.employee != null;

  const onDetailsToggle = (e: SyntheticEvent<HTMLDetailsElement>) => {
    if (e.currentTarget.open) setOpened(true);
  };

  if (!hasEmployee) {
    return (
      <li data-attention-gap data-kind={group.kind} className="text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-700">{label}</span>
          {group.shown.map((item) => (
            <AttentionChip key={item.key} item={item} onToggle={onToggle} />
          ))}
          {group.more > 0 ? <AttentionMore group={group} onToggle={onToggle} /> : null}
        </div>
      </li>
    );
  }

  return (
    <li data-attention-gap data-kind={group.kind} className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <details onToggle={onDetailsToggle} className="group/gap min-w-0 flex-1">
          <summary className="flex min-h-7 cursor-pointer list-none items-center gap-2 select-none">
            <span className="font-medium text-slate-700">{label}</span>
            <svg
              className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open/gap:rotate-180"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path fillRule="evenodd" d={CHEVRON_PATH} clipRule="evenodd" />
            </svg>
          </summary>
          <div data-gap-people aria-live="polite" className="mt-1.5 flex flex-wrap gap-1.5">
            <GapPeople group={group} onToggle={onToggle} enabled={opened} />
          </div>
        </details>
        {group.url ? (
          <AppLink to={group.url} className="rounded px-2 py-0.5 text-xs text-violet-700 hover:underline">
            Бүгдийг нээх →
          </AppLink>
        ) : null}
        {group.count > 1 ? (
          <button
            type="button"
            onClick={() => onToggle(group.keys, "dismiss_all")}
            className="min-h-7 rounded px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            title="Энэ бүлгийг надад дахин харуулахгүй — өөрчлөгдвөл дахин гарна"
          >
            Бүгдийг мэдлээ
          </button>
        ) : null}
      </div>
    </li>
  );
}
