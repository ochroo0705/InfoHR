import { useViews } from "../../api/today";
import { AppLink } from "../../lib/AppLink";

// «Удахгүй болох» (`_today_views.html`). The page mounts it only when show_views is true, so the request is made
// on mount, as the htmx `load` trigger did. Nothing is shown for an empty list or while loading.
export function ViewsBlock() {
  const views = useViews(true);
  const tiles = views.data ?? [];
  if (tiles.length === 0) return null;

  return (
    <section className="card-soft mb-5 p-4" data-today-views aria-labelledby="views-title">
      <h2 id="views-title" className="sec-title mb-2">
        Удахгүй болох
      </h2>
      {tiles.map((tile, index) => (
        // The whole row is the link: the name's link covers the row (after:inset-0), so the caption and the count click too.
        <div
          key={`${tile.url}-${index}`}
          className="relative -mx-2 flex items-baseline justify-between gap-3 rounded-lg border-b border-slate-100 px-2 py-1.5 text-sm transition-colors hover:bg-violet-50 focus-within:bg-violet-50 last:border-0"
        >
          <div className="min-w-0">
            <AppLink to={tile.url} className="break-words text-violet-700 after:absolute after:inset-0 after:content-[''] focus-visible:outline-none">
              {tile.name}
            </AppLink>
            <span className="block text-xs text-slate-500">{tile.report}</span>
          </div>
          <span
            className={`shrink-0 tabular-nums ${tile.count ? "font-semibold text-slate-900" : "text-slate-400"}`}
            data-tile-count
          >
            {tile.count}
          </span>
        </div>
      ))}
    </section>
  );
}
