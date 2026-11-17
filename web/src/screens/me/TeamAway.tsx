import type { MeOut } from "../../api/me";

// «Багийн чөлөө»: who in the user's team is away (manager only). One line per person, max 8 then «+N».
export function TeamAway({ hasTeam, teamAway }: { hasTeam: boolean; teamAway: MeOut["team_away"] }) {
  if (!hasTeam) return null;
  const more = teamAway.length - 8;
  return (
    <section className="mt-6" data-team-away>
      <h2 className="sec-title mb-2">Багийн чөлөө</h2>
      {teamAway.length > 0 ? (
        <>
          <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
            {teamAway.slice(0, 8).map((a, i) => (
              <li key={`${a.full_name}-${a.start}-${i}`} className="px-4 py-3 text-sm">
                {a.full_name} · {a.start} – {a.end}
              </li>
            ))}
          </ul>
          {more > 0 ? <p className="mt-2 text-sm text-slate-500">+{more}</p> : null}
        </>
      ) : (
        <p className="rounded-xl bg-surface px-4 py-3 text-sm text-slate-500 shadow-sm">
          Ойрын 14 хоногт чөлөөтэй хүн алга.
        </p>
      )}
    </section>
  );
}
