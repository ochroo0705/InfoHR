import type { LeaveCalendarCellOut, LeaveCalendarOut } from "../../api/leavePages";
import { AppLink } from "../../lib/AppLink";
import { cn } from "../../lib/utils";

// The team calendar's grid (app/leave/templates/leave/calendar.html, the table in its card). Classes, data attributes and
// element order are copied from the template. The card scrolls sideways; the first column (the name) is sticky.
// The cells come from the API: `kind` (annual, other, long, or empty) picks the colour, and an off day is slate whatever
// its cell says. Counted leave carries its leave type; long leave carries data-long-leave.

const KIND_CLASS: Record<string, string> = {
  annual: "bg-violet-200",
  other: "bg-amber-200",
  long: "bg-sky-200",
};
const TODAY_RING = "ring-2 ring-inset ring-violet-600 dark:ring-white";

export interface CalendarGridProps {
  view: LeaveCalendarOut;
}

function cellClass(cell: LeaveCalendarCellOut, off: boolean, today: boolean): string {
  return cn(
    "h-6 w-6 border border-surface",
    off ? "bg-slate-100 dark:bg-slate-300" : (KIND_CLASS[cell.kind] ?? ""),
    today && TODAY_RING,
  );
}

export function CalendarGrid({ view }: CalendarGridProps) {
  return (
    <div className="card-soft mt-3 overflow-x-auto p-3">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-surface pr-2 text-left">Ажилтан</th>
            {view.days.map((day) => (
              <th
                key={day.date}
                className={cn(
                  "w-6 text-center",
                  day.today ? `font-semibold rounded ${TODAY_RING}` : "font-normal",
                  day.holiday && "text-red-600",
                )}
                data-holiday={day.holiday ? day.date : undefined}
                data-today={day.today ? day.date : undefined}
              >
                {day.day}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {view.lines.map((line) => (
            <tr key={line.employee_id}>
              <td className="sticky left-0 bg-surface py-1 pr-2 whitespace-nowrap">
                <AppLink to={`/employees/${line.employee_id}/`}>{line.employee_name}</AppLink>
              </td>
              {line.cells.map((cell, index) => {
                const day = view.days[index];
                const off = day?.off ?? false;
                const today = day?.today ?? false;
                return (
                  <td
                    key={index}
                    className={cellClass(cell, off, today)}
                    data-leave={cell.kind === "annual" || cell.kind === "other" ? (cell.leave_type_id ?? undefined) : undefined}
                    title={cell.title || undefined}
                    data-long-leave={cell.kind === "long" ? true : undefined}
                  />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
