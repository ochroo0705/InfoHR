import { useEffect, useReducer, useRef } from "react";
import { fetchPrintStatus, useStartPrintJob } from "../../api/orderRegister";
import { DEFAULT_FAIL_MESSAGE, POLL_MS, reduceJob, type JobEvent, type JobState } from "./printJobLogic";

// The «Бэлтгэж байна…» badge (orders.html #print-job, UI_RULES §8b). Classes, Mongolian text and the data-pj hooks are
// copied from the template. All three states are rendered; the two not shown carry `hidden`, as in the template, so the
// CSS keyed on data-state keeps working.

export interface PrintJobBadgeProps {
  job: JobState;
  onRetry: () => void;
  onClose: () => void;
}

export function PrintJobBadge({ job, onRetry, onClose }: PrintJobBadgeProps) {
  return (
    <div
      id="print-job"
      hidden={job.kind === "idle"}
      data-state={job.kind}
      role="status"
      aria-live="polite"
      className="print-job inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700"
    >
      <span data-pj="running" hidden={job.kind !== "running"} className="inline-flex items-center gap-2">
        <span className="pj-dots inline-flex items-center gap-1" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
        Бэлтгэж байна…
      </span>
      <span data-pj="ready" hidden={job.kind !== "ready"} className="inline-flex items-center gap-2">
        Бэлэн болсон{" "}
        <a
          data-pj-open
          href={job.kind === "ready" ? job.file : "#"}
          target="_blank"
          rel="noopener"
          className="rounded-lg bg-violet-600 px-3 py-1 text-white hover:bg-violet-700"
        >
          Нээх
        </a>
      </span>
      <span data-pj="failed" hidden={job.kind !== "failed"} className="inline-flex items-center gap-2 text-red-700">
        <span data-pj-message>{job.kind === "failed" ? job.message : DEFAULT_FAIL_MESSAGE}</span>
        <button type="button" data-pj-retry onClick={onRetry} className="underline">
          Дахин оролдох
        </button>
      </span>
      {job.kind !== "idle" && (
        <button
          type="button"
          data-pj-close
          aria-label="Хаах"
          onClick={onClose}
          className="text-slate-400 hover:text-slate-700"
        >
          ✕
        </button>
      )}
    </div>
  );
}

// The first form error of a failed API call (api/mutate.ts ApiFailure), or undefined when there is none.
function formErrorOf(error: unknown): string | undefined {
  const formErrors = (error as { formErrors?: unknown } | null)?.formErrors;
  return Array.isArray(formErrors) && typeof formErrors[0] === "string" ? formErrors[0] : undefined;
}

export interface PrintJob {
  job: JobState;
  start: (ids: number[]) => void;
  retry: () => void;
  close: () => void;
}

// Owns one background job: starts it with the ids, asks its status every POLL_MS (and once at once), and stops when it is
// ready, failed, closed or the screen goes. A start while one runs is ignored; a stale answer (after close or unmount)
// is dropped by the generation counter.
export function usePrintJob(): PrintJob {
  const startJob = useStartPrintJob();
  const [job, dispatch] = useReducer(reduceJob, { kind: "idle" });
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const running = useRef(false);
  const done = useRef(false);
  const generation = useRef(0);
  const lastIds = useRef<number[]>([]);

  function stop() {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
    running.current = false;
  }

  useEffect(
    () => () => {
      generation.current += 1;
      stop();
    },
    [],
  );

  // Ends the job once: a ready or failed job takes no later answer, so an in-flight poll cannot overwrite it.
  function finish(event: JobEvent) {
    done.current = true;
    stop();
    dispatch(event);
  }

  function poll(token: string, file: string, gen: number) {
    fetchPrintStatus(token)
      .then((info) => {
        if (gen !== generation.current || done.current) return;
        if (info.state === "ready") {
          finish({ type: "ready", file });
        } else if (info.state === "failed") {
          finish({ type: "failed", message: info.message });
        }
      })
      .catch(() => {
        if (gen !== generation.current || done.current) return;
        finish({ type: "failed" });
      });
  }

  function start(ids: number[]) {
    if (running.current) return;
    running.current = true;
    done.current = false;
    lastIds.current = ids;
    generation.current += 1;
    const gen = generation.current;
    dispatch({ type: "start" });
    startJob
      .mutateAsync(ids)
      .then((answer) => {
        if (gen !== generation.current) return;
        timer.current = setInterval(() => poll(answer.token, answer.file, gen), POLL_MS);
        poll(answer.token, answer.file, gen);
      })
      .catch((error: unknown) => {
        if (gen !== generation.current) return;
        // The API's own reason (form_errors) is shown, as print_job.js shows res.json.error; none means the default.
        finish({ type: "failed", message: formErrorOf(error) });
      });
  }

  function close() {
    generation.current += 1;
    stop();
    dispatch({ type: "close" });
  }

  return { job, start, retry: () => start(lastIds.current), close };
}
