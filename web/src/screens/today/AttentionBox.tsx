import { useCallback, useLayoutEffect, useRef, useState, type SyntheticEvent } from "react";
import { useAttentionToggle, type AttentionBoxOut, type GroupOut } from "../../api/today";
import { AttentionGaps } from "./AttentionGaps";
import { AttentionGroup } from "./AttentionGroup";
import { AttentionItem, type ToggleAction } from "./AttentionItem";

const STORAGE_KEY = "hr.attentionOpen";
const CHEVRON_PATH =
  "M5.2 7.2a.75.75 0 0 1 1.06 0L10 10.94l3.74-3.74a.75.75 0 1 1 1.06 1.06l-4.27 4.27a.75.75 0 0 1-1.06 0L5.2 8.26a.75.75 0 0 1 0-1.06Z";

// Storage can be blocked (private window, cleared site data): a failed read means closed, a failed write is ignored.
function readSavedOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeSavedOpen(open: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, open ? "1" : "0");
  } catch {
    // The choice is not kept; the box still works for this page view.
  }
}

// Colours of the box and its header per tone (`_attention.html`, UI_RULES §7a). The tone comes from box.tone.
const TONE = {
  urgent: {
    box: "border-red-200 bg-red-50/60",
    title: "text-red-900",
    pill: "bg-red-100 text-red-700",
    chevron: "text-red-700",
  },
  soon: {
    box: "border-amber-200 bg-amber-50/60",
    title: "text-amber-900",
    pill: "bg-slate-200 text-slate-600",
    chevron: "text-amber-700",
  },
  calm: {
    box: "border-slate-200 bg-slate-50/60",
    title: "text-slate-800",
    pill: "bg-slate-200 text-slate-600",
    chevron: "text-slate-500",
  },
} as const;

function groupKey(group: GroupOut): string {
  return `${group.kind}:${group.urgency}:${group.count}`;
}

// The Анхаарах box (`_attention.html`, id="attention"). `forceOpen` (Today passes true) opens it and marks it overdue.
// Otherwise it opens when an urgent group exists, or when the user's saved choice is open. The open state is applied
// on each mount of the <details>; between mounts the user's own toggles are not overridden.
export function AttentionBox({ box, forceOpen = false }: { box: AttentionBoxOut; forceOpen?: boolean }) {
  const toggle = useAttentionToggle();
  const boxRef = useRef<HTMLDetailsElement | null>(null);
  // The last open state applied or seen, so the toggle event raised by a programmatic open is not written to storage.
  const lastOpen = useRef(false);
  // Bumped after each toggle answer. The items inside the box re-mount under this key, so every group folds back to
  // its default and the gap rows forget their fetched people. The <details> itself is not re-mounted, so it stays open.
  const [version, setVersion] = useState(0);

  const overdue = forceOpen || box.urgent.length > 0;
  const hasShown = box.urgent.length + box.soon.length + box.gaps.length > 0;
  const hasHidden = box.hidden.length > 0;
  const tone = TONE[box.tone as keyof typeof TONE] ?? TONE.calm;

  // Latest value for the callback ref below, which must keep one identity so React calls it only on mount and unmount.
  const overdueRef = useRef(overdue);
  overdueRef.current = overdue;

  // Applies the initial open state each time the <details> mounts (the box is null when nothing is shown, so it can
  // mount again later): forceOpen or urgent items, otherwise the user's saved choice. Runs once per mount, never per
  // render, so the user's own toggles are not overridden.
  const attachBox = useCallback((el: HTMLDetailsElement | null) => {
    boxRef.current = el;
    if (!el) return;
    const open = overdueRef.current || readSavedOpen();
    lastOpen.current = open;
    el.open = open;
  }, []);

  // After a toggle answer, an overdue box opens again, as the Django page re-renders it open.
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (version === 0 || !el || !overdueRef.current) return;
    lastOpen.current = true;
    el.open = true;
  }, [version]);

  const onBoxToggle = (e: SyntheticEvent<HTMLDetailsElement>) => {
    const open = e.currentTarget.open;
    if (open === lastOpen.current) return;
    lastOpen.current = open;
    writeSavedOpen(open);
  };

  const onToggle = (keys: string[], action: ToggleAction) =>
    toggle.mutate({ keys, action }, { onSuccess: () => setVersion((v) => v + 1) });

  if (!hasShown && !hasHidden) return null;

  return (
    <div id="attention">
      <details
        ref={attachBox}
        id="attention-box"
        data-tone={box.tone}
        data-overdue={overdue ? "" : undefined}
        onToggle={onBoxToggle}
        className={`group/box mb-4 rounded-xl border text-sm text-slate-800 ${tone.box}`}
      >
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 select-none">
          <h2 className={`font-semibold ${tone.title}`}>Анхаарах</h2>
          <span className={`rounded-full px-2 text-xs font-semibold ${tone.pill}`}>{box.urgent_count}</span>
          <span className="text-xs text-slate-500">
            + {box.soon_count} удахгүй · {box.gap_count} дутуу
          </span>
          <svg
            className={`ml-auto h-4 w-4 transition-transform group-open/box:rotate-180 ${tone.chevron}`}
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path fillRule="evenodd" d={CHEVRON_PATH} clipRule="evenodd" />
          </svg>
        </summary>
        <div key={version} className="space-y-2 px-4 pb-3">
          {box.urgent.map((group) => (
            <AttentionGroup key={groupKey(group)} group={group} onToggle={onToggle} />
          ))}
          {box.soon.map((group) => (
            <AttentionGroup key={groupKey(group)} group={group} onToggle={onToggle} />
          ))}
          {!hasShown ? <p className="text-amber-800">Шинэ зүйл алга.</p> : null}
          <AttentionGaps groups={box.gaps} total={box.gap_count} onToggle={onToggle} />
          {hasHidden ? (
            <details className="pt-1 text-slate-500">
              <summary className="cursor-pointer list-none text-xs hover:underline">
                Нуусан ({box.hidden.length})
              </summary>
              <ul className="mt-1 space-y-0.5 opacity-75">
                {box.hidden.map((item) => (
                  <AttentionItem key={item.key} item={item} action="restore" onToggle={onToggle} />
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </details>
    </div>
  );
}
