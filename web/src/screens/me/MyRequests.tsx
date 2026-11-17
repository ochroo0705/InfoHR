import { useState } from "react";
import { useWithdraw, type MeOut } from "../../api/me";
import { confirm } from "../../widgets/confirm";
import { formErrorText } from "./formErrorText";

// The badge colour by tone (me.html's branches: a shown state is muted, then the request's own status).
const BADGE_BY_TONE: Record<string, string> = {
  muted: "bg-slate-100 text-slate-600",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-700",
  waiting: "bg-amber-100 text-amber-800",
};

// «Миний хүсэлтүүд»: the user's own leave requests, with «Буцаах» on a waiting one (me.html).
export function MyRequests({ requests }: { requests: MeOut["requests"] }) {
  const withdraw = useWithdraw();
  const [error, setError] = useState<string | null>(null);

  // Asks first; a refusal (409) shows as a red line in #me-error, never a second pop-up.
  async function askWithdraw(pk: number) {
    if (withdraw.isPending) return;
    const ok = await confirm("Хүсэлтээ буцаах уу?");
    if (!ok) return;
    withdraw.mutate(pk, {
      onSuccess: () => setError(null),
      onError: (e) => setError(formErrorText(e) || null),
    });
  }

  return (
    <section className="mt-6">
      <h2 className="sec-title mb-2">Миний хүсэлтүүд</h2>
      {requests.length > 0 ? (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
          {requests.map((r) => (
            <li key={r.id} className="px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium">{r.leave_type}</div>
                  <div className="text-sm text-slate-500">
                    {r.start} – {r.end} · {r.working_days} өдөр
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE_BY_TONE[r.tone] ?? BADGE_BY_TONE.muted}`}
                >
                  {r.status_label}
                </span>
              </div>
              {r.status === "waiting" && r.rule ? (
                <p className="mt-1 text-xs text-slate-500">Батлах: {r.rule}</p>
              ) : null}
              {r.status === "rejected" && r.reason ? (
                <p className="mt-1 text-sm text-red-700">Шалтгаан: {r.reason}</p>
              ) : null}
              {r.can_withdraw ? (
                <button
                  type="button"
                  disabled={withdraw.isPending}
                  onClick={() => void askWithdraw(r.id)}
                  className="mt-2 text-sm text-red-600 hover:underline"
                >
                  Буцаах
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">Хүсэлт гаргаагүй байна.</p>
      )}
      <div id="me-error" className="mt-2 text-sm">
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
      </div>
    </section>
  );
}
