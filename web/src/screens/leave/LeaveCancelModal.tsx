import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useCancelLeave,
  useLeaveCancelInfo,
  type LeaveCancelInfoOut,
  type LeaveCancelIn,
  type LeaveWriteResultOut,
} from "../../api/leave";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { STALE_REOPEN_TEXT, STALE_TEXT } from "./leaveTexts";

// The cancel pop-up of one leave (port of app/leave/templates/leave/_cancel.html and app/leave/views.py leave_cancel).
// Texts and classes are copied from the template. A leave that has not started is cancelled (removed); one that has
// started is marked «Буруу бүртгэсэн» (mistake) and kept. Django asks no extra question, so none is asked here.
// The row as loaded (from the cancel info) goes back untouched, so a save refuses a row another program changed.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const REASON_MAX = 200;
const MISTAKE_TEXT = "Эхэлсэн чөлөөг устгахгүй, буруу бүртгэл гэж тэмдэглэнэ.";
const RESTORE_TEXT = "Үлдэгдэл буцаж нэмэгдэнэ.";
const TITLE_CANCEL = "Чөлөө цуцлах";
const TITLE_MISTAKE = "Буруу гэж тэмдэглэх";

export interface LeaveCancelModalProps {
  // The leave's id.
  id: number;
  onClose: () => void;
}

// The pop-up, once the cancel info has loaded. The typed reason lives in CancelForm, so it survives a refused save.
function CancelForm({ id, info, onClose }: { id: number; info: LeaveCancelInfoOut; onClose: () => void }) {
  const cancel = useCancelLeave(id);
  const ids = useId();
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = reason !== "";
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);
  const title = info.mistake ? TITLE_MISTAKE : TITLE_CANCEL;
  const reasonErrorId = `${ids}-reason-error`;
  const reasonInvalid = (fieldErrors.reason?.length ?? 0) > 0;

  // Typing in the box drops its error; the next save decides it afresh.
  const setReasonText = (value: string) => {
    setReason(value);
    setFieldErrors((prev) =>
      "reason" in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== "reason")) : prev,
    );
  };

  // A refused save: the reason message under its box, the others (and the stray ones) in the red box at the top. A
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
      const body: LeaveCancelIn = { reason, loaded: info.loaded };
      const result: LeaveWriteResultOut = await cancel.mutateAsync(body);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
        onClose();
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
  const cancelPop = () => {
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
      title={title}
      // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell, as LeaveFormModal).
      noAnim
    >
      <p className="mb-3 text-sm text-slate-600">{`${info.label} ${info.start} – ${info.end}`}</p>
      {info.mistake ? (
        <p className="mb-3 text-sm text-slate-600">
          {MISTAKE_TEXT}
          {info.restores_balance ? ` ${RESTORE_TEXT}` : ""}
        </p>
      ) : null}
      <form noValidate className="space-y-3" onSubmit={save}>
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
            {topErrors.includes(STALE_TEXT) ? <p>{STALE_REOPEN_TEXT}</p> : null}
          </div>
        ) : null}
        <div className="block text-sm">
          <label className="block">
            Шалтгаан *
            <input
              type="text"
              name="reason"
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
          <button type="button" onClick={cancelPop} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            Болих
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
          >
            {info.mistake ? TITLE_MISTAKE : "Цуцлах"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// While the cancel info loads (or when it fails): the same pop-up shell. The title is «Чөлөө цуцлах» until the info
// says the leave is a mistake; the form then switches to «Буруу гэж тэмдэглэх».
function LoadingCancel({ failed, onClose }: { failed: boolean; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={TITLE_CANCEL} noAnim>
      {failed ? (
        <p role="alert" className="text-sm text-red-600">
          {LOAD_FAILED_TEXT}
        </p>
      ) : null}
    </Modal>
  );
}

// The cancel pop-up: asks what the leave's cancel will do, then cancels (or marks a mistake) on «Цуцлах».
export function LeaveCancelModal({ id, onClose }: LeaveCancelModalProps) {
  const info = useLeaveCancelInfo(id);
  const data = info.data;
  if (data === undefined) return <LoadingCancel failed={info.isError} onClose={onClose} />;
  return <CancelForm id={id} info={data} onClose={onClose} />;
}
