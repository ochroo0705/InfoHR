import { usePageFormState } from "./PageForm";

// Port of the `#save-bar` markup in app/employees/templates/employees/detail.html (classes, the Mongolian texts and the
// button order are copied). It shows while the page form has unsaved changes or the last save left errors, and hides
// otherwise (the `hidden` class, as the template toggles it). The form-wide errors sit inside the bar above its row:
// the bar is the sticky element, so the errors stay in view with the buttons. Only while there are form-wide errors
// does the bar get flex-wrap, so the full-width error box can take its own line; without them the bar is Django's
// exact flex row (no wrap), so the text and the buttons lay out as in the template at phone width.
export function SaveBar() {
  const form = usePageFormState();
  const visible = form.dirty || form.failed;
  return (
    <div
      id="save-bar"
      className={`${visible ? "flex" : "hidden"} sticky bottom-0 z-40 mt-6 items-center justify-end gap-2 rounded-xl border-2 border-violet-500 bg-violet-50 p-3 shadow-[0_-8px_24px_rgba(15,23,42,0.18)]${form.formErrors.length > 0 ? " flex-wrap" : ""}`}
    >
      {form.formErrors.length > 0 ? (
        <div className="basis-full">
          <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
            {form.formErrors.map((message, i) => (
              <p key={i}>{message}</p>
            ))}
          </div>
        </div>
      ) : null}
      <span className="mr-auto flex items-center gap-2 text-sm font-medium text-violet-900">
        <span className="h-2 w-2 rounded-full bg-violet-600"></span>Хадгалаагүй өөрчлөлт байна
      </span>
      <button
        type="button"
        id="save-cancel"
        disabled={form.saving}
        onClick={form.cancel}
        className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
      >
        Болих
      </button>
      {/* The submit button of the page's form (PageFormElement): its submit saves the page form, as Django's form="emp-form". */}
      <button
        type="submit"
        form="emp-form"
        disabled={form.saving}
        className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
      >
        Хадгалах
      </button>
    </div>
  );
}
