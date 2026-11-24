import { useState } from "react";
import type { MeOut } from "../../api/me";
import { RequestDetailModal } from "../leaveRequests/RequestDetailModal";

// «Надад ирсэн хүсэлт»: the leave requests waiting for the user's approval step. Shown only when there are items. A row
// opens the detail pop-up of that request (mounted only while open).
export function Queue({ queue }: { queue: MeOut["queue"] }) {
  // The id of the request whose detail is open. Null: no pop-up.
  const [openId, setOpenId] = useState<number | null>(null);
  if (queue.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="sec-title mb-2">
        Надад ирсэн хүсэлт <span className="text-sm font-normal text-slate-500">{queue.length}</span>
      </h2>
      <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
        {queue.map((q) => (
          <li key={q.id}>
            <button
              type="button"
              onClick={() => setOpenId(q.id)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-violet-50"
            >
              <span className="min-w-0">
                <span className="block font-medium">{q.employee}</span>
                <span className="block text-sm text-slate-500">
                  {q.leave_type} · {q.start} – {q.end}
                </span>
              </span>
              <span className="shrink-0 text-sm text-slate-500">Шат {q.step}</span>
            </button>
          </li>
        ))}
      </ul>
      {openId !== null ? <RequestDetailModal id={openId} onClose={() => setOpenId(null)} /> : null}
    </section>
  );
}
