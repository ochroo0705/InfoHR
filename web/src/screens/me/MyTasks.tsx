import { useState } from "react";
import { useTick, type MeOut } from "../../api/me";
import { AppLink } from "../../lib/AppLink";
import { formErrorText } from "./formErrorText";

// «Миний даалгавар»: the user's own open checklist tasks (me.html + checklists/_my_tasks.html). Shown only when there are tasks.
export function MyTasks({ tasks }: { tasks: MeOut["tasks"] }) {
  const tick = useTick();
  const [error, setError] = useState<string | null>(null);
  if (tasks.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="sec-title mb-2">
        <AppLink to="/checklists/mine/" className="hover:underline">
          Миний даалгавар
        </AppLink>{" "}
        <span className="text-sm font-normal text-slate-500">{tasks.length}</span>
      </h2>
      <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
        {tasks.map((t) => (
          <li key={t.id} className="flex items-center justify-between gap-3 px-4 py-3">
            <span className="min-w-0">
              <span className="block font-medium">{t.title}</span>
              <span className="block text-sm text-slate-500">
                {t.employee} · <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">{t.kind_label}</span>
              </span>
              <span className={`block text-sm ${t.overdue ? "font-medium text-red-700" : "text-slate-500"}`}>
                Хугацаа {t.due}
              </span>
            </span>
            {t.can_tick ? (
              <div className="shrink-0">
                <button
                  type="button"
                  disabled={tick.isPending}
                  onClick={() =>
                    tick.mutate(t.id, {
                      onSuccess: () => setError(null),
                      onError: (e) => setError(formErrorText(e) || null),
                    })
                  }
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
                >
                  Хийгдсэн
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </section>
  );
}
