import type { EmployeeWorkOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ScrollFloat } from "../../widgets/Scrollbar";

// Port of `checklists/_employee_section.html` (one panel per kind, in the Work tab after the leave block) and of
// `checklists/_task_row.html`. Classes, Mongolian text, element order and data-* hooks are copied from the templates.
// The API sends the strings, the class strings and the flags (done_label, done_rest, title_class, due_class). Every
// write (cancel, the start form, tick, untick) opens the Django employee page (openLegacyEmployee, ruling D2). The start
// form's date box is read-only until step 3b, so a change here is not lost to a page that does not post it.

type Work = EmployeeWorkOut;
type Panel = Work["checklists"][number];
type Task = Panel["rows"][number];

// One task row (`_task_row.html`). «Хийгдсэн» is emphasised green; done_rest carries the rest of the text.
function TaskRow({ row, pk }: { row: Task; pk: number }) {
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
            onClick={() => openLegacyEmployee(pk)}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm text-white hover:bg-violet-700"
          >
            Хийгдсэн
          </button>
        )}{" "}
        {row.can_untick && (
          <button
            type="button"
            onClick={() => openLegacyEmployee(pk)}
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
            onClick={() => openLegacyEmployee(pk)}
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
                  <TaskRow key={i} row={row} pk={pk} />
                ))}
              </tbody>
            </table>
          </ScrollFloat>
        </>
      ) : panel.can_start ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            openLegacyEmployee(pk);
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <label className="text-sm">
            <span className="block text-slate-500">Сүүлийн ажлын өдөр</span>
            <input
              type="date"
              name="anchor_day"
              value={panel.today}
              readOnly
              required
              className="rounded-lg border border-slate-300 bg-surface px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Ажлаас гарах жагсаалт эхлүүлэх
          </button>
        </form>
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
