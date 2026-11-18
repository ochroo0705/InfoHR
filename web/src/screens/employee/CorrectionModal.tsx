import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useCorrectionForm,
  useSubmitCorrection,
  type CorrectionPath,
  type EmployeeFormOut,
  type EmployeeWriteResultOut,
} from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { useUnsavedFlag } from "../../lib/unsaved";
import { confirm } from "../../widgets/confirm";
import { FormFields, toPostValues, useFormValues, type FormField } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The correction pop-ups of the salary and work tabs (`employees/_modal.html` as the Django views set_salary,
// correct_salary and correct_job render it): «Цалин тогтоох», «Цалин засварлах», «Ажлын түүх засварлах». The form is
// loaded when the pop-up opens; its title comes from the server. A correction has no hidden loaded values and no delete,
// so the form is only the boxes and the buttons «Болих» and «Хадгалах». The typed values are kept after a refused save.
// The parent keeps this component mounted while `open` goes false, so the Modal plays its exit; the parent remounts it
// (new key) for each new open (useCorrectionPopup).

const NO_FIELDS: FormField[] = [];
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

export type CorrectionModalProps = {
  pk: number;
  path: CorrectionPath;
  open: boolean;
  // Called once the close is allowed. The parent sets open to false.
  onClose: () => void;
};

export function CorrectionModal({ pk, path, open, onClose }: CorrectionModalProps) {
  const form = useCorrectionForm(pk, path, open);
  const shown: EmployeeFormOut | null = form.data ?? null;
  const fields = useFormValues(shown?.fields ?? NO_FIELDS, path);
  const submitCorrection = useSubmitCorrection(pk, path);

  // The one dirty flag: typed at any time since this pop-up opened. It drives «Болих», the Modal's ✕, Escape and outside
  // click (the Modal's dirty prop) and the unsaved registry. A value typed and then changed back still counts.
  const [typed, setTyped] = useState(false);
  const dirty = typed;

  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [errorTick, setErrorTick] = useState(0);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  // Mounted and still open. A save answer that arrives after this pop-up was closed, or replaced by a newer one (the
  // parent remounts it), must not show errors, move the focus or close anything.
  const mounted = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const isCurrent = () => mounted.current && openRef.current;

  // The unsaved flag counts only while the pop-up is open: a closed one keeps its values for its exit, not as unsaved.
  useUnsavedFlag("correction:" + path, open && dirty);

  // After a refused save the cursor goes to the first box with an error.
  useEffect(() => {
    if (errorTick === 0) return;
    const invalid = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    const box = invalid ?? formRef.current?.querySelector<HTMLElement>("input:not([type=hidden]), textarea");
    box?.focus();
  }, [errorTick]);

  // A refused save: its field errors under their boxes, its form errors in the red box. When the refusal names no box
  // and gives no form error, the red box gets the general save message.
  const refuse = (fieldErrs: Record<string, string[]>, messages: string[]) => {
    const names = new Set((shown?.fields ?? []).map((field) => field.name));
    const boxNamed = Object.keys(fieldErrs).some((name) => names.has(name));
    setErrors(fieldErrs);
    setFormErrors(messages.length > 0 ? messages : boxNamed ? [] : [SAVE_FAILED_TEXT]);
    setErrorTick((tick) => tick + 1);
  };

  const onFieldChange = (name: string, value: string) => {
    fields.set(name, value);
    setTyped(true);
    // Typing drops that box's error; the next save decides it afresh.
    setErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // Enter in a box, or «Хадгалах»: posts the boxes to the path the form was loaded from. A refusal keeps the pop-up open.
  const submit = async () => {
    if (inFlight.current || !shown) return;
    inFlight.current = true;
    setPending(true);
    setFormErrors([]);
    let closing = false;
    try {
      const values = { ...toPostValues(shown.fields, fields.values), ...shown.hidden };
      // The mutation's success waits for the refetch of the work, salary and activity keys, so the pop-up closes after it.
      const result: EmployeeWriteResultOut = await submitCorrection.mutateAsync({ values });
      if (!isCurrent()) return;
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
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

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const showing = open && (shown !== null || form.isError);
  const messages = form.isError ? [LOAD_FAILED_TEXT] : formErrors;

  return (
    <Modal open={showing} onClose={onClose} dirty={dirty} title={shown?.title}>
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
          <FormFields
            fields={shown.fields}
            values={fields.values}
            errors={errors}
            onChange={onFieldChange}
            variant="boxed"
          />
          <div className="flex justify-end gap-2 pt-2">
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
  );
}

// One correction pop-up of a section: `openCorrection(path)` opens it, `correctionModal` is drawn by the section. Each
// open gets its own serial (a remount, so an old form never shows in a new pop-up). A close answer closes only the
// pop-up that asked (the serial guard, as PersonalList's closePopup does).
type CorrectionTarget = { path: CorrectionPath; serial: number; open: boolean };

export function useCorrectionPopup(pk: number): {
  openCorrection: (path: CorrectionPath) => void;
  correctionModal: ReactNode;
} {
  const [target, setTarget] = useState<CorrectionTarget | null>(null);
  const openCorrection = (path: CorrectionPath) =>
    setTarget((prev) => ({ path, serial: (prev?.serial ?? 0) + 1, open: true }));
  const closeCorrection = (serial: number) =>
    setTarget((prev) => (prev && prev.serial === serial ? { ...prev, open: false } : prev));
  const correctionModal =
    target !== null ? (
      <CorrectionModal
        key={target.serial}
        pk={pk}
        path={target.path}
        open={target.open}
        onClose={() => closeCorrection(target.serial)}
      />
    ) : null;
  return { openCorrection, correctionModal };
}
