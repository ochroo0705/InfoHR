import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ScrollFloat } from "../../widgets/Scrollbar";

type PersonalListOut = components["schemas"]["EmployeePersonalListOut"];
type PersonalColumn = PersonalListOut["columns"][number];
type PersonalListRow = PersonalListOut["rows"][number];

// Port of `_list_section.html` (a pop-up list: head, then its table), `_inline_list.html` (a list edited in its own
// rows: the same head, a wrapper with data-inline-list, and the action cell) and the read rows of `_inline_row.html`.
// Classes, Mongolian text, element order and data-* hooks are copied from the templates. React renders the strings the
// API sends (title, empty label, column classes, cell text). The «+ нэмэх» button, the row click and the action cell
// follow `editable`, the flag the API sends for can_manage. Every write opens the Django employee page (openLegacyEmployee,
// ruling D2): no fetch.

// The head: the title, «бүртгэгдээгүй» beside it when the list is empty, «+ нэмэх» on the right when editable.
function ListHead({ list, pk, editable }: { list: PersonalListOut; pk: number; editable: boolean }) {
  return (
    <div className="flex items-baseline gap-3">
      <h3 className="sec-title">
        {list.title}
        {list.empty_label && (
          <>
            {" "}
            <span className="ml-1 text-sm font-normal text-slate-400">{list.empty_label}</span>
          </>
        )}
      </h3>
      {editable && (
        <button
          type="button"
          onClick={() => openLegacyEmployee(pk)}
          className="ml-auto rounded px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-50"
        >
          + нэмэх
        </button>
      )}
    </div>
  );
}

// The cells of one row, with the column's <td> class (empty when the template has none).
function RowCells({ columns, cells }: { columns: PersonalColumn[]; cells: string[] }) {
  return (
    <>
      {cells.map((cell, index) => (
        <td key={index} className={columns[index]?.cell_class || undefined}>
          {cell}
        </td>
      ))}
    </>
  );
}

// One row of a pop-up list: the whole row opens the Django pop-up (legacy) when editable.
function PopupRow({
  row,
  columns,
  pk,
  editable,
}: {
  row: PersonalListRow;
  columns: PersonalColumn[];
  pk: number;
  editable: boolean;
}) {
  return (
    <tr
      className={editable ? " cursor-pointer hover:bg-violet-50" : ""}
      onClick={editable ? () => openLegacyEmployee(pk) : undefined}
    >
      <RowCells columns={columns} cells={row.cells} />
    </tr>
  );
}

// One row of an inline list: it carries its key, and the action cell exists only when editable.
function InlineRow({
  row,
  columns,
  pk,
  editable,
}: {
  row: PersonalListRow;
  columns: PersonalColumn[];
  pk: number;
  editable: boolean;
}) {
  return (
    <tr
      data-row-key={row.key}
      className={editable ? " cursor-pointer hover:bg-violet-50" : ""}
      onClick={editable ? () => openLegacyEmployee(pk) : undefined}
    >
      <RowCells columns={columns} cells={row.cells} />
      {editable && <td></td>}
    </tr>
  );
}

// One personal-tab list in read mode. A list with `inline` true is edited in its own rows (`_inline_list.html`), the
// others in a pop-up (`_list_section.html`). The section wrapper (#sec-<kind>) belongs to the caller.
export function PersonalList({ list, pk, editable }: { list: PersonalListOut; pk: number; editable: boolean }) {
  if (list.inline) {
    return (
      <div id={`list-${list.kind}`} data-inline-list="">
        <ListHead list={list} pk={pk} editable={editable} />
        {list.rows.length > 0 && (
          <ScrollFloat className="ptable">
            <table>
              <thead>
                <tr>
                  {list.columns.map((col, index) => (
                    <th key={index} className={col.head_class || undefined}>
                      {col.header}
                    </th>
                  ))}
                  {editable && <th className="w-px"></th>}
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => (
                  <InlineRow key={row.key} row={row} columns={list.columns} pk={pk} editable={editable} />
                ))}
              </tbody>
            </table>
          </ScrollFloat>
        )}
      </div>
    );
  }
  return (
    <>
      <ListHead list={list} pk={pk} editable={editable} />
      {list.rows.length > 0 && (
        <ScrollFloat className="ptable">
          <table>
            <thead>
              <tr>
                {list.columns.map((col, index) => (
                  <th key={index} className={col.head_class || undefined}>
                    {col.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.rows.map((row) => (
                <PopupRow key={row.key} row={row} columns={list.columns} pk={pk} editable={editable} />
              ))}
            </tbody>
          </table>
        </ScrollFloat>
      )}
    </>
  );
}
