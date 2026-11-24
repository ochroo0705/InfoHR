import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useDeleteEntry, useListForm, useSaveEntry, type ListFieldOut, type ListValues } from "../../api/lists";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The add and edit pop-up of one lookup-list entry (port of app/lists/templates/lists/_entry_form.html). Labels, the ` *`
// marks, the buttons and their classes are copied from the template. The fields, their kinds, the choices (the blank
// choice is already first) and the title come from the server form (useListForm). A refused write keeps the pop-up open
// with its errors; a saved or deleted entry closes it, and the mutation hooks refresh the list.
// The page mounts this pop-up while it is open, so a new entry or another one is a new mount (no stale edits).

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const DELETE_TEXT = "Энэ бичлэгийг устгах уу?";
// A list of this many choices (blank included) is a typing box, as Select draws it by its own count.
const SEARCH_FROM = 8;

type Errors = Record<string, string[]>;

function baselineOf(fields: ListFieldOut[]): ListValues {
  return Object.fromEntries(fields.map((field) => [field.name, field.value]));
}

export interface EntryFormModalProps {
  slug: string;
  // The entry to edit. Undefined: the add pop-up.
  pk?: number;
  onClose: () => void;
}

export function EntryFormModal({ slug, pk, onClose }: EntryFormModalProps) {
  const query = useListForm(slug, pk, true);
  const saveEntry = useSaveEntry(slug, pk);
  // Only called from the edit pop-up (pk is set there); the add pop-up never shows «Устгах».
  const deleteEntry = useDeleteEntry(slug, pk ?? 0);
  const data = query.data;

  const [edits, setEdits] = useState<ListValues>({});
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);

  const baseline = data === undefined ? {} : baselineOf(data.fields);
  const valueOf = (name: string): string => edits[name] ?? baseline[name] ?? "";
  const dirty = Object.keys(edits).some((name) => edits[name] !== baseline[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: formErrors };
  const dirtyNow = dirty || hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: string, value: string) => {
    setEdits((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // A refused write: its field errors under their boxes, its form errors in the red box at the top. A refusal with
  // neither gets the general save message.
  const refuse = (fe: Errors, messages: string[]) => {
    setFieldErrors(fe);
    setFormErrors(messages.length > 0 ? messages : Object.keys(fe).length > 0 ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || data === undefined) return;
    // The in-flight mark is set before the request, so a second Enter or click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      // Every box is posted, an empty one as "".
      const values = Object.fromEntries(data.fields.map((field) => [field.name, valueOf(field.name)]));
      const result = await saveEntry.mutateAsync(values);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
      refuse(result.field_errors, result.form_errors);
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Устгах» asks first; an entry in use is refused and the pop-up stays open with the Django message.
  const remove = async () => {
    if (inFlight.current || pk === undefined) return;
    // The in-flight mark is set before the question, so a second click while it is open asks nothing more.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      if (!(await confirm(DELETE_TEXT))) return;
      const result = await deleteEntry.mutateAsync();
      if (result.ok) {
        closing = true;
        onClose();
        return;
      }
      setFormErrors(result.form_errors.length > 0 ? result.form_errors : [SAVE_FAILED_TEXT]);
    } catch (error) {
      const messages = (error as Partial<ApiFailure>).formErrors ?? [];
      setFormErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
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

  // The control of one field, by the kind the server sends: a select, a number box or a text box.
  const controlOf = (field: ListFieldOut, invalid: true | undefined): ReactNode => {
    if (field.kind === "select") {
      const options = field.choices.map((choice) => ({ value: choice.value, label: choice.label }));
      return (
        <Select
          name={field.name}
          value={valueOf(field.name)}
          onChange={(value) => setField(field.name, value)}
          options={options}
          search={options.length >= SEARCH_FROM}
          required={field.required}
          invalid={invalid}
          className={BOXED}
        />
      );
    }
    if (field.kind === "number") {
      return (
        <input
          type="number"
          name={field.name}
          required={field.required}
          value={valueOf(field.name)}
          aria-invalid={invalid}
          onChange={(event) => setField(field.name, event.target.value)}
          className={BOXED}
        />
      );
    }
    return (
      <input
        type="text"
        name={field.name}
        required={field.required}
        maxLength={field.max_length ?? undefined}
        value={valueOf(field.name)}
        aria-invalid={invalid}
        onChange={(event) => setField(field.name, event.target.value)}
        className={BOXED}
      />
    );
  };

  const showDelete = pk !== undefined && data?.can_delete === true;

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={dirtyNow ? serverErrors : null}
      title={data?.title}
    >
      {data === undefined ? (
        query.isError ? (
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
          <div className="grid gap-3 md:grid-cols-2">
            {data.fields.map((field) => {
              const invalid = (fieldErrors[field.name]?.length ?? 0) > 0 || undefined;
              return (
                <label key={field.name} className="block text-sm">
                  {field.label}
                  {field.required ? " *" : null}
                  {controlOf(field, invalid)}
                  {errorsOf(field.name)}
                </label>
              );
            })}
          </div>
          <div className="flex items-center gap-2 pt-2">
            {showDelete ? (
              <button
                type="button"
                disabled={pending}
                onClick={() => void remove()}
                className="mr-auto rounded px-2 py-1 text-red-600 hover:bg-red-50"
              >
                Устгах
              </button>
            ) : null}
            <button
              type="button"
              onClick={cancel}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
            >
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
