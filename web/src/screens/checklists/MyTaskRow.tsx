// One row of «Миний даалгавар» (checklists/_my_tasks.html): the title, the employee and kind, the due date, and the
// «Хийгдсэн» button when `onTick` is given. Shared by the My page card (me/MyTasks.tsx) and the checklists/mine page.
export type MyTaskRowData = {
  title: string;
  employee: string;
  kind_label: string;
  due: string;
  overdue: boolean;
};

export function MyTaskRow({
  task,
  onTick,
  pending,
}: {
  task: MyTaskRowData;
  onTick?: () => void;
  pending: boolean;
}) {
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-3">
      <span className="min-w-0">
        <span className="block font-medium">{task.title}</span>
        <span className="block text-sm text-slate-500">
          {task.employee} · <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">{task.kind_label}</span>
        </span>
        <span className={`block text-sm ${task.overdue ? "font-medium text-red-700" : "text-slate-500"}`}>
          Хугацаа {task.due}
        </span>
      </span>
      {onTick ? (
        <div className="shrink-0">
          <button
            type="button"
            disabled={pending}
            onClick={onTick}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Хийгдсэн
          </button>
        </div>
      ) : null}
    </li>
  );
}
