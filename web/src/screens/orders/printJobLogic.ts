// The state machine of the background print job («Сонгосныг хэвлэх» with many orders), as print_job.js runs it.
// Pure: no timers, no requests. The hook in PrintJobBadge.tsx drives it.

// How often the status is asked while the PDF is built (print_job.js: 1500 ms).
export const POLL_MS = 1500;

// The text shown when a job fails without a reason of its own (print_job.js).
export const DEFAULT_FAIL_MESSAGE = "Бэлтгэж чадсангүй.";

export type JobState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "ready"; file: string }
  | { kind: "failed"; message: string };

export type JobEvent =
  | { type: "start" }
  | { type: "ready"; file: string }
  | { type: "failed"; message?: string }
  | { type: "close" };

// A start while a job runs changes nothing: one job at a time. A failed message without text falls back to the default.
export function reduceJob(state: JobState, event: JobEvent): JobState {
  switch (event.type) {
    case "start":
      return state.kind === "running" ? state : { kind: "running" };
    case "ready":
      return { kind: "ready", file: event.file };
    case "failed":
      return { kind: "failed", message: event.message || DEFAULT_FAIL_MESSAGE };
    case "close":
      return { kind: "idle" };
  }
}

// Fewer orders than the threshold are printed by the plain form post; the threshold comes from the API.
export function shouldBackground(count: number, backgroundFrom: number): boolean {
  return count >= backgroundFrom;
}
