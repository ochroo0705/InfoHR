import type { TodayOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { AttentionTile } from "./AttentionTile";

// The three tiles under the shortcuts (`employees/today.html`). Classes, SVG paths and data-tile hooks are verbatim.
export function Tiles({ data }: { data: TodayOut }) {
  return (
    <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
      <AppLink to="/employees/" className="card-soft flex items-center gap-3 p-4">
        <span className="tile-icon bg-violet-100 text-violet-700">
          <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M7 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm6 1a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM1 16a6 6 0 0 1 12 0v1H1v-1Zm13 1v-1a7.9 7.9 0 0 0-1.3-4.4A5 5 0 0 1 19 16v1h-5Z" />
          </svg>
        </span>
        <span>
          <span className="block text-xs text-slate-500">Ажилтан</span>
          <span className="block text-2xl font-semibold leading-tight" data-tile="headcount">
            {data.headcount}
          </span>
        </span>
      </AppLink>

      <div className="card-soft flex items-center gap-3 p-4">
        <span className="tile-icon bg-sky-100 text-sky-700">
          <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M6 2a1 1 0 0 1 1 1v1h6V3a1 1 0 1 1 2 0v1h1a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1V3a1 1 0 0 1 1-1Zm-2 6v8h12V8H4Z" />
          </svg>
        </span>
        <span>
          <span className="block text-xs text-slate-500">Өнөөдөр чөлөөтэй</span>
          <span className="block text-2xl font-semibold leading-tight" data-tile="away">
            {data.away_today}
          </span>
        </span>
      </div>

      <AttentionTile box={data.box} />
    </div>
  );
}
