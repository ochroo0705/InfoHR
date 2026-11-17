import { useState } from "react";
import { useAway, type TodayOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { NAME_LINK_CLASS, NameRows } from "./NameRows";

type Strip = TodayOut["strip"];

// Shade classes of the away strip, copied from SHADE_CLASSES in app/employees/services/today_page.py.
const SHADE: Record<string, string> = {
  off: "bg-slate-100 text-slate-400",
  zero: "bg-sky-50 text-slate-500",
  low: "bg-sky-200",
  mid: "bg-sky-400",
  high: "bg-sky-600 text-white",
};

// The «Чөлөөтэй» strip of the Today page (`_today_strip.html`, the away part). Renders nothing without the leave right.
// A click on a counted day picks it; its names come from useAway and show under the strip (`_today_away.html`).
export function AwayStrip({ strip }: { strip: Strip }) {
  const [selected, setSelected] = useState<string | null>(null);
  const away = useAway(selected);

  if (!strip.show_leave) return null;

  return (
    <section className="card-soft p-4" data-away-strip="" aria-labelledby="away-title">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="away-title" className="sec-title">
          Чөлөөтэй
        </h2>
        <span className="text-xs text-slate-500">
          {strip.first} – {strip.last}
        </span>
        <AppLink to="/leave/calendar/" className="ml-auto text-xs text-violet-700 hover:underline">
          Бүтэн хуанли →
        </AppLink>
      </div>
      <div className="grid grid-cols-7 gap-1 sm:grid-cols-14">
        {strip.cells.map((c) => {
          const shade = SHADE[c.shade] ?? SHADE.off;
          const ring = c.is_today ? " ring-2 ring-violet-600" : "";
          const today = c.is_today ? "" : undefined;
          if (!c.clickable) {
            return (
              <div
                key={c.day}
                className={`rounded-md px-1 py-1.5 text-center text-xs leading-tight ${shade}${ring}`}
                title={c.holiday || undefined}
                data-today={today}
              >
                <span className="block font-semibold">{c.num}</span>
                <span className="block text-slate-600">{c.weekday}</span>
              </div>
            );
          }
          const label = `${c.day}: ${c.count} хүн чөлөөтэй`;
          return (
            <button
              key={c.day}
              type="button"
              onClick={() => setSelected(c.day)}
              aria-label={label}
              title={label}
              className={`rounded-md px-1 py-1.5 text-center text-xs leading-tight hover:ring-2 hover:ring-violet-300 ${shade}${ring}`}
              data-today={today}
            >
              <span className="block font-semibold">{c.num}</span>
              <span className="block tabular-nums">{c.count}</span>
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-sm text-slate-700" data-away-today="">
        {strip.today_line}
      </p>
      <div id="away-names" className="mt-2" aria-live="polite">
        {selected !== null && away.data !== undefined ? (
          <>
            <h3 className="mb-1 text-xs font-medium text-slate-500" data-away-day="">
              {selected}
            </h3>
            <NameRows
              rows={away.data.people.map((p) => ({
                id: p.id,
                left: (
                  <AppLink to={`/employees/${p.id}/`} className={NAME_LINK_CLASS}>
                    {p.full_name}
                  </AppLink>
                ),
                right: `${p.label} · ${p.until} хүртэл`,
              }))}
              empty="Энэ өдөр чөлөөтэй хүн алга."
              rightClass="text-right text-slate-500"
            />
          </>
        ) : null}
      </div>
    </section>
  );
}
