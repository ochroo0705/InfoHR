import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { invalidateEmployee, type EmployeeFormFieldOut } from "../../api/employeeWrites";
import { useEventCancelForm, useSubmitEventCancel, type HrPopupOut, type HrPopupResultOut } from "../../api/events";
import type { ApiFailure } from "../../api/mutate";
import { useOrderPopup, useSubmitOrderEdit, useSubmitOrderUpload, type OrderPopupKind } from "../../api/orders";
import { useUnsavedFlag } from "../../lib/unsaved";
import { confirm } from "../../widgets/confirm";
import { FormFields, toPostValues, useFormValues } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { OrderFields } from "../../widgets/OrderFields";
import { tryClose } from "../../widgets/modalLogic";
import { loadMessagesOf, splitRefusal, STALE_TEXT, useStaleRefresh, usePopupGuards } from "./popupGuards";

// The generic pop-up of `employees/_modal.html` for the order edit, the order scan upload and the event cancel. The
// server draws the form: its title, hint, submit label, multipart flag and fields (HrPopupOut). This component draws
// them and keeps what the user typed; it decides no rule (no order block, no «cancel_order_no», no required box).
// Contract: the parent remounts the pop-up with a new key for each open (as CorrectionModal and the sections do), so each
// open starts with nothing typed. The parent keeps it mounted while `open` goes false, so the Modal plays its exit.
// Order cancel (`order-cancel`) is not here yet (Task 3d-2 extends `target`).

const NO_FIELDS: EmployeeFormFieldOut[] = [];
const FILE_BOX_CLASS =
  "mt-1 inline-block cursor-pointer rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 focus-within:ring-2 focus-within:ring-violet-500";

export type HrPopupTarget =
  | { kind: "order-edit" | "order-upload"; orderId: number }
  | { kind: "event-cancel"; eventId: number };

export type HrPopupProps = {
  pk: number;
  target: HrPopupTarget;
  open: boolean;
  // Called once the close is allowed. The parent sets open to false.
  onClose: () => void;
};

export function HrPopup({ pk, target, open, onClose }: HrPopupProps) {
  const queryClient = useQueryClient();
  const isOrder = target.kind !== "event-cancel";
  const orderId = target.kind === "event-cancel" ? 0 : target.orderId;
  const eventId = target.kind === "event-cancel" ? target.eventId : 0;
  const orderKind: OrderPopupKind = target.kind === "order-upload" ? "upload" : "edit";

  // The load and the save hooks are all called (hooks rules); the ones of the other kinds are disabled or unused.
  const orderLoad = useOrderPopup(pk, orderId, orderKind, open && isOrder);
  const cancelLoad = useEventCancelForm(pk, eventId, open && !isOrder);
  const load = isOrder ? orderLoad : cancelLoad;
  const submitEdit = useSubmitOrderEdit(pk, orderId);
  const submitUpload = useSubmitOrderUpload(pk, orderId);
  const submitCancel = useSubmitEventCancel(pk, eventId);

  const shown: HrPopupOut | null = load.data ?? null;
  const fields = shown?.fields ?? NO_FIELDS;
  const values = useFormValues(fields, `${target.kind}/${orderId}/${eventId}`);
  const { formRef, isCurrent, isMounted, bumpErrorTick } = usePopupGuards(open);

  // The one dirty flag: typed or chosen at any time since this pop-up opened (the same rule as CorrectionModal).
  const [typed, setTyped] = useState(false);
  const dirty = typed;
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  useUnsavedFlag("hrpopup:" + target.kind, open && dirty);

  // A load that answers 404 means the page changed: refresh the employee's work and activity.
  const loadFailure = load.isError ? (load.error as Partial<ApiFailure>) : null;
  const loadIsStale = loadFailure?.status === 404;
  useStaleRefresh(loadIsStale, pk, queryClient, ["work", "activity"]);

  // A refused save: the field errors of this form's boxes go under those boxes; the rest, and the form errors, go to the
  // red box on top (splitRefusal, shared with EventModal).
  const refuse = (fieldErrs: Record<string, string[]>, messages: string[]) => {
    const split = splitRefusal(
      fields.map((item) => item.name),
      fieldErrs,
      messages,
    );
    setErrors(split.boxErrors);
    setFormErrors(split.formMessages);
    bumpErrorTick();
  };

  // Typing or choosing drops that box's error; the next save decides it afresh.
  const dropError = (name: string) =>
    setErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  const onFieldChange = (name: string, value: string) => {
    values.set(name, value);
    setTyped(true);
    dropError(name);
  };
  const onFileChange = (name: string, chosen: File | null) => {
    setFile(chosen);
    setTyped(true);
    dropError(name);
  };

  // Sends the pop-up's own request: the order edit or cancel posts the boxes; the upload posts the chosen file.
  const send = (): Promise<HrPopupResultOut> => {
    if (target.kind === "order-upload") return submitUpload.mutateAsync({ file });
    const body = { values: toPostValues(fields, values.values) };
    return target.kind === "order-edit" ? submitEdit.mutateAsync(body) : submitCancel.mutateAsync(body);
  };

  // Enter in a box, or the submit button: one request at a time. A refusal keeps the pop-up open with every value typed.
  const submit = async () => {
    if (inFlight.current || !shown) return;
    inFlight.current = true;
    setPending(true);
    setFormErrors([]);
    let closing = false;
    try {
      const answer = await send();
      if (!isCurrent()) return;
      if (answer.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
      refuse(answer.field_errors, answer.form_errors);
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      if (failure.status === 404) {
        // The order or event changed elsewhere: keep the typed values, refresh the page data.
        setErrors({});
        setFormErrors([STALE_TEXT]);
        void invalidateEmployee(queryClient, pk, ["work", "activity"]);
      } else {
        refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
      }
    } finally {
      if (!closing) {
        inFlight.current = false;
        if (isMounted()) setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕, Escape and an outside click.
  const cancel = () => {
    void tryClose({ dirty, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const loadMessages = loadMessagesOf(loadFailure);
  const messages = load.isError ? loadMessages : formErrors;
  const showing = open && (shown !== null || load.isError);

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
          {messages.length > 0 ? <p className="rounded bg-red-50 p-2 text-sm text-red-700">{messages.join(" ")}</p> : null}
          {target.kind === "order-edit" ? (
            <OrderFields fields={fields} values={values.values} errors={errors} onChange={onFieldChange} />
          ) : shown.multipart ? (
            <div className="grid gap-3 md:grid-cols-2">
              {fields.map((item) => {
                const itemErrors = errors[item.name] ?? [];
                return (
                  <label key={item.name} className="block text-sm">
                    {item.label}
                    {item.required ? " *" : null}
                    <span className={FILE_BOX_CLASS}>
                      Файл сонгох
                      <input
                        type="file"
                        name={item.name}
                        aria-invalid={itemErrors.length > 0 || undefined}
                        className="sr-only"
                        onChange={(event) => onFileChange(item.name, event.target.files?.[0] ?? null)}
                      />
                    </span>
                    <span data-file-name="" className="ml-2 text-xs text-slate-500">
                      {file?.name ?? ""}
                    </span>
                    {itemErrors.map((message, i) => (
                      <span key={i} className="text-xs text-red-600">
                        {message}
                      </span>
                    ))}
                  </label>
                );
              })}
            </div>
          ) : (
            <FormFields
              variant="boxed"
              fields={fields}
              values={values.values}
              errors={errors}
              onChange={onFieldChange}
              errorInline
            />
          )}
          {shown.hint ? <p className="text-xs text-slate-500">{shown.hint}</p> : null}
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
              {shown.submit_label}
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="rounded bg-red-50 p-2 text-sm text-red-700">{messages.join(" ")}</p>
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
