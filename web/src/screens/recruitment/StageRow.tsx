import { useRef, useState } from "react";
import type { components } from "../../api/schema";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { cn } from "../../lib/utils";
import { confirm } from "../../widgets/confirm";

// The stage row of a candidate page (port of the stepper in app/recruitment/templates/recruitment/candidate_detail.html).
// A step the user may move to is a button; the others are plain text, the current one carries aria-current="step".
// A move listed in `moveConfirm` asks first. A refused move throws an Error whose message is shown under the row, and
// the next successful move clears it. Buttons are locked while a move runs.

export type ProgressItem = components["schemas"]["RecruitProgressOut"];

export interface StageRowProps {
  progress: ProgressItem[];
  moveTo: string[];
  moveConfirm: string[];
  // Resolves when the move saved; rejects with an Error carrying the refusal text otherwise.
  onMove: (stage: string) => Promise<void>;
}

const HELP = "Шат дээр дарж ажил хүсэгчийг шилжүүлнэ. «Ажилд авсан» шатанд «Ажилд авах» товчоор оруулна.";

export function StageRow({ progress, moveTo, moveConfirm, onMove }: StageRowProps) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const move = async (item: ProgressItem) => {
    if (inFlight.current) return;
    if (moveConfirm.includes(item.key)) {
      const yes = await confirm(`«${item.label}» шат руу шилжүүлэх үү?`);
      if (!yes) return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      await onMove(item.key);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error && error.message ? error.message : SAVE_FAILED_TEXT);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  return (
    <div className="mt-3 text-sm">
      <ol className="flex flex-wrap items-center gap-1.5" aria-label="Шат">
        {progress.map((item, index) => {
          const done = item.state === "done";
          const current = item.state === "current";
          const movable = moveTo.includes(item.key);
          return (
            <li key={item.key} className="flex items-center gap-1.5">
              {index > 0 ? (
                <span className="hidden text-slate-300 sm:inline" aria-hidden="true">
                  ›
                </span>
              ) : null}
              {movable ? (
                <button
                  type="button"
                  title={`${item.label} шат руу шилжүүлэх`}
                  disabled={pending}
                  onClick={() => void move(item)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 hover:bg-violet-50 disabled:opacity-50",
                    done ? "border-violet-200 bg-violet-50 text-violet-800" : "border-slate-300 text-slate-600",
                  )}
                >
                  {done ? "✓ " : ""}
                  {item.label}
                </button>
              ) : (
                <span
                  aria-current={current ? "step" : undefined}
                  className={cn(
                    "rounded-full border px-3 py-1.5",
                    current
                      ? "border-violet-600 bg-violet-600 font-medium text-white"
                      : done
                        ? "border-violet-200 bg-violet-50 text-violet-800"
                        : "border-transparent text-slate-500",
                  )}
                >
                  {done ? "✓ " : ""}
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {moveTo.length > 0 ? <p className="mt-1 text-xs text-slate-500">{HELP}</p> : null}
      <div role="alert" className="mt-2 text-sm text-red-600">
        {message}
      </div>
    </div>
  );
}
