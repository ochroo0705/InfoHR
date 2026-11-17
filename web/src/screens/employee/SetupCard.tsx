import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";

// Port of `_setup.html` (the «Бүрдүүлэлт» card): a collapsible card with the checklist items and a progress bar. The
// card is open while incomplete. Classes, Mongolian text, element order and ids are copied from the template. React
// renders the numbers, texts and flags the API sends (done, progress_text, percent, complete, items' note, auto).
// Ticking an item is a write: it opens the Django employee page (openLegacyEmployee, ruling D2). A system item (auto)
// is a disabled checkbox.

type Setup = NonNullable<EmployeeHeadOut["setup"]>;
type Item = Setup["items"][number];

function SetupItem({ item, pk }: { item: Item; pk: number }) {
  return (
    <li>
      <label
        className={`flex items-center gap-3 px-4 py-2.5 text-sm ${item.auto ? "cursor-default" : "hover:bg-slate-50"}`}
      >
        <input
          type="checkbox"
          className="peer sr-only"
          checked={item.done}
          disabled={item.auto}
          onChange={() => openLegacyEmployee(pk)}
        />
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 peer-focus-visible:ring-2 peer-focus-visible:ring-violet-500 ${
            item.done ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-300 bg-surface"
          }${item.auto ? " opacity-70" : ""}`}
        >
          {item.done && (
            <svg
              viewBox="0 0 20 20"
              width="12"
              height="12"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 10.5l3 3 7-7" />
            </svg>
          )}
        </span>
        <span className={item.done ? "text-slate-500" : "font-medium text-slate-800"}>{item.label}</span>
        {item.auto && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500" title="Систем өөрөө тэмдэглэнэ">
            автоматаар
          </span>
        )}
        {item.note && <span className="ml-auto text-xs text-slate-400">{item.note}</span>}
      </label>
    </li>
  );
}

export function SetupCard({ setup, pk }: { setup: Setup | null; pk: number }) {
  if (setup === null) return null;
  const complete = setup.complete;
  return (
    <div id="setup" className="mb-6">
      <details
        className={`group card-hover overflow-hidden rounded-xl border border-l-4 border-slate-200 ${
          complete ? "border-l-emerald-500" : "border-l-amber-500"
        } bg-surface`}
        open={!complete}
      >
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
          {complete ? (
            <>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
                <svg
                  viewBox="0 0 20 20"
                  width="14"
                  height="14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M5 10.5l3 3 7-7" />
                </svg>
              </span>
              <span className="text-sm font-semibold text-emerald-800">Бүрдүүлэлт дууссан</span>
            </>
          ) : (
            <>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-100 text-xs font-bold text-amber-800">
                {setup.done}
              </span>
              <span className="text-sm font-semibold text-slate-700">Бүрдүүлэлт</span>
              <span className="text-sm text-slate-500">{setup.progress_text}</span>
            </>
          )}
          <span className="ml-auto hidden h-1.5 w-28 overflow-hidden rounded-full bg-slate-100 sm:block">
            <span
              className={`block h-full rounded-full ${complete ? "bg-emerald-500" : "bg-amber-500"} transition-all`}
              style={{ width: `${setup.percent}%` }}
            />
          </span>
          <svg
            viewBox="0 0 20 20"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            className="shrink-0 text-slate-400 transition-transform group-open:rotate-180"
            aria-hidden="true"
          >
            <path d="M5 8l5 5 5-5" />
          </svg>
        </summary>
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {setup.items.map((item) => (
            <SetupItem key={item.key} item={item} pk={pk} />
          ))}
        </ul>
      </details>
    </div>
  );
}
