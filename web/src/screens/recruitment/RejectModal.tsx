import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useRejectCandidate, type RecruitRejectIn, type RecruitWriteResultOut } from "../../api/recruitment";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The reject pop-up of a candidate (port of app/recruitment/templates/recruitment/candidate_reject.html and RejectForm in
// app/recruitment/forms.py). The reason is required unless the candidate withdrew; the server says so under the box.
// The confirm is red (UI_RULES 4a): reject is the destructive step itself, and a grey line says what is kept and how to
// undo it.

const TITLE = "Ажил хүсэгчийг татгалзах";
const REASON_LABEL = "Татгалзсан шалтгаан";
const REASON_PLACEHOLDER = "Жишээ: туршлага хүрэлцэхгүй байна";
const WITHDRAWN_LABEL = "Ажил хүсэгч өөрөө татгалзсан";
const WITHDRAWN_HELP = "Татгалзсан биш, өөрөө хасагдсан бол сонгоно. Шалтгаан заавал биш.";
const KEPT_LINE =
  "Шалтгаан шатны түүхэнд хадгалагдана. Алдсан бол ажил хүсэгчийн хуудаснаас «Дахин нээх» дарж буцаана.";

export interface RejectModalProps {
  candidate: { id: number; name: string };
  // Closes this pop-up only (Болих, ✕, Escape).
  onClose: () => void;
  // A rejection that saved: the caller closes the pop-up.
  onDone: () => void;
}

export function RejectModal({ candidate, onClose, onDone }: RejectModalProps) {
  const reject = useRejectCandidate(candidate.id);
  const ids = useId();
  const [reason, setReason] = useState("");
  const [withdrawn, setWithdrawn] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = reason !== "" || withdrawn;
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);
  const reasonInvalid = (fieldErrors.reason?.length ?? 0) > 0;
  const reasonErrorId = `${ids}-reason-error`;

  // Typing in the box drops its error; the next send decides it afresh.
  const setReasonText = (value: string) => {
    setReason(value);
    setFieldErrors((prev) =>
      "reason" in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== "reason")) : prev,
    );
  };

  // The reason's message goes under its box; the others, and the form's own, go in the red box on top. A refusal with no
  // message at all gets the general save text.
  const refuse = (fe: Record<string, string[]>, formErrors: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => key !== "reason")
      .flatMap(([, list]) => list);
    const top = [...formErrors, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const body: RecruitRejectIn = { reason, withdrawn };
      const result: RecruitWriteResultOut = await reject.mutateAsync(body);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
        onDone();
        return;
      }
      const messages = [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
      refuse(result.field_errors, messages);
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

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty: dirty || hasErrors, leaving: false, close: onClose }, (message) =>
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
      titleClass="mb-1 text-lg font-semibold"
      noAnim
    >
      <p className="mb-4 text-sm text-slate-600">{candidate.name}</p>
      <form noValidate className="space-y-3" onSubmit={submit}>
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <div className="block text-sm">
          <label className="block">
            {withdrawn ? REASON_LABEL : `${REASON_LABEL} *`}
            <textarea
              name="reason"
              rows={3}
              placeholder={REASON_PLACEHOLDER}
              value={reason}
              onChange={(event) => setReasonText(event.target.value)}
              aria-invalid={reasonInvalid || undefined}
              aria-describedby={reasonInvalid ? reasonErrorId : undefined}
              className={BOXED}
            />
          </label>
          {reasonErrors}
        </div>
        <div className="text-sm">
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              name="withdrawn"
              checked={withdrawn}
              onChange={(event) => setWithdrawn(event.target.checked)}
              className="mt-1"
            />
            <span>{WITHDRAWN_LABEL}</span>
          </label>
          <p className="ml-6 text-xs text-slate-500">{WITHDRAWN_HELP}</p>
        </div>
        <p className="text-xs text-slate-500">{KEPT_LINE}</p>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            disabled={pending}
            onClick={cancel}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm disabled:opacity-50"
          >
            Болих
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50"
          >
            Татгалзах
          </button>
        </div>
      </form>
    </Modal>
  );
}
