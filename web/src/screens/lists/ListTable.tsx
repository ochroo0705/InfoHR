import type { KeyboardEvent } from "react";
import type { ListColumnOut, ListRowOut } from "../../api/lists";

// The table of one list (app/lists/templates/lists/list.html). Classes, the empty-row text and the element order are
// copied from the template. React decides nothing: the header labels, the cell text (a choice column already shows its
// label) and the rows all come from the API.
//
// Keyboard (the row rule of UI_RULES.md §4, as in logs/EmployeeLogTable.tsx): every row opens its pop-up, so every row
// is a tab stop (tabIndex=0). Enter or Space on the row itself opens it, and the row shows a focus-visible outline.

export interface ListTableProps {
  columns: ListColumnOut[];
  rows: ListRowOut[];
  // Opens the edit pop-up of entry `pk`.
  onOpen: (pk: number) => void;
}

export function ListTable({ columns, rows, onOpen }: ListTableProps) {
  return (
    <table className="mt-4 w-full overflow-hidden rounded-xl border border-slate-200 bg-surface text-sm">
      <thead className="text-left text-slate-500">
        <tr>
          {columns.map((column) => (
            <th key={column.name} className="px-4 py-2 font-normal">
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.id}
            tabIndex={0}
            className="cursor-pointer border-t border-slate-100 hover:bg-violet-50 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
            onClick={() => onOpen(row.id)}
            onKeyDown={(event: KeyboardEvent<HTMLTableRowElement>) => {
              // Keys from an inner control are not the row's; a row has none, but the rule stays the same as the log rows.
              if (event.target !== event.currentTarget) return;
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onOpen(row.id);
            }}
          >
            {row.cells.map((value, index) => (
              <td key={index} className="px-4 py-2">
                {value}
              </td>
            ))}
          </tr>
        ))}
        {rows.length === 0 ? (
          <tr>
            <td colSpan={columns.length} className="py-6 text-center text-slate-400">
              бүртгэгдээгүй
            </td>
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
