import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { invalidateListEntries, quickAddEntry, useListForm, type ListFieldOut, type ListValues } from "../../api/lists";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The «шинэ бичлэг» pop-up that adds an entry from a form dropdown when the list needs more than a name (port of
// app/lists/templates/lists/_quick_modal.html; docs/UI_RULES.md §2a). The labels, the ` *` marks, the grid and the
// buttons are copied from the template.
// Only plain LISTS slugs reach this pop-up: a QUICK-only slug (department, position) has no pop-up (its spec.modal is
// false), and the form route answers 404 for it, so the form is never asked for those.
// The typed text goes into the `name` field; `parentValue` goes into the one required select field that is still empty
// (the list's parent, e.g. the city of a district). The server's own rules decide the rest: a 400 carries the field
// errors and the first form error (`error`), a 200 carries the picked entry, `existed` included.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

// The starting values: each field's own value, the typed text in `name`, the parent value in the parent field.
function startingValues(fields: ListFieldOut[], initialName: string, parentValue: string | undefined): ListValues {
  const parentField =
    parentValue === undefined
      ? undefined
      : fields.find((field) => field.kind === "select" && field.required && field.value === "")?.name;
  return Object.fromEntries(
    fields.map((field) => [
      field.name,
      field.name === "name"
        ? initialName
        : field.name === parentField && parentValue !== undefined
          ? parentValue
          : field.value,
    ]),
  );
}

export interface QuickAddModalProps {
  // The plain LISTS slug the entry is added to.
  slug: string;
  // The list's label, for the title.
  label: string;
  // The text typed in the dropdown: the starting value of `name`.
  initialName: string;
  // The value of the list's parent field, when the list has one.
  parentValue?: string;
  // Called with the picked or created entry; `existed` is passed through as the server answered it.
  onDone: (entry: { value: string | number; label: string; existed: boolean }) => void;
  onClose: () => void;
}

export function QuickAddModal({ slug, label, initialName, parentValue, onDone, onClose }: QuickAddModalProps) {
  const queryClient = useQueryClient();
  const form = useListForm(slug, undefined, true);
  // What the user changed. The rest comes from the starting values, so the form keeps the server's own defaults.
  const [edits, setEdits] = useState<ListValues>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);

  const fields = form.data?.fields ?? [];
  const baseline = startingValues(fields, initialName, parentValue);
  const current: ListValues = { ...baseline, ...edits };
  const dirty = Object.keys(edits).some((name) => edits[name] !== baseline[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: formErrors };
  const dirtyNow = dirty || hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: string, value: string) => {
    setEdits((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) =>
      name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev,
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || form.data === undefined) return;
    // The in-flight mark is set before the request, so a second Enter or click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const reply = await quickAddEntry(slug, current);
      if ("error" in reply) {
        setFieldErrors(reply.field_errors);
        setFormErrors([reply.error]);
        return;
      }
      // The guard stays set: the pop-up is closing, and a second Enter must not send again.
      closing = true;
      void invalidateListEntries(queryClient, slug);
      onDone({ value: reply.value, label: reply.label, existed: reply.existed });
      onClose();
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      setFieldErrors(failure.fieldErrors ?? {});
      setFormErrors(failure.formErrors?.length ? failure.formErrors : [SAVE_FAILED_TEXT]);
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty: dirtyNow, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const errorsOf = (name: string): ReactNode =>
    (fieldErrors[name] ?? []).map((message, index) => (
      <span key={index} className="block text-xs text-red-600">
        {message}
      </span>
    ));
  const invalid = (name: string) => (fieldErrors[name]?.length ?? 0) > 0 || undefined;

  const renderField = (field: ListFieldOut) => {
    const mark = field.required ? " *" : "";
    if (field.kind === "select") {
      return (
        <label key={field.name} className="block text-sm">
          {field.label}
          {mark}
          <Select
            name={field.name}
            value={current[field.name] ?? ""}
            onChange={(value) => setField(field.name, value)}
            options={field.choices.map((choice) => ({ value: choice.value, label: choice.label }))}
            className={BOXED}
            invalid={invalid(field.name)}
          />
          {errorsOf(field.name)}
        </label>
      );
    }
    return (
      <label key={field.name} className="block text-sm">
        {field.label}
        {mark}
        <input
          type={field.kind === "number" ? "number" : "text"}
          name={field.name}
          maxLength={field.max_length ?? undefined}
          value={current[field.name] ?? ""}
          aria-invalid={invalid(field.name)}
          onChange={(event) => setField(field.name, event.target.value)}
          className={BOXED}
        />
        {errorsOf(field.name)}
      </label>
    );
  };

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={dirtyNow ? serverErrors : null}
      title={`${label}: шинэ бичлэг`}
    >
      {form.data === undefined ? (
        form.isError ? (
          <p role="alert" className="text-sm text-red-600">
            {LOAD_FAILED_TEXT}
          </p>
        ) : null
      ) : (
        <form noValidate className="space-y-3" onSubmit={submit}>
          {formErrors.length > 0 ? (
            <div className="rounded bg-red-50 p-2 text-sm text-red-700">
              {formErrors.map((message, index) => (
                <p key={index}>{message}</p>
              ))}
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-2">{fields.map(renderField)}</div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
              Болих
            </button>
            <button
              type="submit"
              disabled={pending}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
            >
              Хадгалах
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
