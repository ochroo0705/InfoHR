import { useEffect, useRef, useState } from "react";
import { useDismissNotice, type MeOut } from "../../api/me";
import { usePresence } from "../../lib/presence";

// The result notices at the top of `me.html` (one `data-notice` row each). «Мэдлээ» sends the notice's key; the row
// plays its exit (usePresence, as other removed rows do) once the server has accepted it. A failed dismissal keeps it.
type NoticeItem = MeOut["notices"][number];
type Row = { notice: NoticeItem; closing: boolean };

// Rebuilds the rows from a fresh server list without losing the ones still on screen: a row that is closing, or whose
// dismissal is in flight, stays where it was even when the server no longer sends it. Keeps the order of `prev`.
export function mergeRows(prev: Row[], next: NoticeItem[], pending: ReadonlySet<string>): Row[] {
  const fresh = new Map(next.map((n) => [n.key, n]));
  const out: Row[] = [];
  const seen = new Set<string>();
  for (const row of prev) {
    const key = row.notice.key;
    const current = fresh.get(key);
    if (current) {
      out.push({ notice: current, closing: row.closing });
      seen.add(key);
    } else if (row.closing || pending.has(key)) {
      out.push(row);
      seen.add(key);
    }
  }
  for (const n of next) {
    if (!seen.has(n.key)) out.push({ notice: n, closing: false });
  }
  return out;
}

export function Notices({ notices }: { notices: NoticeItem[] }) {
  const dismiss = useDismissNotice();
  const [rows, setRows] = useState<Row[]>(() => notices.map((notice) => ({ notice, closing: false })));
  const pending = useRef(new Set<string>());

  useEffect(() => {
    setRows((prev) => mergeRows(prev, notices, pending.current));
  }, [notices]);

  function dismissOne(key: string) {
    if (pending.current.has(key)) return;
    pending.current.add(key);
    dismiss.mutate(
      { key },
      {
        onSuccess: () => {
          pending.current.delete(key);
          setRows((prev) => prev.map((r) => (r.notice.key === key ? { ...r, closing: true } : r)));
        },
        onError: () => {
          // The server still has the notice: keep the row as it was.
          pending.current.delete(key);
        },
      },
    );
  }

  function removeRow(key: string) {
    setRows((prev) => prev.filter((r) => !(r.closing && r.notice.key === key)));
  }

  return (
    <>
      {rows.map((row) => (
        <NoticeRow
          key={row.notice.key}
          notice={row.notice}
          closing={row.closing}
          onDismiss={() => dismissOne(row.notice.key)}
          onGone={() => removeRow(row.notice.key)}
        />
      ))}
    </>
  );
}

function NoticeRow({
  notice,
  closing,
  onDismiss,
  onGone,
}: {
  notice: NoticeItem;
  closing: boolean;
  onDismiss: () => void;
  onGone: () => void;
}) {
  const presence = usePresence(!closing);

  // The exit has finished (or motion is off): drop the row from the list.
  useEffect(() => {
    if (closing && !presence.mounted) onGone();
  }, [closing, presence.mounted, onGone]);

  if (!presence.mounted) return null;

  return (
    <div
      ref={presence.ref}
      data-notice
      data-leaving={presence.leaving ? "" : undefined}
      inert={presence.leaving ? true : undefined}
      className={`mb-3 flex items-start gap-3 rounded-xl border border-slate-200 border-l-4 ${
        notice.approved ? "border-l-emerald-500" : "border-l-red-500"
      } bg-surface p-3 text-sm`}
    >
      <p className="min-w-0 flex-1">{notice.text}</p>
      <div className="shrink-0">
        <button type="button" onClick={onDismiss} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100">
          Мэдлээ
        </button>
      </div>
    </div>
  );
}
