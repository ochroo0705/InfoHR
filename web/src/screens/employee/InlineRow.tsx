import { useEffect, useRef, type KeyboardEvent } from "react";
import type { components } from "../../api/schema";
import { AppLink } from "../../lib/AppLink";
import { initialValue, SoftBox } from "../../widgets/FormFields";
import { useInlineRow } from "./useInlineRow";

type PersonalListOut = components["schemas"]["EmployeePersonalListOut"];
export type EmptyListOut = components["schemas"]["EmployeeFormEmptyListOut"];

// The amber notes of the open row's form (`_inline_list.html`: after the form, before the table). PersonalList draws them
// above its table; the notes are only shown while a row is open, as the template does.
export function EmptyListNotes({ items }: { items: EmptyListOut[] }) {
  return (
    <>
      {items.map((item) => (
        <p key={item.slug} className="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {item.label} жагсаалт хоосон байна.{" "}
          <AppLink to={`/lists/${item.slug}/`} className="text-violet-700 hover:underline">
            Жагсаалт
          </AppLink>{" "}
          хэсэгт нэмнэ үү.
        </p>
      ))}
    </>
  );
}

// The open row of an inline list (`_inline_row.html`): one soft box per column in its own <td>, then the action cell
// («Устгах» with its in-row question, ✓ and ✕). The row is a <form> target: the boxes post with `form="inline-<kind>-form"`
// and the ✓ button submits it, so Enter in a box saves (native implicit submission). Until the form loads, the cells show
// the row's read values (an edit) or are empty (an add), never a half-drawn form. Classes and Mongolian text are copied
// from `_inline_row.html`; the svgs are its own.

const CHECK_ICON = (
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8.5l3 3 7-7" />
  </svg>
);

const CROSS_ICON = (
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

// Moves the cursor into a row: its first box with an error, else its first box (sections.js afterSettle).
function focusInRow(row: HTMLElement | null) {
  if (!row) return;
  const invalid = row.querySelector<HTMLElement>('[aria-invalid="true"]');
  const box = invalid ?? row.querySelector<HTMLElement>("input:not([type=hidden]), textarea");
  box?.focus();
}

export function InlineOpenRow({
  pk,
  list,
  rowKey,
  readCells,
  onClose,
  onListErrors,
  currentOpen,
  onEmptyLists,
}: {
  pk: number;
  list: PersonalListOut;
  rowKey: string;
  // The row's cells as read, shown until the form loads (an edit only).
  readCells?: string[];
  onClose: () => void;
  onListErrors: (messages: string[]) => void;
  // The key of the row open now in the list (see useInlineRow).
  currentOpen: () => string | null;
  // Reports the form's empty lists to the list, which shows their notes above its table. [] when the row closes.
  onEmptyLists?: (items: EmptyListOut[]) => void;
}) {
  const kind = list.kind;
  const formId = `inline-${kind}-form`;
  const columnNames = list.columns.map((column) => column.field);
  const row = useInlineRow({ pk, kind, rowKey, columnNames, onClose, onListErrors, currentOpen });
  const rowRef = useRef<HTMLTableRowElement>(null);
  // The notes go to the list when the form's empty lists change, and are cleared when the row closes.
  const emptyKey = row.emptyLists.map((item) => item.slug).join("|");
  useEffect(() => {
    onEmptyLists?.(row.emptyLists);
    // Only the list's slugs decide the notes; a new empty array with the same slugs changes nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emptyKey]);
  useEffect(() => () => onEmptyLists?.([]), []);

  // The cursor goes to the row once its boxes are drawn, and again after a refused save.
  const focused = useRef(false);
  useEffect(() => {
    if (!row.loaded || focused.current) return;
    focused.current = true;
    focusInRow(rowRef.current);
  }, [row.loaded]);
  useEffect(() => {
    if (row.errorTick > 0) focusInRow(rowRef.current);
  }, [row.errorTick]);

  // Esc closes the row without saving, unless it only closes a dropdown or a calendar (sections.js; both popups call
  // preventDefault on Esc, and an open one is still in the DOM).
  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    if (document.querySelector(".sel-popup:not([data-leaving]), .dp-popup:not([data-leaving])")) return;
    onClose();
  };

  const cells = list.columns.map((column, index) => {
    const field = row.slots[index];
    if (field) {
      return (
        <td key={index} className="relative py-1.5 pr-2">
          <SoftBox
            field={field}
            value={row.values[field.name] ?? initialValue(field)}
            errors={row.errors[field.name] ?? []}
            onChange={row.setValue}
            formId={formId}
            id={`inline-${kind}-${field.name}`}
          />
        </td>
      );
    }
    // Not loaded (or a column with no box): the read value, or empty.
    return (
      <td key={index} className="relative py-1.5 pr-2">
        {row.loaded ? null : (readCells?.[index] ?? "")}
      </td>
    );
  });

  return (
    <>
      <tr
        ref={rowRef}
        data-inline-row
        data-row-key={rowKey}
        data-leaving={row.leaving ? "" : undefined}
        aria-busy={row.pending || undefined}
        className={
          "is-picked align-top" +
          (row.leaving ? " opacity-0 transition-opacity duration-[var(--dur-out)]" : "")
        }
        onKeyDown={onKeyDown}
      >
        {cells}
        <td className="py-1.5">
          <form
            id={formId}
            noValidate
            className="contents"
            onSubmit={(event) => {
              event.preventDefault();
              void row.save();
            }}
          >
            <div className="flex items-center justify-end gap-1 whitespace-nowrap">
              {row.canDelete && !row.confirming ? (
                <span>
                  <button
                    type="button"
                    onClick={() => row.setConfirming(true)}
                    className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                  >
                    Устгах
                  </button>
                </span>
              ) : null}
              {row.canDelete && row.confirming ? (
                <span className="text-xs text-slate-700">
                  Устгах уу?
                  <button
                    type="button"
                    data-inline-delete
                    onClick={() => void row.remove()}
                    className="rounded px-1.5 py-1 font-medium text-red-600 hover:bg-red-50"
                  >
                    Тийм
                  </button>
                  <button
                    type="button"
                    onClick={() => row.setConfirming(false)}
                    className="rounded px-1.5 py-1 hover:bg-slate-100"
                  >
                    Үгүй
                  </button>
                </span>
              ) : null}
              <button
                type="submit"
                disabled={row.pending}
                aria-busy={row.pending || undefined}
                title="Хадгалах (Enter)"
                aria-label="Хадгалах"
                className="rounded-md bg-violet-600 p-1.5 text-white hover:bg-violet-700 disabled:opacity-60"
              >
                {CHECK_ICON}
              </button>
              <button
                type="button"
                data-inline-cancel
                onClick={onClose}
                title="Болих (Esc)"
                aria-label="Болих"
                className="rounded-md border border-slate-300 bg-surface p-1.5 text-slate-600 hover:bg-slate-50"
              >
                {CROSS_ICON}
              </button>
            </div>
          </form>
        </td>
      </tr>
    </>
  );
}
