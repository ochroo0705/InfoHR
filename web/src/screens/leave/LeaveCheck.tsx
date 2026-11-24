import { useEffect, useRef, useState } from "react";
import { useCheckLeave, type LeaveCheckOut } from "../../api/leave";

// The live check line under the leave form (port of app/leave/templates/leave/_check.html; the classes and texts are
// copied from it). It asks the server whether the posted dates are allowed and what they count, and shows the answer.
// - `values` are the form's values at its last COMMIT (a select pick, a whole date, or leaving the note or reason box),
//   not every keystroke: the check can write (ledger.ensure_grants), so it runs on a change the user has committed.
// - Nothing is asked on mount, in add or edit mode (Django's check is hx-trigger "change" only).
// - It checks only when employee, leave type, start and end are all set. The question waits 300 ms after the last commit.
// - The latest answer wins: an answer to an older question (or one that came after the pop-up closed) is ignored.
// - Nothing is shown while there is no answer, or when the answer is not valid and has no lists to show.

export const CHECK_DELAY_MS = 300;

export interface LeaveCheckValues {
  employee: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  note?: string;
  override_reason?: string;
}

export interface LeaveCheckProps {
  values: LeaveCheckValues;
  // The leave being edited (its id); undefined or null when adding.
  leaveId?: number | null;
}

// A box of the form as text, read as a number. The caller has already checked that it is set.
const numberOf = (text: string): number => Number(text);

export function LeaveCheck({ values, leaveId }: LeaveCheckProps) {
  const { mutateAsync } = useCheckLeave();
  // The latest mutateAsync, read by the effect: a new object from the hook must not restart a waiting question.
  const mutateRef = useRef(mutateAsync);
  mutateRef.current = mutateAsync;
  const [answer, setAnswer] = useState<LeaveCheckOut | null>(null);
  // Counts the questions asked. An answer is shown only when no newer question was asked since it was sent.
  const latest = useRef(0);
  // The key of the values last seen. The first render is not a change, so nothing is asked on mount.
  const seen = useRef<string | null>(null);
  const { employee, leave_type, start_date, end_date } = values;
  const note = values.note ?? "";
  const overrideReason = values.override_reason ?? "";
  const key = JSON.stringify([employee, leave_type, start_date, end_date, note, overrideReason, leaveId ?? null]);

  useEffect(() => {
    if (seen.current === key) return;
    const first = seen.current === null;
    seen.current = key;
    if (first) return;
    const ready = employee !== "" && leave_type !== "" && start_date !== "" && end_date !== "";
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (ready) {
      timer = setTimeout(() => {
        const token = ++latest.current;
        mutateRef
          .current({
            employee: numberOf(employee),
            leave_type: numberOf(leave_type),
            start_date,
            end_date,
            leave_id: leaveId ?? null,
            note,
            override_reason: overrideReason,
          })
          .then(
            (result) => {
              if (token === latest.current) setAnswer(result);
            },
            () => {
              if (token === latest.current) setAnswer(null);
            },
          );
      }, CHECK_DELAY_MS);
    } else {
      setAnswer(null);
    }
    // A new commit (or unmount) drops the waiting question and makes every question already sent out of date.
    return () => {
      clearTimeout(timer);
      latest.current += 1;
    };
    // Only the key: it carries every value the question reads, and a new object from the hook must not restart it.
  }, [key]);

  // The live region is always mounted, so a screen reader hears each answer as it is filled in. It is empty (and
  // unboxed) while there is nothing to show.
  const shown = answer !== null && (answer.valid || answer.errors.length > 0 || answer.warnings.length > 0);
  if (!shown || answer === null) return <div aria-live="polite" />;
  const { errors, warnings, working_days, balance_after, period } = answer;

  return (
    <div className="rounded-lg bg-slate-50 p-3 text-sm" aria-live="polite">
      {errors.map((message, index) => (
        <p key={index} className="text-red-700">
          {message}
        </p>
      ))}
      {errors.length === 0 ? (
        <p>
          <b>{working_days}</b> ажлын өдөр
          {balance_after !== null && balance_after !== undefined ? (
            <>
              {" "}· үлдэх: <b>{balance_after}</b>
            </>
          ) : null}
        </p>
      ) : null}
      {period ? (
        <p className="text-slate-500">
          Хугацаа: {period.start} – {period.end}
        </p>
      ) : null}
      {warnings.map((message, index) => (
        <p key={index} className="text-amber-700">
          {message}
        </p>
      ))}
    </div>
  );
}
