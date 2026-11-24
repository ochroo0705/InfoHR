import { useState } from "react";
import { useTick, type MeOut } from "../../api/me";
import { AppLink } from "../../lib/AppLink";
import { MyTaskRow } from "../checklists/MyTaskRow";
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
          <MyTaskRow
            key={t.id}
            task={t}
            pending={tick.isPending}
            onTick={
              t.can_tick
                ? () =>
                    tick.mutate(t.id, {
                      onSuccess: () => setError(null),
                      onError: (e) => setError(formErrorText(e) || null),
                    })
                : undefined
            }
          />
        ))}
      </ul>
      {error ? <p className="mt-2 text-sm text-red-700">{error}</p> : null}
    </section>
  );
}
