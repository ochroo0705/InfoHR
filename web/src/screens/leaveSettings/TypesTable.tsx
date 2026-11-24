import type { KeyboardEvent } from "react";
import type { LeaveTypeOut } from "../../api/leaveSetup";
import { cn } from "../../lib/utils";

// The types table of the settings page (port of the table in app/leave/templates/leave/settings.html). Classes, texts and
// the column order are copied from the template. A row opens its type's pop-up: a click, or Enter and Space on the focused
// row (the same keys as the balances rows, with no role="button" on the row).
const COLUMNS = 5;
const EMPTY_TEXT = "Чөлөөний төрөл бүртгээгүй";

function yesNo(flag: boolean): string {
  return flag ? "Тийм" : "Үгүй";
}

export interface TypesTableProps {
  types: LeaveTypeOut[];
  onOpen: (id: number) => void;
}

export function TypesTable({ types, onOpen }: TypesTableProps) {
  return (
    <table className="mt-3 w-full text-sm">
      <thead className="text-left text-slate-500">
        <tr>
          <th className="py-2">Нэр</th>
          <th>Цалинтай</th>
          <th>Ээлжийн амралтаас хасна</th>
          <th>Идэвхтэй</th>
          <th>Ажилтан хүсэлт гаргана</th>
        </tr>
      </thead>
      <tbody>
        {types.map((type) => {
          const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
            if (event.target !== event.currentTarget) return;
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            onOpen(type.id);
          };
          return (
            <tr
              key={type.id}
              tabIndex={0}
              onClick={() => onOpen(type.id)}
              onKeyDown={onKeyDown}
              className={cn(
                "border-t border-slate-100 hover:bg-violet-50 cursor-pointer focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500",
                !type.is_active && "text-slate-400 line-through",
              )}
            >
              <td className="py-2">{type.name}</td>
              <td>{yesNo(type.is_paid)}</td>
              <td>{yesNo(type.uses_annual_balance)}</td>
              <td>{yesNo(type.is_active)}</td>
              <td>{yesNo(type.staff_may_request)}</td>
            </tr>
          );
        })}
        {types.length === 0 ? (
          <tr>
            <td colSpan={COLUMNS} className="py-6 text-center text-slate-500">
              {EMPTY_TEXT}
            </td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
