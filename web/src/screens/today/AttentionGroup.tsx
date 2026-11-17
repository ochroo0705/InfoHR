import type { GroupOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { AttentionChip } from "./AttentionChip";
import { AttentionItem, type ToggleHandler } from "./AttentionItem";
import { AttentionMore } from "./AttentionMore";

const CHEVRON_PATH =
  "M5.2 7.2a.75.75 0 0 1 1.06 0L10 10.94l3.74-3.74a.75.75 0 1 1 1.06 1.06l-4.27 4.27a.75.75 0 0 1-1.06 0L5.2 8.26a.75.75 0 0 1 0-1.06Z";

// One Анхаарах group as a closed line (`_attention_group.html`): «label · count», the nearest date for dated groups,
// the chevron, then «Бүгдийг нээх →» (when the kind has a page) and «Бүгдийг мэдлээ» (when there is more than one item).
// Dated groups list one line per item; undated groups show name chips. The group is open only when `group.open`.
export function AttentionGroup({ group, onToggle }: { group: GroupOut; onToggle: ToggleHandler }) {
  const tone =
    group.urgency === 0
      ? { border: "border-red-500", heading: "text-red-700" }
      : group.urgency === 1
        ? { border: "border-amber-400", heading: "text-amber-800" }
        : { border: "border-slate-300", heading: "text-slate-700" };
  const hasDate = group.dated && !!group.nearest;

  return (
    <details
      data-attention-group
      data-kind={group.kind}
      data-urgency={group.urgency}
      open={group.open || undefined}
      className={`group/line rounded-lg border-l-4 bg-surface/70 py-2 pl-3 pr-2 ${tone.border}`}
    >
      <summary className="group/head flex min-h-7 cursor-pointer list-none items-center gap-2 select-none">
        <h3 className={`font-medium ${tone.heading}`}>
          {group.label} · {group.count}
        </h3>
        {hasDate ? <span className="ml-auto whitespace-nowrap text-xs text-slate-500">{group.nearest}</span> : null}
        <svg
          className={`${hasDate ? "" : "ml-auto "}h-4 w-4 shrink-0 text-slate-400 transition-transform group-open/line:rotate-180`}
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path fillRule="evenodd" d={CHEVRON_PATH} clipRule="evenodd" />
        </svg>
      </summary>
      {group.count > 1 || group.url ? (
        <div className="mt-1 flex items-center justify-end gap-2">
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
      ) : null}
      {group.dated ? (
        <ul className="mt-1 space-y-0.5">
          {group.shown.map((item) => (
            <AttentionItem key={item.key} item={item} action="dismiss" onToggle={onToggle} />
          ))}
          {group.more > 0 ? <AttentionMore group={group} onToggle={onToggle} /> : null}
        </ul>
      ) : (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {group.shown.map((item) => (
            <AttentionChip key={item.key} item={item} onToggle={onToggle} />
          ))}
          {group.more > 0 ? <AttentionMore group={group} onToggle={onToggle} /> : null}
        </div>
      )}
    </details>
  );
}
