import type { MeOut } from "../../api/me";

// «Ээлжийн амралт»: the leave balance of the current and upcoming periods (me.html). Three states, then the «nowhere» line.
export function Balance({ balance }: { balance: MeOut["balance"] }) {
  return (
    <section className="mt-6">
      <h2 className="sec-title mb-2">Ээлжийн амралт</h2>
      {balance.start_missing ? (
        <p className="text-sm text-amber-700">
          Ажилд орсон огноо бүртгэлгүй тул ээлжийн амралтыг тооцох боломжгүй.
        </p>
      ) : !balance.configured ? (
        <p className="text-sm text-slate-500">Ээлжийн амралтын төрөл тохируулаагүй байна.</p>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
          {!balance.started ? (
            <li className="px-4 py-3 text-sm text-slate-400">Ажлын жил эхлээгүй байна.</li>
          ) : (
            balance.periods.map((p) => (
              <li key={p.start} className="flex items-center justify-between gap-3 px-4 py-3">
                <span className="min-w-0">
                  <span className="block font-medium">
                    {p.start} – {p.end}
                    {p.current ? (
                      <span className="ml-1 rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-900">
                        Одоо
                      </span>
                    ) : (
                      <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">Ирэх</span>
                    )}
                  </span>
                  <span className="block text-xs text-slate-500">
                    Эрх {p.granted} · Авсан {p.taken} ·{" "}
                    <span className={`font-semibold ${p.negative ? "text-red-700" : "text-slate-700"}`}>
                      Үлдэгдэл {p.left} хоног
                    </span>
                  </span>
                </span>
              </li>
            ))
          )}
        </ul>
      )}
      {balance.nowhere > 0 ? (
        <p className="mt-2 text-sm text-amber-700">
          Эрхийн хугацаагүй чөлөө: {balance.nowhere}
          <span className="block text-xs text-slate-500">Энэ огноонд амралтын эрх бүртгэгдээгүй.</span>
        </p>
      ) : null}
    </section>
  );
}
