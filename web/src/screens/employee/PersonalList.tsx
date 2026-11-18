import { useEffect, useRef, useState } from "react";
import type { components } from "../../api/schema";
import { ScrollFloat } from "../../widgets/Scrollbar";
import { EmptyListNotes, type EmptyListOut, InlineOpenRow } from "./InlineRow";
import { RowModal } from "./RowModal";

type PersonalListOut = components["schemas"]["EmployeePersonalListOut"];
type PersonalColumn = PersonalListOut["columns"][number];
type PersonalListRow = PersonalListOut["rows"][number];

// Port of `_list_section.html` (a pop-up list: head, then its table), `_inline_list.html` (a list edited in its own
// rows: the same head, a wrapper with data-inline-list, the open row and the action cell) and the read rows of
// `_inline_row.html`. Classes, Mongolian text, element order and data-* hooks are copied from the templates. React renders
// the strings the API sends (title, empty label, column classes, cell text). The «+ нэмэх» button, the row click and the
// action cell follow `editable`, the flag the API sends for can_manage. An inline list's writes happen in its own rows
// (InlineRow.tsx, Task 15b); a pop-up list's writes happen in its pop-up (RowModal.tsx, Task 15c).

// The open row of an inline list: none, the add row ("new"), or the row with that key (the API's row key, as a string).
type OpenKey = "new" | string | null;

// The head: the title, «бүртгэгдээгүй» beside it when the list is empty, «+ нэмэх» on the right when shown.
function ListHead({
  list,
  showAdd,
  emptyLabel,
  onAdd,
}: {
  list: PersonalListOut;
  showAdd: boolean;
  emptyLabel: string;
  onAdd: () => void;
}) {
  return (
    <div className="flex items-baseline gap-3">
      <h3 className="sec-title">
        {list.title}
        {emptyLabel && (
          <>
            {" "}
            <span className="ml-1 text-sm font-normal text-slate-400">{emptyLabel}</span>
          </>
        )}
      </h3>
      {showAdd && (
        <button
          type="button"
          onClick={onAdd}
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

// One row of a pop-up list: the whole row opens its pop-up (RowModal, edit) when editable.
function PopupRow({
  row,
  columns,
  editable,
  onOpen,
}: {
  row: PersonalListRow;
  columns: PersonalColumn[];
  editable: boolean;
  onOpen: () => void;
}) {
  return (
    <tr className={editable ? " cursor-pointer hover:bg-violet-50" : ""} onClick={editable ? onOpen : undefined}>
      <RowCells columns={columns} cells={row.cells} />
    </tr>
  );
}

// The pop-up open on a pop-up list: the add form (rowKey null) or the edit form of one row. `serial` gives each open its
// own RowModal (a remount), so a new pop-up never shows the values of an old one. `open` false keeps it mounted while
// its exit plays.
type PopupTarget = { rowKey: number | null; serial: number; open: boolean };

// A pop-up list (`_list_section.html`): its head, its table, and one RowModal for the add or the edit (only one at a time).
function PopupList({ list, pk, editable }: { list: PersonalListOut; pk: number; editable: boolean }) {
  const [target, setTarget] = useState<PopupTarget | null>(null);
  const openPopup = (rowKey: number | null) =>
    setTarget((prev) => ({ rowKey, serial: (prev?.serial ?? 0) + 1, open: true }));
  // Closes only the pop-up that asked: a late answer from a RowModal of an earlier open (its serial is no longer the
  // current one) must not close the pop-up that replaced it.
  const closePopup = (serial: number) =>
    setTarget((prev) => (prev && prev.serial === serial ? { ...prev, open: false } : prev));

  return (
    <>
      <ListHead list={list} showAdd={editable} emptyLabel={list.empty_label} onAdd={() => openPopup(null)} />
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
                <PopupRow
                  key={row.key}
                  row={row}
                  columns={list.columns}
                  editable={editable}
                  onOpen={() => openPopup(Number(row.key))}
                />
              ))}
            </tbody>
          </table>
        </ScrollFloat>
      )}
      {target !== null && (
        <RowModal
          key={target.serial}
          pk={pk}
          kind={list.kind}
          rowKey={target.rowKey}
          open={target.open}
          onClose={() => closePopup(target.serial)}
        />
      )}
    </>
  );
}

// One read row of an inline list: it carries its key and the action cell (when editable). A click opens the row for
// editing, and only when no row is open (`_inline_list.html`: the click is absent while open_key is set).
function InlineReadRow({
  row,
  columns,
  editable,
  clickable,
  onOpen,
}: {
  row: PersonalListRow;
  columns: PersonalColumn[];
  editable: boolean;
  clickable: boolean;
  onOpen: () => void;
}) {
  return (
    <tr
      data-row-key={row.key}
      className={clickable ? " cursor-pointer hover:bg-violet-50" : ""}
      onClick={clickable ? onOpen : undefined}
    >
      <RowCells columns={columns} cells={row.cells} />
      {editable && <td></td>}
    </tr>
  );
}

// An inline list: its head, its table with the open row (the add row at the bottom, or the edited row in place), and the
// red box for the open row's refused write. Only one row is open at a time; while one is, «+ нэмэх» and the row clicks
// are off (Django hides them when open_key is set).
function InlineList({ list, pk, editable }: { list: PersonalListOut; pk: number; editable: boolean }) {
  const [requested, setOpen] = useState<OpenKey>(null);
  const [listErrors, setListErrors] = useState<string[]>([]);
  // The open row's empty-list notes: drawn above the table (after the form, before the errors and the table, as
  // `_inline_list.html` orders them).
  const [notes, setNotes] = useState<EmptyListOut[]>([]);
  // A row that was open and is gone now (deleted elsewhere) is shown closed, as inline_context does.
  const open: OpenKey =
    requested === null || requested === "new" || list.rows.some((row) => row.key === requested) ? requested : null;
  const idle = editable && open === null;
  // The open key as the latest render has it: a write answer for another row is ignored (useInlineRow).
  const openRef = useRef<OpenKey>(null);
  openRef.current = open;
  const currentOpen = () => openRef.current;
  // The list was refetched without the open row (another user changed or removed it): the row closes, and the red box
  // keeps the message of the refused write.
  useEffect(() => {
    if (requested !== null && requested !== "new" && !list.rows.some((row) => row.key === requested)) {
      setOpen(null);
    }
  }, [requested, list.rows]);
  const close = () => {
    openRef.current = null;
    setOpen(null);
    setListErrors([]);
  };
  const showTable = list.rows.length > 0 || open === "new";

  return (
    <div id={`list-${list.kind}`} data-inline-list="">
      <ListHead
        list={list}
        showAdd={idle}
        emptyLabel={open === "new" ? "" : list.empty_label}
        onAdd={() => setOpen("new")}
      />
      <EmptyListNotes items={notes} />
      {listErrors.length > 0 && (
        <div className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700">
          {listErrors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      )}
      {showTable && (
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
              {list.rows.map((row) =>
                open === row.key ? (
                  <InlineOpenRow
                    key={row.key}
                    pk={pk}
                    list={list}
                    rowKey={row.key}
                    readCells={row.cells}
                    onClose={close}
                    onListErrors={setListErrors}
                    currentOpen={currentOpen}
                    onEmptyLists={setNotes}
                  />
                ) : (
                  <InlineReadRow
                    key={row.key}
                    row={row}
                    columns={list.columns}
                    editable={editable}
                    clickable={idle}
                    onOpen={() => setOpen(row.key)}
                  />
                ),
              )}
              {open === "new" && (
                <InlineOpenRow
                  key="new"
                  pk={pk}
                  list={list}
                  rowKey="new"
                  onClose={close}
                  onListErrors={setListErrors}
                  currentOpen={currentOpen}
                  onEmptyLists={setNotes}
                />
              )}
            </tbody>
          </table>
        </ScrollFloat>
      )}
    </div>
  );
}

// One personal-tab list in read mode. A list with `inline` true is edited in its own rows (`_inline_list.html`), the
// others in a pop-up (`_list_section.html`, RowModal). The section wrapper (#sec-<kind>) belongs to the caller.
export function PersonalList({ list, pk, editable }: { list: PersonalListOut; pk: number; editable: boolean }) {
  if (list.inline) {
    return <InlineList list={list} pk={pk} editable={editable} />;
  }
  return <PopupList list={list} pk={pk} editable={editable} />;
}
