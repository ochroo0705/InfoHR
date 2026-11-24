import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useApproveRequest,
  useLeaveRequestDetail,
  type LeaveRequestApproveIn,
  type LeaveRequestDetailOut,
  type LeaveWriteResultOut,
} from "../../api/leaveRequests";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { DECIDED_TEXT, RequestRejectModal } from "./RequestRejectModal";

// The detail pop-up of one leave request (port of app/leave/templates/leave/_request_detail.html and
// app/leave/views_requests.py request_detail). Labels, classes and the order of the parts are copied from the template.
// The gating is the API's raw flags: the past-date line and the step line and balance show only while the request waits,
// the decided line only once it does not. A decided request, or one the user may not act on, has no form.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const TITLE = "Чөлөөний хүсэлт";
const NO_JOB_TEXT = "Ажлын мэдээлэл алга";
const OVERRIDE_LABEL = "Үлдэгдэл хүрэлцэхгүй бол шалтгаан";
const REASON_MAX = 200;

export interface RequestDetailModalProps {
  // The request's id.
  id: number;
  onClose: () => void;
}

// The pop-up, once the detail has loaded. The typed reason and the refusal state live in DetailForm, so they survive a
// refused approve (the detail refetches after a refusal and keeps its data meanwhile).
function DetailForm({ id, detail, onClose }: { id: number; detail: LeaveRequestDetailOut; onClose: () => void }) {
  const approve = useApproveRequest(id);
  const ids = useId();
  const [reason, setReason] = useState("");
  // The reason box shows when the server asks for it, and after any refusal (Django's show_reason).
  const [refused, setRefused] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  // Set when the request was decided meanwhile (the API answers 404): the text shows, the decision buttons go, and the
  // detail is refetched by the hook so the pop-up redraws as decided.
  const [gone, setGone] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = reason !== "";
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors) && !gone;
  const reasonShown = detail.needs_reason || refused;
  const reasonInvalid = (fieldErrors.override_reason?.length ?? 0) > 0;
  const reasonErrorId = `${ids}-override-error`;

  // Typing in the box drops its error; the next approve decides it afresh.
  const setReasonText = (value: string) => {
    setReason(value);
    setFieldErrors((prev) =>
      "override_reason" in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== "override_reason")) : prev,
    );
  };

  // A refused approve: the reason message under its box, the others (and the stray ones) in the red box at the top. A
  // refusal with no message at all gets the general save text.
  const refuse = (fe: Record<string, string[]>, formErrors: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => key !== "override_reason")
      .flatMap(([, list]) => list);
    const top = [...formErrors, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setRefused(true);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  // Approves the current step: the step is the one the detail was loaded at.
  const approveNow = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const body: LeaveRequestApproveIn = { step: detail.current_step, override_reason: reason };
      const result: LeaveWriteResultOut = await approve.mutateAsync(body);
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
      if (failure.status === 404) {
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
  const cancelPop = () => {
    void tryClose({ dirty: (dirty || hasErrors) && !gone, leaving: false, close: onClose }, (message) =>
      confirm(message, { ok: "Хаах" }),
    );
  };

  const reasonErrors: ReactNode = reasonInvalid ? (
    <div id={reasonErrorId}>
      {(fieldErrors.override_reason ?? []).map((message, index) => (
        <span key={index} className="block text-xs text-red-600">
          {message}
        </span>
      ))}
    </div>
  ) : null;

  const decidedText = `Энэ хүсэлт шийдэгдсэн: ${detail.status_label}${detail.reason ? ` · ${detail.reason}` : ""}`;

  return (
    <>
      <Modal
        open
        onClose={onClose}
        dirty={dirty}
        serverErrors={hasErrors ? serverErrors : null}
        title={detail.employee_name}
        titleClass="mb-1 text-lg font-semibold"
        // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell, as LeaveCancelModal).
        noAnim
      >
        <p className="mb-4 text-sm text-slate-500">{detail.job_line || NO_JOB_TEXT}</p>
        {topErrors.length > 0 ? (
          <div role="alert" className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-2">
          <div>
            <dt className="text-slate-500">Төрөл</dt>
            <dd>{detail.leave_type}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Хугацаа</dt>
            <dd>{`${detail.start} – ${detail.end}`}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Ажлын өдөр</dt>
            <dd>{detail.working_days}</dd>
          </div>
          {detail.waiting ? (
            <div>
              <dt className="text-slate-500">Шат</dt>
              <dd>
                {`${detail.current_step}/${detail.step_count} · ${detail.rule}`}
                {detail.override ? (
                  <>
                    {" "}
                    <span className="text-amber-700">(эрхээр)</span>{" "}
                    <span className="block text-xs text-slate-500">Удирдлагын оронд батлав</span>
                  </>
                ) : null}
              </dd>
            </div>
          ) : null}
          {detail.waiting && detail.balance_after !== null ? (
            <div>
              <dt className="text-slate-500">Энэ чөлөөг авсны дараах үлдэгдэл</dt>
              <dd>{detail.balance_after}</dd>
            </div>
          ) : null}
          <div>
            <dt className="text-slate-500">Гаргасан</dt>
            <dd>{detail.created}</dd>
          </div>
        </dl>

        {detail.waiting && detail.past ? (
          <p className="mt-3 rounded bg-amber-50 p-2 text-sm text-amber-800">Энэ хүсэлт өнгөрсөн огноотой байна.</p>
        ) : null}
        {detail.warnings.map((warning, index) => (
          <p key={index} className="mt-2 text-sm text-amber-700">
            {warning}
          </p>
        ))}
        {detail.waiting ? null : <p className="mt-3 text-sm text-slate-500">{decidedText}</p>}

        <h3 className="mt-5 text-sm font-semibold text-slate-700">Нэг хэлтсийн бусад</h3>
        {detail.others.length > 0 ? (
          <ul className="mt-1 space-y-1 text-sm">
            {detail.others.map((other, index) => (
              <li key={index}>
                {`${other.name} · ${other.start} – ${other.end} · `}
                <span className="text-slate-500">{other.state}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-slate-400">Давхцсан хүн алга</p>
        )}

        <h3 className="mt-5 text-sm font-semibold text-slate-700">Түүх</h3>
        {detail.history.length > 0 ? (
          <ul className="mt-1 space-y-1 text-sm">
            {detail.history.map((entry, index) => (
              <li key={index}>{entry.text}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-slate-400">Түүх бүртгэгдээгүй</p>
        )}

        {detail.may && !gone ? (
          <form noValidate className="mt-5 space-y-3" onSubmit={approveNow}>
            {reasonShown ? (
              <div className="block text-sm">
                <label className="block">
                  {OVERRIDE_LABEL}
                  <input
                    type="text"
                    name="override_reason"
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
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
              <button
                type="button"
                disabled={pending}
                onClick={() => setRejecting(true)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-red-600 hover:bg-red-50"
              >
                Татгалзах
              </button>
              <div className="flex gap-2">
                <button type="button" onClick={cancelPop} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
                  Болих
                </button>
                <button
                  type="submit"
                  disabled={pending}
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
                >
                  Батлах
                </button>
              </div>
            </div>
          </form>
        ) : (
          <div className="mt-5 flex justify-end">
            <button type="button" onClick={cancelPop} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
              Болих
            </button>
          </div>
        )}
      </Modal>
      {/* Outside the detail's panel: the reject pop-up's typing does not mark the detail as typed-in. */}
      {rejecting ? (
        <RequestRejectModal
          request={{ id, leave_type: detail.leave_type, start: detail.start, end: detail.end }}
          onClose={() => setRejecting(false)}
          onDone={() => {
            setRejecting(false);
            onClose();
          }}
        />
      ) : null}
    </>
  );
}

// While the detail loads (or when it fails, e.g. a 404 for a request the user may not see): the same pop-up shell.
function LoadingDetail({ failed, onClose }: { failed: boolean; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={TITLE} noAnim>
      {failed ? (
        <p role="alert" className="text-sm text-red-600">
          {LOAD_FAILED_TEXT}
        </p>
      ) : null}
    </Modal>
  );
}

// The detail pop-up of request `id`: read fresh on every open (see useLeaveRequestDetail).
export function RequestDetailModal({ id, onClose }: RequestDetailModalProps) {
  const detail = useLeaveRequestDetail(id);
  const data = detail.data;
  if (data === undefined) return <LoadingDetail failed={detail.isError} onClose={onClose} />;
  return <DetailForm id={id} detail={data} onClose={onClose} />;
}
