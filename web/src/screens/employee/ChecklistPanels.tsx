import { useState } from "react";
import type { EmployeeWorkOut } from "../../api/employee";
import { useCancelChecklist, useStartOffboarding, useTickTask, useUntickTask } from "../../api/checklists";
import { formErrorText } from "../me/formErrorText";
import { DatePicker } from "../../widgets/DatePicker";
import { ScrollFloat } from "../../widgets/Scrollbar";

// Port of `checklists/_employee_section.html` (one panel per kind, in the Work tab after the leave block) and of
// `checklists/_task_row.html`. Classes, Mongolian text, element order and data-* hooks are copied from the templates.
// The API sends the strings, the class strings and the flags (done_label, done_rest, title_class, due_class). Every
// write (tick, untick, cancel, the start form) posts to /api/v1/checklists/... and refreshes the page data in place. A
// refused change (409, 400, 404) shows its message in a red line under its own panel. The start form's date box is the
// shared DatePicker (the `datepicker.js` text box: ISO text, calendar button), drawn with the template's own box classes.

type Work = EmployeeWorkOut;
type Panel = Work["checklists"][number];
type Task = Panel["rows"][number];

// One task row (`_task_row.html`). «Хийгдсэн» is emphasised green; done_rest carries the rest of the text. The row's
// buttons are disabled while `busy` (a write of the panel runs).
function TaskRow({
  row,
  busy,
  onTick,
  onUntick,
}: {
  row: Task;
  busy: boolean;
  onTick: (id: number) => void;
  onUntick: (id: number) => void;
}) {
  return (
    <tr>
      <td className={row.title_class}>
        {row.title}
        {!row.required && (
          <>
            {" "}
            <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">Заавал биш</span>
          </>
        )}
      </td>
      <td className="whitespace-nowrap">{row.owner_label}</td>
      <td className={row.due_class}>{row.due_on}</td>
      <td className="whitespace-nowrap text-xs text-slate-500">
        {row.done_label && <span className="font-medium text-emerald-700">{row.done_label}</span>}
        {row.done_rest}
      </td>
      <td className="whitespace-nowrap text-right">
        {row.can_tick && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onTick(row.id)}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm text-white hover:bg-violet-700"
          >
            Хийгдсэн
          </button>
        )}{" "}
        {row.can_untick && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onUntick(row.id)}
            className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-violet-50 hover:text-violet-700"
          >
            Буцаах
          </button>
        )}
      </td>
    </tr>
  );
}

function PanelSection({ panel, pk }: { panel: Panel; pk: number }) {
  const [anchorDay, setAnchorDay] = useState(panel.today);
  // The day the box was last set from: when `today` changes (past midnight, a new load) the box shows the new day.
  const [anchorToday, setAnchorToday] = useState(panel.today);
  if (anchorToday !== panel.today) {
    setAnchorToday(panel.today);
    setAnchorDay(panel.today);
  }
  const [error, setError] = useState("");
  const tick = useTickTask();
  const untick = useUntickTask();
  const cancel = useCancelChecklist();
  const start = useStartOffboarding(pk);

  // One write at a time in this panel: while any of them runs, every button of the panel is disabled.
  const writing = tick.isPending || untick.isPending || cancel.isPending || start.isPending;

  // Runs one write. Each write starts from a clear line; a refusal fills it with the Django message (every refusal is
  // shown, not only the last one), a success leaves it empty.
  async function run(write: () => Promise<unknown>, onDone?: () => void) {
    setError("");
    try {
      await write();
      onDone?.();
    } catch (e) {
      setError(formErrorText(e));
    }
  }

  return (
    <section className="mt-10" data-checklist data-checklist-kind={panel.kind}>
      <div className="mb-3 flex items-center gap-2">
        <h3 className="sec-title mr-auto">{panel.heading}</h3>
        {panel.checklist && (
          <span
            className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700"
            data-checklist-progress
          >
            {panel.progress}
          </span>
        )}
        {panel.can_cancel && (
          <button
            type="button"
            disabled={writing}
            onClick={() => {
              const checklistId = panel.checklist_id;
              if (checklistId === null) return;
              // A cancelled panel shows the start form again with today's date, not the last typed one.
              void run(() => cancel.mutateAsync(checklistId), () => setAnchorDay(panel.today));
            }}
            className="rounded px-2 py-1 text-sm text-red-600 hover:bg-red-50"
          >
            Цуцлах
          </button>
        )}
      </div>
      {panel.checklist ? (
        <>
          <p className="mb-2 text-xs text-slate-500">
            {panel.caption}
            {panel.completed && (
              <>
                {" "}
                · <span className="font-medium text-emerald-700">Дууссан</span>
              </>
            )}
          </p>
          <ScrollFloat className="ptable">
            <table>
              <thead>
                <tr>
                  <th>Даалгавар</th>
                  <th>Хариуцагч</th>
                  <th>Хугацаа</th>
                  <th>Биелэлт</th>
                  <th className="w-px"></th>
                </tr>
              </thead>
              <tbody>
                {panel.rows.map((row, i) => (
                  <TaskRow
                    key={i}
                    row={row}
                    busy={writing}
                    onTick={(id) => void run(() => tick.mutateAsync(id))}
                    onUntick={(id) => void run(() => untick.mutateAsync(id))}
                  />
                ))}
              </tbody>
            </table>
          </ScrollFloat>
        </>
      ) : panel.can_start ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => start.mutateAsync(anchorDay));
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <label className="text-sm">
            <span className="block text-slate-500">Сүүлийн ажлын өдөр</span>
            <DatePicker
              name="anchor_day"
              value={anchorDay}
              onChange={setAnchorDay}
              required
              className="rounded-lg border border-slate-300 bg-surface px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={writing}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Ажлаас гарах жагсаалт эхлүүлэх
          </button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export function ChecklistPanels({ work, pk }: { work: Work; pk: number }) {
  if (!work.checklist_visible) return null;
  return (
    <>
      {work.checklists.map((panel) => (
        <PanelSection key={panel.kind} panel={panel} pk={pk} />
      ))}
    </>
  );
}
