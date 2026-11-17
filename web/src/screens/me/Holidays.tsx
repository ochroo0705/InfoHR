import type { MeOut } from "../../api/me";

// «Баяр ёслол»: the holiday line in its own card (me.html, data-holidays). Max 3 names, then «+N».
export function Holidays({ holidays }: { holidays: MeOut["holidays"] }) {
  if (holidays.length === 0) return null;
  const more = holidays.length - 3;
  const names = holidays
    .slice(0, 3)
    .map((h) => `${h.day} ${h.name}`)
    .join(" · ");
  return (
    <section className="mt-6">
      <p data-holidays className="rounded-xl bg-surface px-4 py-3 text-sm text-slate-700 shadow-sm">
        Баяр ёслол: {names}
        {more > 0 ? ` +${more}` : ""}
      </p>
    </section>
  );
}
