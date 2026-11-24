import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMeaning, useSaveMeaning, type ListMeaningOut, type ListValues } from "../../api/lists";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { Select } from "../../widgets/Select";

// Port of app/lists/templates/lists/meaning.html: the «Утгын холбоо» page at /lists/meaning/. Classes, texts and order
// are copied from the template. The rows (labels, hints, options, current choice) come from the API. Saving posts every
// value at once; the page then shows the fresh server values and a short «Хадгалагдлаа» note (Django shows none).
const PAGE_TITLE = "Утгын холбоо";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const BLANK = "— сонгоогүй —";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const SAVE_FAILED = "Серверийн алдаа гарлаа. Дахин оролдоно уу.";
const SAVED = "Хадгалагдлаа";
// Search box shows only from this many options (select.js rule); fewer options use the plain select.
const SEARCH_FROM = 8;

// The values the server holds: each row's current entry pk as text, "" when none.
function valuesOf(data: ListMeaningOut | undefined): ListValues {
  const out: ListValues = {};
  for (const row of data?.rows ?? []) out[row.key] = row.current === null ? "" : String(row.current);
  return out;
}

export function MeaningPage() {
  const query = useMeaning();
  const save = useSaveMeaning();
  // The user's picks not yet saved; null shows the server values.
  const [draft, setDraft] = useState<ListValues | null>(null);
  const [saved, setSaved] = useState(false);
  const serverValues = useMemo(() => valuesOf(query.data), [query.data]);
  const values = draft ?? serverValues;

  useEffect(() => {
    const previous = document.title;
    document.title = PAGE_TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (query.isError && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (query.data === undefined) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }
  const rows = query.data.rows;

  function change(key: string, value: string) {
    setDraft({ ...values, [key]: value });
    setSaved(false);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(false);
    try {
      // The save refetches the meanings before it resolves, so the server values are fresh when the draft is dropped.
      const result = await save.mutateAsync(values);
      if (result.ok) {
        setDraft(null);
        setSaved(true);
      }
    } catch {
      // The alert below shows the failure; the picks stay on screen.
    }
  }

  return (
    <>
      <div className="flex items-center gap-3">
        <AppLink to="/lists/" className="text-sm text-violet-700 hover:underline">
          ← Жагсаалтууд
        </AppLink>
        <h1 className="mr-auto text-xl font-semibold">{PAGE_TITLE}</h1>
      </div>
      <form onSubmit={onSubmit} className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-surface p-6">
        {rows.map((row) => (
          <label key={row.key} className="block text-sm">
            {row.label}
            <span className="block text-xs text-slate-500">{row.hint}</span>
            <Select
              name={row.key}
              value={values[row.key] ?? ""}
              onChange={(value) => change(row.key, value)}
              options={[
                { value: "", label: BLANK },
                ...row.options.map((option) => ({ value: String(option.value), label: option.label })),
              ]}
              search={row.options.length >= SEARCH_FROM}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        ))}
        <div className="flex justify-end pt-2">
          <div className="flex flex-col items-end gap-2">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
            >
              Хадгалах
            </button>
            {saved ? (
              <p role="status" className="text-sm text-emerald-700">
                {SAVED}
              </p>
            ) : null}
            {save.isError ? (
              <p role="alert" className="text-sm text-red-600">
                {SAVE_FAILED}
              </p>
            ) : null}
          </div>
        </div>
      </form>
    </>
  );
}
