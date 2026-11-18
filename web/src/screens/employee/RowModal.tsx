import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  useAddRow,
  useDeleteRow,
  useEditRow,
  useRowForm,
  type EmployeeFormOut,
  type EmployeeWriteResultOut,
  type RowFormOverrides,
} from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { AppLink } from "../../lib/AppLink";
import { useUnsavedFlag } from "../../lib/unsaved";
import { confirm } from "../../widgets/confirm";
import {
  FormFields,
  initialValue,
  toPostValues,
  useFormValues,
  type FormField,
  type FormValues,
} from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The pop-up of one row of a pop-up list (`_personal_row_form.html` and `_personal_delete.html`): the add form (rowKey
// null) or the edit form of row `rowKey`, with «Устгах» (edit only) that opens the delete confirm. Classes and Mongolian
// text are copied from those templates. The form is loaded once the pop-up is open; the typed values are kept over a
// refetch (useFormValues). Only the address's city change refetches with overrides: the districts follow the city, so
// the typed district is dropped and the typed street is kept (`_personal_modal`, the city's hx-get).
// The parent keeps this component mounted while `open` goes false, so the Modal plays its exit; the parent remounts it
// (new key) for each new open, so an old edit never shows in a new pop-up.

const NO_FIELDS: FormField[] = [];
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const DELETE_TEXT = "Энэ бичлэгийг устгах уу? Устгасны дараа буцаах боломжгүй.";

export type RowModalProps = {
  pk: number;
  kind: string;
  // null: the add form. Else the key of the row to edit.
  rowKey: number | null;
  open: boolean;
  // Called once the close is allowed. The parent sets open to false.
  onClose: () => void;
};

export function RowModal({ pk, kind, rowKey, open, onClose }: RowModalProps) {
  const isNew = rowKey === null;
  const [overrides, setOverrides] = useState<RowFormOverrides>({});
  const form = useRowForm(pk, kind, rowKey, overrides, open);
  // The last loaded form stays on screen while a refetch runs (a city change), so the pop-up does not blink.
  const [shown, setShown] = useState<EmployeeFormOut | null>(null);
  // The values of the FIRST form this pop-up loaded. A refetch (a city change) moves useFormValues' baseline, so the
  // dirty check compares with this one instead: typed values stay unsaved until the pop-up closes or saves.
  const [first, setFirst] = useState<FormValues | null>(null);
  // The hidden loaded_* snapshot of the FIRST load too: a city refetch returns the row as it is now, which can hold a
  // colleague's edit. The save and the delete post the snapshot this pop-up opened with, so that edit shows as a conflict.
  const [firstHidden, setFirstHidden] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    const data = form.data;
    if (!data) return;
    setShown(data);
    setFirst((prev) => prev ?? Object.fromEntries(data.fields.map((f) => [f.name, initialValue(f)])));
    setFirstHidden((prev) => prev ?? data.hidden);
  }, [form.data]);

  const fieldList = shown?.fields ?? NO_FIELDS;
  const fields = useFormValues(fieldList, kind + "/" + (rowKey ?? "new"));
  // The one dirty flag: the Modal's dirty prop, «Болих», and the unsaved registry all read it.
  const dirtyNow =
    first !== null && Object.entries(first).some(([name, value]) => (fields.values[name] ?? "") !== value);

  const addRow = useAddRow(pk, kind);
  const editRow = useEditRow(pk, kind, rowKey ?? 0);
  const deleteRow = useDeleteRow(pk, kind, rowKey ?? 0);

  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [errorTick, setErrorTick] = useState(0);
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleteErrors, setDeleteErrors] = useState<string[]>([]);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);

  // The unsaved flag counts only while the pop-up is open: a closed one keeps its values for its exit, not as unsaved.
  useUnsavedFlag("list:" + kind, open && dirtyNow);

  // After a refused write the cursor goes to the first box with an error (as InlineRow does).
  useEffect(() => {
    if (errorTick === 0) return;
    const invalid = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    const box = invalid ?? formRef.current?.querySelector<HTMLElement>("input:not([type=hidden]), textarea");
    box?.focus();
  }, [errorTick]);

  // A refused write: its field errors under their boxes, its form errors in the red box. When the refusal names no box
  // and gives no form error, the red box gets the general save message.
  const refuse = (fieldErrs: Record<string, string[]>, messages: string[]) => {
    const names = new Set(fieldList.map((field) => field.name));
    const boxNamed = Object.keys(fieldErrs).some((name) => names.has(name));
    setErrors(fieldErrs);
    setFormErrors(messages.length > 0 ? messages : boxNamed ? [] : [SAVE_FAILED_TEXT]);
    setErrorTick((tick) => tick + 1);
  };

  const onFieldChange = (name: string, value: string) => {
    if (kind === "address" && name === "city" && value !== fields.values.city) {
      // The districts belong to the city: the typed district is dropped, the typed street is kept, and the form is
      // loaded again for the new city.
      fields.set("district", "");
      setOverrides({ city: value, district: "", street: fields.values.street ?? "" });
    }
    fields.set(name, value);
    // Typing drops that box's error; the next save decides it afresh.
    setErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // Enter in a box, or «Хадгалах»: an add posts the boxes, an edit posts the boxes with the loaded_* snapshot.
  const submit = async () => {
    if (inFlight.current || !shown || !firstHidden) return;
    if (!isNew && Object.keys(firstHidden).length === 0) {
      refuse({}, []);
      return;
    }
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const values = { ...toPostValues(shown.fields, fields.values), ...firstHidden };
      const result: EmployeeWriteResultOut = isNew
        ? await addRow.mutateAsync({ values })
        : await editRow.mutateAsync({ values });
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        setFormErrors([]);
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

  // «Устгах» in the delete confirm: one delete with the loaded_* snapshot. A refusal keeps both pop-ups open with the message.
  const remove = async () => {
    if (inFlight.current || !shown || !firstHidden || isNew) return;
    if (Object.keys(firstHidden).length === 0) {
      setDeleteErrors([SAVE_FAILED_TEXT]);
      return;
    }
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const result = await deleteRow.mutateAsync({ values: { ...firstHidden } });
      if (result.ok) {
        closing = true;
        setConfirming(false);
        onClose();
        return;
      }
      setDeleteErrors(result.form_errors.length > 0 ? result.form_errors : [SAVE_FAILED_TEXT]);
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      const messages = failure.formErrors ?? [];
      setDeleteErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
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

  const canDelete = !isNew && shown?.can_delete === true;
  const deleteTitle = (shown?.title ?? "").replace(/: засах$/, "") + ": устгах";
  const showing = open && (shown !== null || form.isError);
  const messages = form.isError ? [LOAD_FAILED_TEXT] : formErrors;

  return (
    <>
      <Modal open={showing} onClose={onClose} dirty={dirtyNow} title={shown?.title}>
        {shown ? (
          <form
            ref={formRef}
            noValidate
            className="space-y-3"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              void submit();
            }}
          >
            {messages.length > 0 ? (
              <div className="rounded bg-red-50 p-2 text-sm text-red-700">
                {messages.map((message, index) => (
                  <p key={index}>{message}</p>
                ))}
              </div>
            ) : null}
            {shown.empty_lists.map((item) => (
              <p key={item.slug} className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
                {item.label} жагсаалт хоосон байна.{" "}
                <AppLink to={`/lists/${item.slug}/`} className="text-violet-700 hover:underline">
                  Жагсаалт
                </AppLink>{" "}
                хэсэгт нэмнэ үү.
              </p>
            ))}
            <FormFields
              fields={shown.fields}
              values={fields.values}
              errors={errors}
              onChange={onFieldChange}
              variant="boxed"
            />
            <div className={"flex items-center gap-2 pt-2" + (canDelete ? " justify-between" : " justify-end")}>
              {canDelete ? (
                <button
                  type="button"
                  onClick={() => {
                    setDeleteErrors([]);
                    setConfirming(true);
                  }}
                  className="rounded px-2 py-1 text-red-600 hover:bg-red-50"
                >
                  Устгах
                </button>
              ) : null}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
                  Болих
                </button>
                <button
                  type="submit"
                  disabled={pending}
                  aria-busy={pending || undefined}
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-60"
                >
                  Хадгалах
                </button>
              </div>
            </div>
          </form>
        ) : (
          <>
            <div className="rounded bg-red-50 p-2 text-sm text-red-700">{LOAD_FAILED_TEXT}</div>
            <div className="flex justify-end pt-3">
              <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
                Хаах
              </button>
            </div>
          </>
        )}
      </Modal>
      {canDelete ? (
        <Modal open={confirming} onClose={() => setConfirming(false)} title={deleteTitle} width="max-w-md">
          <p className="text-sm text-slate-700">{DELETE_TEXT}</p>
          <form
            noValidate
            className="mt-4 space-y-3"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              void remove();
            }}
          >
            {deleteErrors.length > 0 ? (
              <div className="rounded bg-red-50 p-2 text-sm text-red-700">
                {deleteErrors.map((message, index) => (
                  <p key={index}>{message}</p>
                ))}
              </div>
            ) : null}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                autoFocus
                onClick={() => setConfirming(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
              >
                Болих
              </button>
              <button
                type="submit"
                disabled={pending}
                aria-busy={pending || undefined}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60"
              >
                Устгах
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </>
  );
}
