import type { MeOut } from "../../api/me";

// «Энэ оны бүртгэгдсэн чөлөө»: the leave recorded this year (me.html).
export function Recorded({ recorded }: { recorded: MeOut["recorded"] }) {
  return (
    <section className="mt-6">
      <h2 className="sec-title mb-2">Энэ оны бүртгэгдсэн чөлөө</h2>
      {recorded.length > 0 ? (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
          {recorded.map((lv, i) => (
            <li key={`${lv.leave_type}-${lv.start}-${i}`} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
              <span className="min-w-0">
                {lv.leave_type} · {lv.start} – {lv.end}
              </span>
              <span className="shrink-0 text-slate-600">{lv.days} өдөр</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">Бүртгэгдээгүй</p>
      )}
    </section>
  );
}
