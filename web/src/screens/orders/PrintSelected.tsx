import type { FormEvent } from "react";
import { PrintJobBadge, usePrintJob } from "./PrintJobBadge";
import { shouldBackground } from "./printJobLogic";

// The «Сонгосныг хэвлэх» form (orders.html #order-print-form) and its button, with the job badge beside it. Fewer orders
// than backgroundFrom post the form as before, to a new tab. From backgroundFrom on, the submit becomes a background job
// (one at a time). The threshold and the rights come from the API; this screen only counts the picks.

export interface PrintSelectedProps {
  picked: number[];
  backgroundFrom: number;
  csrfToken: string;
}

export function PrintSelected({ picked, backgroundFrom, csrfToken }: PrintSelectedProps) {
  const { job, start, retry, close } = usePrintJob();
  const count = picked.length;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    if (!shouldBackground(count, backgroundFrom)) return;
    event.preventDefault();
    start(picked);
  }

  return (
    <>
      <form
        id="order-print-form"
        method="post"
        action="/api/v1/orders/print/selected"
        target="_blank"
        className="contents"
        onSubmit={onSubmit}
      >
        <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} />
        {picked.map((id) => (
          <input key={id} type="hidden" name="ids" value={id} />
        ))}
        <button
          type="submit"
          id="order-print-selected"
          disabled={count === 0}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm enabled:hover:bg-slate-50 disabled:text-slate-400"
        >
          Сонгосныг хэвлэх{count > 0 ? ` (${count})` : ""}
        </button>
      </form>
      <PrintJobBadge job={job} onRetry={retry} onClose={close} />
    </>
  );
}
