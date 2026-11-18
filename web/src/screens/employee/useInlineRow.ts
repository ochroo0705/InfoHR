import { useEffect, useMemo, useRef, useState } from "react";
import {
  useAddRow,
  useDeleteRow,
  useEditRow,
  useRowForm,
  type EmployeeWriteResultOut,
} from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { useUnsavedFlag } from "../../lib/unsaved";
import { toPostValues, useFormValues, type FormField } from "../../widgets/FormFields";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The state of one open inline row (`_inline_row.html`): its form (useRowForm), the typed values, the field errors, the
// save and delete calls, and the unsaved flag "list:<kind>". The row's boxes are the form fields that the list's columns
// name (`column.field`), in column order; a form field no column names is not shown and not posted.

const NO_FIELDS: FormField[] = [];
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

export type InlineRowOptions = {
  pk: number;
  kind: string;
  // "new" for the add row, else the row's key (the URL key of the edit form).
  rowKey: string;
  // The list's column field names, in column order ("" for a column with no box).
  columnNames: string[];
  // Closes the row (the parent sets the open row to none and clears the list's messages).
  onClose: () => void;
  // Sets the messages of the red box above the table (the form errors of a refused write).
  onListErrors: (messages: string[]) => void;
  // The key of the row that is open now in the list (null when none). A write answer for a row that is no longer the
  // open one is ignored: it must not close the row that replaced it, nor write its messages.
  currentOpen: () => string | null;
};

export function useInlineRow({
  pk,
  kind,
  rowKey,
  columnNames,
  onClose,
  onListErrors,
  currentOpen,
}: InlineRowOptions) {
  const isNew = rowKey === "new";
  const numericKey = isNew ? 0 : Number(rowKey);
  const form = useRowForm(pk, kind, isNew ? null : numericKey, {}, true);
  const formFields = form.data?.fields;
  const hidden = form.data?.hidden ?? {};
  // Edit and delete send the loaded_* snapshot; without it the server refuses, so nothing is posted.
  const hasHidden = Object.keys(hidden).length > 0;
  const columnKey = columnNames.join("|");

  // One slot per column: the form field that column's box edits, or undefined. Not loaded yet: all undefined.
  const slots = useMemo<(FormField | undefined)[]>(() => {
    const byName = new Map((formFields ?? NO_FIELDS).map((field) => [field.name, field]));
    return columnKey.split("|").map((name) => (name ? byName.get(name) : undefined));
    // columnKey is the column names joined; it stands for columnNames.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formFields, columnKey]);
  const shown = useMemo(() => slots.filter((field): field is FormField => field !== undefined), [slots]);

  const fields = useFormValues(shown, rowKey);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [errorTick, setErrorTick] = useState(0);
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [leaving, setLeaving] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sees it at once and sends nothing.
  const inFlight = useRef(false);

  const addRow = useAddRow(pk, kind);
  const editRow = useEditRow(pk, kind, numericKey);
  const deleteRow = useDeleteRow(pk, kind, numericKey);

  // A dirty row is an unsaved owner while it is open (unsaved.ts); closing it clears the key on unmount.
  useUnsavedFlag("list:" + kind, fields.dirty);

  // A failed form load keeps the row with its cells empty and says so in the red box.
  const loadFailed = form.isError;
  useEffect(() => {
    if (loadFailed) onListErrors([LOAD_FAILED_TEXT]);
    // onListErrors is the parent's setter, stable for the life of the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadFailed]);

  const isCurrent = () => currentOpen() === rowKey;

  // Typing changes one value and drops that box's error, as the next save decides it afresh.
  const setValue = (name: string, value: string) => {
    fields.set(name, value);
    setErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // A refused write: its field errors under their boxes, its form errors in the red box, the first invalid box focused.
  // When the refusal names no box and gives no form error, the red box gets the general save message.
  const refuse = (fieldErrors: Record<string, string[]>, formErrors: string[]) => {
    const shownNames = new Set(shown.map((field) => field.name));
    const boxNamed = Object.keys(fieldErrors).some((name) => shownNames.has(name));
    setErrors(fieldErrors);
    const messages = formErrors.length > 0 ? formErrors : boxNamed ? [] : [SAVE_FAILED_TEXT];
    onListErrors(messages);
    setErrorTick((tick) => tick + 1);
  };

  // The body of a write: the shown boxes as posted, plus the form's hidden loaded_* values (the server needs them).
  const bodyOf = () => ({ ...toPostValues(shown, fields.values), ...hidden });

  const save = async () => {
    if (inFlight.current) return;
    if (!form.data) {
      if (loadFailed) onListErrors([LOAD_FAILED_TEXT]);
      return;
    }
    if (!isNew && !hasHidden) {
      refuse({}, []);
      return;
    }
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const values = bodyOf();
      const result: EmployeeWriteResultOut = isNew
        ? await addRow.mutateAsync({ values })
        : await editRow.mutateAsync({ values });
      if (result.ok) {
        // The guard stays set: the row is closing, and a second Enter must not send again.
        closing = true;
        if (isCurrent()) {
          onListErrors([]);
          onClose();
        }
        return;
      }
      if (!isCurrent()) return;
      refuse(result.field_errors, result.form_errors);
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Тийм»: the row fades at once (leaving), the delete is sent once, and on success the row closes at once. A refused
  // or failed delete clears the fade and keeps the row open with its message. The in-flight guard is kept after a success,
  // so a second tap sends nothing.
  const remove = async () => {
    if (inFlight.current || isNew) return;
    if (!form.data) {
      if (loadFailed) onListErrors([LOAD_FAILED_TEXT]);
      return;
    }
    if (!hasHidden) {
      setConfirming(false);
      refuse({}, []);
      return;
    }
    inFlight.current = true;
    setPending(true);
    setLeaving(true);
    let closing = false;
    try {
      const result = await deleteRow.mutateAsync({ values: bodyOf() });
      if (result.ok) {
        closing = true;
        if (isCurrent()) {
          onListErrors([]);
          onClose();
        }
        return;
      }
      if (!isCurrent()) return;
      setLeaving(false);
      setConfirming(false);
      refuse(result.field_errors, result.form_errors);
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      setLeaving(false);
      setConfirming(false);
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  return {
    loaded: formFields !== undefined,
    slots,
    emptyLists: form.data?.empty_lists ?? [],
    values: fields.values,
    dirty: fields.dirty,
    errors,
    errorTick,
    pending,
    confirming,
    setConfirming,
    leaving,
    setValue,
    save,
    remove,
    canDelete: !isNew,
  };
}
