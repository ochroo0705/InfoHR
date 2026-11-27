import { useCallback, useEffect, useMemo, useRef, type ClipboardEvent } from "react";
import { useReportRows, type ReportCellOut, type ReportGroupOut, type ReportTableOut } from "../../api/reports";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { ScrollHost } from "../../widgets/Scrollbar";
import { HeaderRow, type CheckColumn, type HeaderSelect } from "./HeaderRow";
import { ReportCell, inlineStyle } from "./ReportCell";
import { gridBodyRows, openRecord, ReportRows, rowPerson, type RowsCursor } from "./ReportRows";
import { SelectionBar } from "./SelectionBar";
import { CellEditor, isPanelEditor, type MoveDir } from "./grid/CellEditor";
import { columnMarks, EditLegend } from "./grid/EditMarks";
import { box, inEditorSurface, isComposingKey, isPrintable, move, type Pos } from "./grid/gridMath";
import { BulkBar } from "./grid/BulkBar";
import { useBulkEdit } from "./grid/useBulkEdit";
import { isGridTarget, useGridCursor, type GridKeyEvent } from "./grid/useGridCursor";
import { bufferName, NO_EDIT_MSG, targetKey, useCellEdit } from "./grid/useCellEdit";
import { headerMark, isOn, isPicked } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";
import { useStickyHeader } from "./useStickyHeader";

// The table of a report page (app/reports/templates/reports/_table.html, _rows.html, _batch_rows.html). The API draws the
// heads, the cells, the groups and the footer; this component only lays them out and loads the next batch.
// Cells are read-only here, and there is no editing (step 5f). `table` is the page's own first batch; further batches come
// from the rows route through the «Цааш харуулах» pill. With `selection` (a selectable table of a report with a person),
// the selection column has its checkboxes and the selection bar sits above the table (step 5d).

// The row selection of the page. `api` is the hook's result; the page passes this only when the report is selectable.
export interface ReportTableSelection {
  api: ReportSelection;
  urls: Record<string, string>;
  maxPeople: number;
  reportKey: string;
}

export interface ReportTableProps {
  reportKey: string;
  query: string; // the address query, sent as typed (see api/reports.ts)
  table: ReportTableOut;
  dataUpdatedAt: number; // the page query's dataUpdatedAt: a page refetch seeds a new rows query from the new first batch
  inert?: boolean; // the table is inert while a new address loads: no sticky header copy is drawn meanwhile
  selection?: ReportTableSelection;
  // The editable-column marks and their legend (UI_RULES §4b). The page holds the choice (EditMarks.useEditMarks) and the
  // kinds the page's answer lists (head.edit_marks). Marks default on; the legend shows only with an editable kind.
  marksOn?: boolean;
  editKinds?: string[];
}

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

// The groups as drawn: each saved text (useCellEdit overrides, keyed by the cell's edit target) replaces the text of the
// cell that has that target, wherever it sits. The money formatting is dropped with the value, so the text shown is the
// text saved.
// A row with no saved cell is the same object as before (the memoised rows of ReportRows keep their identity), and a
// group with no changed row is the same object too.
export function withSavedTexts(groups: ReportGroupOut[], saved: ReadonlyMap<string, string>): ReportGroupOut[] {
  if (saved.size === 0) return groups;
  return groups.map((group) => {
    let groupChanged = false;
    const rows = group.rows.map((row) => {
      let rowChanged = false;
      const cells = row.map((cell) => {
        const text = cell.edit ? saved.get(targetKey(cell.edit)) : undefined;
        if (text === undefined) return cell;
        rowChanged = true;
        return { ...cell, text, money: false, value: null };
      });
      if (!rowChanged) return row;
      groupChanged = true;
      return cells;
    });
    return groupChanged ? { ...group, rows } : group;
  });
}

// The key each move of the editor stands for: Enter saves and goes down, Tab right, Shift+Tab left (grid_nav.js submit).
const MOVE_KEY: Record<MoveDir, string> = { down: "ArrowDown", right: "Tab", left: "ShiftTab" };

// The elements a key or a paste belongs to, not the grid (grid_nav.js isField).
const FIELD_SELECTOR = "input, select, textarea, button, summary, [contenteditable='true']";

export function ReportTable({
  reportKey,
  query,
  table,
  dataUpdatedAt,
  inert = false,
  selection,
  marksOn = true,
  editKinds = [],
}: ReportTableProps) {
  const rows = useReportRows(reportKey, query, table, dataUpdatedAt);
  const moreRef = useRef<HTMLButtonElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const go = useTransitionNavigate();

  // The selection column: a blank placeholder, with the API's class and pinned offset (_table.html). Its footer cell is
  // classed only when the first columns are pinned (Django's check_pinned).
  const check: CheckColumn | null = table.selectable ? { css: table.check_css, style: table.check_style } : null;
  const footerCheck: CheckColumn | null = check && table.pin > 0 ? check : check ? { css: "", style: "" } : null;

  const grouped = table.groups.some((group) => group.label !== "");
  const pages = useMemo(() => rows.data?.pages ?? [], [rows.data]);
  // The fixed copy of the header is measured again when the address, the answer or the batches loaded change.
  useStickyHeader(tableRef, `${query}|${dataUpdatedAt}|${pages.length}|${marksOn}`, inert);
  // An ungrouped table is one unlabelled group: its batches run on as one list of rows. Memoised, so the rows keep their
  // identity between key presses (ReportRows' memoised rows depend on it).
  const shown = useMemo<ReportGroupOut[]>(() => {
    const loaded = pages.flatMap((page) => page.groups);
    return grouped ? loaded : [{ label: "", count: 0, rows: loaded.flatMap((group) => group.rows) }];
  }, [pages, grouped]);

  // The person ids of the rows on screen, in draw order. They are registered with the selection on every render, as the
  // hook's contract asks, so the header box, the «all matching» offer and the picks read the rows as drawn.
  const visibleIds: string[] = shown.flatMap((group) =>
    group.rows.flatMap((row) => {
      const id = rowPerson(row);
      return id === null ? [] : [id];
    }),
  );
  if (selection) selection.api.setVisibleIds(visibleIds);
  const state = selection?.api.state ?? null;
  const selecting = state !== null && isOn(state);
  // body[data-selecting] is what the stylesheet reads to stop text selection in the picked rows (report_select.js sync).
  useEffect(() => {
    if (!selecting) return;
    document.body.dataset.selecting = "1";
    return () => {
      delete document.body.dataset.selecting;
    };
  }, [selecting]);
  const headSelect: HeaderSelect | null =
    selection && state ? { mark: headerMark(state, visibleIds), onPick: selection.api.pickVisible } : null;

  // The keyboard grid reads the rows as drawn (gridBodyRows), so a batch appended at the end keeps the cursor; a new address
  // clears it (resetKey). Enter opens the cell's link, else the row's first link; Space ticks the row's box.
  const hasCheck = check !== null;
  // The rows as the API sent them: the edit targets of the cells (what may open) and the people of the rows.
  const base = useMemo(() => gridBodyRows(shown, grouped, hasCheck, state), [shown, grouped, hasCheck, state]);
  const anyEditable = useMemo(() => base.some((row) => row.cells.some((cell) => cell?.edit != null)), [base]);
  // The editable-column marks of the loaded rows (EditMarks.columnMarks), when the marks are on.
  const colMarks = useMemo(() => columnMarks(base), [base]);
  const marks = marksOn ? colMarks : null;
  // The cell editor (grid_nav.js startEdit and submit). A new address or a refetch of the rows is a new epoch: the editor
  // closes and the saved texts are cleared.
  const edit = useCellEdit({
    resetKey: `${query}|${dataUpdatedAt}`,
    targetAt: (pos) => base[pos.r]?.cells[pos.c]?.edit ?? null,
  });
  // The rows with the saved texts only: a bulk batch starts from the texts the user sees before any preview.
  const savedRows = useMemo(() => withSavedTexts(shown, edit.overrides), [shown, edit.overrides]);
  const lookup = useMemo(
    () => gridBodyRows(savedRows, grouped, hasCheck, state),
    [savedRows, grouped, hasCheck, state],
  );
  // The bulk edit (UI_RULES §4 «Bulk edit on report tables»): paste, fill down, clear, and the preview of a batch.
  const bulk = useBulkEdit({
    resetKey: `${query}|${dataUpdatedAt}`,
    rows: lookup,
    currentEpoch: edit.currentEpoch,
    setTexts: edit.setTexts,
    onClosed: () => tableRef.current?.focus({ preventScroll: true }),
  });
  // The texts drawn: the saved texts, then the pending cells of a preview (by target, as a saved text is).
  const shownTexts = useMemo(
    () => (bulk.previews.size === 0 ? edit.overrides : new Map([...edit.overrides, ...bulk.previews])),
    [edit.overrides, bulk.previews],
  );
  // Without a preview the rows drawn are the saved rows, so they are built once (and gridBodyRows runs once for them).
  const previewing = bulk.previews.size > 0;
  const drawn = useMemo(
    () => (previewing ? withSavedTexts(shown, shownTexts) : savedRows),
    [previewing, shown, shownTexts, savedRows],
  );
  const body = useMemo(
    () => (drawn === savedRows ? lookup : gridBodyRows(drawn, grouped, hasCheck, state)),
    [drawn, savedRows, lookup, grouped, hasCheck, state],
  );
  const texts = useMemo(() => body.map((row) => row.texts), [body]);

  // F2, Enter or a typed key on the cursor cell (grid_nav.js keydown). A cell with an edit target opens its editor and the
  // key is taken; a cell without one shows the note on F2 (when the table has an editable column) and leaves the key to
  // the grid, so Enter opens the row's link and a typed key does nothing.
  const editKey = (pos: Pos, e: GridKeyEvent): boolean => {
    const target = base[pos.r]?.cells[pos.c]?.edit ?? null;
    if (!target) {
      if (e.key === "F2" && anyEditable) edit.note(NO_EDIT_MSG);
      return false;
    }
    e.preventDefault();
    edit.open(pos, isPrintable(e) ? e.key : undefined);
    return true;
  };

  const grid = useGridCursor({
    rows: texts,
    resetKey: query,
    onOpenRow: (r, c) => {
      const row = body[r];
      if (!row) return;
      const href = row.hrefs[c] || row.hrefs.find((h) => h !== "");
      if (href) openRecord(href, go);
    },
    onToggleRow: (r) => {
      const person = body[r]?.person;
      if (!selection || person == null) return false;
      selection.api.pickRow(person, !isPicked(selection.api.state, person));
    },
    onEditKey: editKey,
    // Ctrl+D fills the range down from its top row; Delete clears it (grid_nav.js keydown).
    onBulkKey: (_pos, range, e) => {
      if (e.key === "Delete") bulk.clear(range);
      else bulk.fillDown(range);
    },
  });

  // The row cells call these. They read the latest state through a ref, so the memoised rows keep the same props.
  // A click on a cell moves the cursor and closes an open editor without saving; while a save runs, a click does nothing
  // (Django's busy guard). A double click opens the cell's editor, is ignored on a group heading, and shows the note on a
  // cell that cannot be edited.
  const cellActions = useRef({
    click: (_r: number, _c: number, _shift: boolean) => {},
    dbl: (_r: number, _c: number) => {},
  });
  cellActions.current = {
    click: (r, c, shift) => {
      if (edit.isSaving()) return;
      if (edit.current()) edit.cancel();
      grid.onCellClick(r, c, shift);
    },
    dbl: (r, c) => {
      if (edit.isSaving() || bulk.active()) return; // no editor while a bulk preview is open (Django startEdit)
      const row = base[r];
      if (!row || row.heading) return;
      if (row.cells[c]?.edit) edit.open({ r, c });
      else if (anyEditable) edit.note(NO_EDIT_MSG);
    },
  };
  const onCellClick = useCallback((r: number, c: number, shift: boolean) => cellActions.current.click(r, c, shift), []);
  const onCellDoubleClick = useCallback((r: number, c: number) => cellActions.current.dbl(r, c), []);

  // An outside click closes an open editor without saving (grid_nav.js mousedown). A click inside the editor's form does
  // not, and a save that runs keeps the editor (cancel refuses then).
  const editOpen = edit.session !== null;
  const cancel = edit.cancel;
  useEffect(() => {
    if (!editOpen) return;
    const onDown = (event: MouseEvent) => {
      if (inEditorSurface(event.target)) return; // the form and the popup of a choice or date box are the editor
      cancel();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [editOpen, cancel]);

  // A move after a save: the editor's cell moves by its key (clamped to the table, no editor opens on the next cell).
  const moveFrom = (pos: Pos, dir: MoveDir) => {
    const next = move(
      pos,
      MOVE_KEY[dir],
      base.map((row) => row.texts.length),
    );
    if (next) grid.onCellClick(next.r, next.c, false);
  };

  // The open editor, drawn in its cell. The anchor is the cell's <td>, already drawn while its editor opens (the panel
  // placement reads it). Saving or cancelling puts the focus back on the table with the cursor on the same cell. Every
  // callback checks the epoch the editor opened in: an answer from an older address writes and moves nothing.
  let editorCursor: RowsCursor["editor"] = null;
  const session = edit.session;
  if (session && session.editor) {
    const { pos, epoch } = session;
    const editor = session.editor;
    const target = base[pos.r]?.cells[pos.c]?.edit;
    if (target) {
      const anchor = tableRef.current?.querySelector<HTMLElement>(`td[data-r="${pos.r}"][data-c="${pos.c}"]`) ?? null;
      editorCursor = {
        r: pos.r,
        c: pos.c,
        panel: isPanelEditor(editor),
        node: (
          <CellEditor
            key={`${epoch}:${pos.r}:${pos.c}`}
            target={target}
            editor={editor}
            anchor={anchor}
            initialText={session.initialText}
            buffered={session.buffered}
            onSavingChange={(on) => edit.setSaving(on, epoch)}
            onSetRange={(text) => {
              // Ctrl+Enter: the editor closes without saving and its text goes to the range (grid_nav.js setMany).
              if (epoch !== edit.currentEpoch()) return;
              edit.cancel();
              bulk.setRange(grid.range ?? box(pos, pos), text);
            }}
            onSaved={(text) => {
              if (epoch !== edit.currentEpoch()) return;
              tableRef.current?.focus({ preventScroll: true });
              edit.onSaved(target, text, epoch);
            }}
            onCancel={() => {
              tableRef.current?.focus({ preventScroll: true });
              edit.cancel();
            }}
            onMove={(dir) => {
              if (epoch === edit.currentEpoch()) moveFrom(pos, dir);
            }}
          />
        ),
      };
    }
  }

  // While an editor is open the table's keys are its: the grid does not move. A key typed while the editor loads (or in
  // the gap before it mounts) is buffered for it (grid_nav.js bufferKey); Esc from the table cancels. The session is read
  // from a ref, so a key in that gap sees the editor that is there.
  const onGridKeyDown = (e: GridKeyEvent) => {
    // Only the keys of the grid's own cells count: a key another handler took (defaultPrevented, e.g. an open list's Esc),
    // an IME key, or a key from outside the cells (a field, a popup, a header link) is not the grid's.
    if (e.defaultPrevented || isComposingKey(e) || !isGridTarget(e)) return;
    if (bulk.active()) {
      // A batch's preview is open: Enter saves, Escape discards, every other key is held (grid_nav.js previewKey). Tab and
      // the browser's shortcuts pass through (bulk.onKey).
      bulk.onKey(e);
      return;
    }
    if (edit.current()) {
      if (e.key === "Escape") {
        e.preventDefault();
        edit.cancel();
        return;
      }
      const name = bufferName(e);
      if (name !== null) {
        e.preventDefault();
        edit.buffer(name);
      }
      return;
    }
    grid.onKeyDown(e);
  };

  // The cursor cell scrolls into view as it moves (grid_nav.js scrollIntoView, nearest on both axes).
  const activeR = grid.active?.r;
  const activeC = grid.active?.c;
  useEffect(() => {
    if (activeR === undefined || activeC === undefined) return;
    const cell = tableRef.current?.querySelector<HTMLElement>(`td[data-r="${activeR}"][data-c="${activeC}"]`);
    cell?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [activeR, activeC]);

  const hasMore = rows.hasNextPage;
  const loadingMore = rows.isFetchingNextPage;
  const failed = rows.isError;
  // After a failed batch the pill is not loaded by scrolling into view; its click still asks again.
  const onMore = () => {
    if (!loadingMore) void rows.fetchNextPage();
  };
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !failed);

  // Ctrl+V (a paste event, as in Django): the clipboard's rows are laid from the cursor cell; one value on a Shift range
  // fills the range. Nothing happens while an editor or a preview is open, or when the paste lands in a field.
  const onPaste = (e: ClipboardEvent<HTMLTableElement>) => {
    if (edit.current() || bulk.active()) return;
    const table = tableRef.current;
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    if (target !== table && (target.closest("tbody td") === null || target.closest(FIELD_SELECTOR) !== null)) return;
    const origin = grid.active;
    const text = e.clipboardData?.getData("text/plain") ?? "";
    if (!origin || !text) return;
    e.preventDefault();
    bulk.paste(origin, text, grid.range);
  };

  const footer = table.footer && table.footer.length > 0 ? table.footer : null;

  return (
    <>
      {failed ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      {edit.notice ? (
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <p
            role={edit.notice.tone === "error" ? "alert" : "status"}
            data-edit-note
            className={edit.notice.tone === "error" ? "text-red-600" : "text-slate-500"}
          >
            {edit.notice.text}
          </p>
          {edit.notice.tone === "error" ? (
            <button
              type="button"
              data-edit-note-close
              onClick={edit.dismissNotice}
              className="rounded-lg border border-slate-300 bg-surface px-3 py-1 text-slate-700 hover:bg-slate-50"
            >
              Хаах
            </button>
          ) : null}
        </div>
      ) : null}
      {bulk.bar ? <BulkBar message={bulk.bar.message} actions={bulk.bar.actions} onEscape={bulk.escape} /> : null}
      {selection && state ? (
        <SelectionBar
          reportKey={selection.reportKey}
          query={query}
          total={table.count}
          urls={selection.urls}
          selection={selection.api}
          pickedCount={state.all ? table.count : state.ids.size}
          allVisiblePicked={visibleIds.length > 0 && visibleIds.every((id) => isPicked(state, id))}
          hasMore={hasMore}
          overCap={table.count > selection.maxPeople}
          maxPeople={selection.maxPeople}
        />
      ) : null}
      {marksOn ? <EditLegend kinds={editKinds} /> : null}
      <ScrollHost fit className="ptable ptable-fit">
        <table
          ref={tableRef}
          data-grid=""
          className={marksOn ? "edit-marks" : undefined}
          tabIndex={0}
          aria-label="Хүснэгт: сумаар шилжинэ"
          onKeyDown={onGridKeyDown}
          onFocus={grid.onFocus}
          onPaste={onPaste}
        >
          <thead>
            <HeaderRow heads={table.heads} check={check} select={headSelect} marks={marks} />
          </thead>
          <tbody>
            {table.count === 0 ? (
              <tr>
                <td colSpan={table.table_span} className="py-6 text-center text-slate-400">
                  Өгөгдөл олдсонгүй
                </td>
              </tr>
            ) : (
              <>
                <ReportRows
                  groups={drawn}
                  grouped={grouped}
                  tableSpan={table.table_span}
                  check={check}
                  selection={selection?.api ?? null}
                  cursor={{
                    active: grid.active,
                    range: grid.range,
                    onCellClick,
                    onCellDoubleClick,
                    editor: editorCursor,
                    marks: bulk.marks,
                    colMarks: marks,
                    busy: session && (edit.loading || edit.saving) ? session.pos : null,
                  }}
                />
                {hasMore ? (
                  <tr data-more-row>
                    <td colSpan={table.table_span} className="px-4 py-3 text-center">
                      <button
                        ref={moreRef}
                        type="button"
                        data-more-batch
                        onClick={onMore}
                        className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-surface px-4 py-1.5 text-sm text-slate-600 hover:border-violet-300 hover:text-violet-700"
                      >
                        <svg
                          aria-hidden="true"
                          className={
                            loadingMore
                              ? "htmx-indicator h-4 w-4 animate-spin htmx-request"
                              : "htmx-indicator h-4 w-4 animate-spin"
                          }
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={3}
                        >
                          <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
                        </svg>
                        Цааш харуулах
                      </button>
                    </td>
                  </tr>
                ) : null}
              </>
            )}
          </tbody>
          {footer ? (
            <tfoot>
              <tr className="border-t border-slate-300 font-semibold">
                {footerCheck ? (
                  <td className={footerCheck.css || undefined} style={inlineStyle(footerCheck.style)} />
                ) : null}
                {footer.map((cell, index) => (
                  <ReportCell key={index} cell={cell} />
                ))}
              </tr>
            </tfoot>
          ) : null}
        </table>
      </ScrollHost>
    </>
  );
}
