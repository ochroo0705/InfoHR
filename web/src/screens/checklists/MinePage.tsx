import { useEffect, useState } from "react";
import { useChecklistMine, useTickTask } from "../../api/checklists";
import { useMainWidth } from "../../shell/mainWidth";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { formErrorText } from "../me/formErrorText";
import { MyTaskRow } from "./MyTaskRow";

// Port of app/checklists/templates/checklists/mine.html (+ _my_tasks.html): «Миний даалгавар» at /checklists/mine/.
// Classes, Mongolian text and the element order are copied from the template. The rows (who may see them, the overdue
// mark) are decided by the API; this page only draws them and posts a tick.
const PAGE_TITLE = "Миний даалгавар";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function MinePage() {
  useMainWidth("max-w-2xl px-4");
  const query = useChecklistMine();
  const tick = useTickTask();
  const [error, setError] = useState<string | null>(null);

  // The page's title, as the lists pages set it; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = PAGE_TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the right gets the forbidden screen; a missing page the not-found screen; anything else the alert.
  const status = (query.error as { status?: number } | null)?.status;
  if (query.isError && (status === 401 || status === 403)) return <Forbidden />;
  if (query.isError && status === 404) return <NotFound />;
  if (query.isError) {
    return (
      <section className="mt-6">
        <p role="alert" className="text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      </section>
    );
  }
  if (!query.data) return null;

  const items = query.data.items;
  return (
    <section className="mt-6">
      <h1 className="sec-title mb-2">
        {PAGE_TITLE} <span className="text-sm font-normal text-slate-500">{items.length}</span>
      </h1>
      {items.length > 0 ? (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl bg-surface shadow-sm">
          {items.map((item) => (
            <MyTaskRow
              key={item.id}
              task={item}
              pending={tick.isPending}
              onTick={() =>
                tick.mutate(item.id, {
                  onSuccess: () => setError(null),
                  onError: (e) => setError(formErrorText(e) || null),
                })
              }
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">Таныг хүлээж буй даалгавар алга.</p>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
