import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useRejectRequest, type LeaveRequestRejectIn, type LeaveWriteResultOut } from "../../api/leaveRequests";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The reject pop-up of one leave request (port of app/leave/templates/leave/_request_reject.html and app/leave/forms.py
// RejectForm). Texts and classes are copied from the template. The reason is required; the server says so when it is
// empty. A rejected request writes no leave. The pop-up opens over the detail pop-up; `onDone` closes both.

const REASON_MAX = 200;
const TITLE = "Хүсэлт татгалзах";
const REASON_LABEL = "Татгалзсан шалтгаан";
// Shown when the request was decided or withdrawn meanwhile (the API answers 404). Shared with the detail pop-up.
export const DECIDED_TEXT = "Энэ хүсэлт шийдэгдсэн байна.";

export interface RequestRejectModalProps {
  // The request being rejected: its id, and the type and dates the pop-up names.
  request: { id: number; leave_type: string; start: string; end: string };
  // Closes this pop-up only (Болих, ✕, Escape).
  onClose: () => void;
  // A rejection that saved: the caller closes the detail pop-up too.
  onDone: () => void;
}

export function RequestRejectModal({ request, onClose, onDone }: RequestRejectModalProps) {
  const reject = useRejectRequest(request.id);
  const ids = useId();
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // Set when the request was decided meanwhile: the text shows and the submit stays locked.
  const [gone, setGone] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = reason !== "";
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors) && !gone;
  const reasonInvalid = (fieldErrors.reason?.length ?? 0) > 0;
  const reasonErrorId = `${ids}-reason-error`;

  // Typing in the box drops its error; the next send decides it afresh.
  const setReasonText = (value: string) => {
    setReason(value);
    setFieldErrors((prev) =>
      "reason" in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== "reason")) : prev,
    );
  };

  // A refused send: the reason message under its box, the others (and the stray ones) in the red box at the top. A
  // refusal with no message at all gets the general save text.
  const refuse = (fe: Record<string, string[]>, formErrors: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => key !== "reason")
      .flatMap(([, list]) => list);
    const top = [...formErrors, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const body: LeaveRequestRejectIn = { reason };
      const result: LeaveWriteResultOut = await reject.mutateAsync(body);
      if (result.ok) {
        // The guard stays set: the pop-ups are closing, and nothing may send again.
        closing = true;
        onDone();
        return;
      }
      const messages = [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
      refuse(result.field_errors, messages);
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      if (failure.status === 404) {
        // Decided or withdrawn meanwhile: the detail is refetched by the hook, so this pop-up only says so.
        setGone(true);
        setFieldErrors({});
        setTopErrors([DECIDED_TEXT]);
      } else {
        refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
      }
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty: (dirty || hasErrors) && !gone, leaving: false, close: onClose }, (message) =>
      confirm(message, { ok: "Хаах" }),
    );
  };

  // The reason's errors sit under its box, outside the label, and the box names them in aria-describedby.
  const reasonErrors: ReactNode = reasonInvalid ? (
    <div id={reasonErrorId}>
      {(fieldErrors.reason ?? []).map((message, index) => (
        <span key={index} className="block text-xs text-red-600">
          {message}
        </span>
      ))}
    </div>
  ) : null;

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={hasErrors ? serverErrors : null}
      title={TITLE}
      titleClass="mb-2 text-lg font-semibold"
      width="max-w-md"
      // No enter or exit animation, as the other pop-ups of the leave screens.
      noAnim
    >
      <p className="mb-3 text-sm text-slate-600">{`${request.leave_type} ${request.start} – ${request.end}`}</p>
      <form noValidate className="space-y-3" onSubmit={save}>
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <div className="block text-sm">
          <label className="block">
            {`${REASON_LABEL} *`}
            <textarea
              name="reason"
              rows={2}
              required
              maxLength={REASON_MAX}
              value={reason}
              onChange={(event) => setReasonText(event.target.value)}
              aria-invalid={reasonInvalid || undefined}
              aria-describedby={reasonInvalid ? reasonErrorId : undefined}
              className={BOXED}
            />
          </label>
          {reasonErrors}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            Болих
          </button>
          <button
            type="submit"
            disabled={pending || gone}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Татгалзах
          </button>
        </div>
      </form>
    </Modal>
  );
}
