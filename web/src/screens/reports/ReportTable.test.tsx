// The harness is imported first: it stubs fetch before ../../api/client (and so ../../api/reports) load.
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers, urlOf } from "../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import { setCsrf } from "../../api/client";
import {
  bulkCells,
  fetchEditor,
  NO_FORM_MSG,
  saveEdit,
  type ReportEditor,
  type ReportEditResult,
  type ReportEditTarget,
} from "../../api/reportsEdit";
import type { ReportCellOut, ReportHeadCellOut, ReportTableOut } from "../../api/reports";
import { ReportTable, withSavedTexts, type ReportTableProps } from "./ReportTable";
import { useReportSelection } from "./useReportSelection";
import { NO_EDIT_MSG, targetKey } from "./grid/useCellEdit";

vi.mock("../../api/reportsEdit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/reportsEdit")>();
  return { ...actual, fetchEditor: vi.fn(), saveEdit: vi.fn(), bulkCells: vi.fn() };
});

const HEAD: ReportHeadCellOut = {
  label: "Нэр",
  href: "/reports/staff/?sort=name",
  append_href: "/reports/staff/?sort=name,-number",
  arrow: "",
  css: "",
  sticky_left: "",
};

function cell(value: string): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0, edit: null };
}

function table(overrides: Partial<ReportTableOut> = {}): ReportTableOut {
  return {
    address: "/reports/staff/",
    check_css: "",
    check_style: "",
    clear_rules_url: "",
    count: 2,
    footer: null,
    groups: [{ label: "", count: 2, rows: [[cell("Бат")], [cell("Сарнай")]] }],
    heads: [HEAD],
    next_offset: null,
    note: "",
    pin: 0,
    query: "",
    rules_text: "",
    selectable: false,
    shows_count: true,
    table_span: 1,
    ...overrides,
  } as ReportTableOut;
}

const NEXT_BATCH = (rows: string[], nextOffset: number | null) => ({
  groups: [{ label: "", count: rows.length, rows: rows.map((value) => [cell(value)]) }],
  next_offset: nextOffset,
});

let client: QueryClient;

beforeEach(() => {
  resetFetch();
  setCsrf("");
  client = newClient();
});

afterEach(() => {
  cleanup();
  resetObservers();
});

// Renders the table under a router and the query client. `rerenderWith` re-renders the same tree with new props.
function renderTable(overrides: Partial<ReportTableProps> = {}) {
  const props: ReportTableProps = {
    reportKey: "staff",
    query: "q=a",
    table: table(),
    dataUpdatedAt: 1,
    ...overrides,
  };
  const ui = (current: ReportTableProps) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReportTable {...current} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(ui(props));
  return {
    ...result,
    rerenderWith: (next: Partial<ReportTableProps>) => result.rerender(ui({ ...props, ...next })),
  };
}

describe("ReportTable", () => {
  it("empty_report_row_spans_the_table", () => {
    const { getByText, queryByRole } = renderTable({
      table: table({ count: 0, groups: [{ label: "", count: 0, rows: [] }], table_span: 3, next_offset: null }),
    });

    const empty = getByText("Өгөгдөл олдсонгүй").closest("td")!;
    expect(empty.getAttribute("colspan")).toBe("3");
    expect(empty.className).toBe("py-6 text-center text-slate-400");
    expect(queryByRole("button", { name: "Цааш харуулах" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("footer_cells_and_none_without_footer", () => {
    const footerCells: ReportCellOut[] = [
      cell("Нийт"),
      { value: "2500000.00", text: "2500000.00", money: true, href: "", css: "text-right", style: "", person: 0, edit: null },
    ];

    const withFooter = renderTable({ table: table({ footer: footerCells }) });
    const tfoot = withFooter.container.querySelector("tfoot")!;
    expect(tfoot.querySelector("tr")!.className).toBe("border-t border-slate-300 font-semibold");
    const cells = Array.from(tfoot.querySelectorAll("td"));
    expect(cells.map((td) => td.textContent)).toEqual(["Нийт", "2,500,000₮"]);
    expect(cells[1].className).toBe("text-right");
    withFooter.unmount();

    const nullFooter = renderTable({ table: table({ footer: null }) });
    expect(nullFooter.container.querySelector("tfoot")).toBeNull();
    nullFooter.unmount();

    const emptyFooter = renderTable({ table: table({ footer: [] }) });
    expect(emptyFooter.container.querySelector("tfoot")).toBeNull();
  });

  it("pill_loads_next_batch_with_offset_and_hides_at_end", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, NEXT_BATCH(["Номин", "Дорж"], null)));
    const { getByRole, getByText, queryByText, container } = renderTable({
      table: table({ count: 4, next_offset: 2 }),
    });

    expect(getByText("Бат")).toBeTruthy();
    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));

    await waitFor(() => expect(getByText("Номин")).toBeTruthy());
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/rows");
    expect(urlOf(0).searchParams.get("q")).toBe("a");
    expect(urlOf(0).searchParams.get("offset")).toBe("2");
    expect(getByText("Дорж")).toBeTruthy();
    expect(container.querySelectorAll("tbody > tr")).toHaveLength(4);
    // The last batch has no next offset: the pill is gone.
    expect(queryByText("Цааш харуулах")).toBeNull();
  });

  it("grouped_table_has_no_pill", () => {
    const { queryByText, getByText } = renderTable({
      table: table({
        count: 3,
        groups: [
          { label: "Санхүү", count: 2, rows: [[cell("Бат")], [cell("Сарнай")]] },
          { label: "Бусад", count: 1, rows: [[cell("Номин")]] },
        ],
        next_offset: null,
        table_span: 1,
      }),
    });

    expect(getByText("Санхүү · 2")).toBeTruthy();
    expect(getByText("Бусад · 1")).toBeTruthy();
    expect(queryByText("Цааш харуулах")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("failed_next_batch_shows_alert", async () => {
    // A 403 is not retried by the query, so the failure shows at once.
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));
    const { getByRole, getByText } = renderTable({ table: table({ count: 4, next_offset: 2 }) });

    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));

    await waitFor(() => expect(getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй."));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // The rows already on screen stay, and the pill is still there to ask again.
    expect(getByText("Бат")).toBeTruthy();
    expect(getByRole("button", { name: "Цааш харуулах" })).toBeTruthy();
  });

  it("rows_reseed_when_dataUpdatedAt_changes", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, NEXT_BATCH(["Номин"], null)));
    const { getByRole, getByText, queryByText, rerenderWith } = renderTable({
      table: table({ count: 3, next_offset: 2 }),
    });

    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));
    await waitFor(() => expect(getByText("Номин")).toBeTruthy());

    // The page refetched: the batches start again from the new first batch, and the old batches are gone.
    const refreshed = table({
      count: 1,
      groups: [{ label: "", count: 1, rows: [[cell("Шинэ")]] }],
      next_offset: null,
    });
    rerenderWith({ table: refreshed, dataUpdatedAt: 2 });

    expect(getByText("Шинэ")).toBeTruthy();
    expect(queryByText("Номин")).toBeNull();
    expect(queryByText("Бат")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("selectable_table_draws_a_blank_placeholder_column_in_head_rows_and_footer", () => {
    const second: ReportHeadCellOut = { ...HEAD, label: "Тушаал", href: "/reports/staff/?sort=order" };
    const footer: ReportCellOut[] = [cell("Нийт"), cell("5")];
    const { container } = renderTable({
      table: table({
        heads: [HEAD, second],
        selectable: true,
        table_span: 3,
        check_css: "sticky z-10 bg-surface",
        check_style: "left: 0rem",
        pin: 1,
        footer,
        groups: [{ label: "", count: 2, rows: [[cell("Бат"), cell("1")], [cell("Сарнай"), cell("2")]] }],
      }),
    });

    // Header: the placeholder first, then the two heads. It has no control and no text.
    const headCells = Array.from(container.querySelectorAll("thead tr > *"));
    expect(headCells).toHaveLength(3);
    expect(headCells[0].tagName).toBe("TH");
    expect(headCells[0].textContent).toBe("");
    expect(headCells[0].querySelector("input")).toBeNull();
    expect((headCells[0] as HTMLElement).className).toBe("sticky z-10 bg-surface");
    expect((headCells[0] as HTMLElement).style.left).toBe("0rem");

    // Each body row: placeholder plus its two cells.
    const bodyRows = Array.from(container.querySelectorAll("tbody > tr"));
    expect(bodyRows).toHaveLength(2);
    for (const row of bodyRows) {
      const cells = Array.from(row.querySelectorAll("td"));
      expect(cells).toHaveLength(3);
      expect(cells[0].textContent).toBe("");
      expect(cells[0].querySelector("input")).toBeNull();
    }

    // Footer: placeholder (classed, since the first column is pinned) plus the two footer cells.
    const footerCells = Array.from(container.querySelectorAll("tfoot td"));
    expect(footerCells).toHaveLength(3);
    expect(footerCells[0].className).toBe("sticky z-10 bg-surface");
    expect(footerCells[1].textContent).toBe("Нийт");

    // No span is drawn in this state (no empty row, group heading or pill).
    const spans = Array.from(container.querySelectorAll("[colspan]")).map((el) => el.getAttribute("colspan"));
    expect(spans).toEqual([]);
  });

  it("selectable_table_spans_match_drawn_cells_for_empty_group_and_pill", () => {
    // Each render in this test has its own seed version (dataUpdatedAt), so none reads another render's cached rows.
    const empty = renderTable({
      dataUpdatedAt: 11,
      table: table({ count: 0, groups: [{ label: "", count: 0, rows: [] }], selectable: true, table_span: 3 }),
    });
    expect(empty.container.querySelector("tbody td")!.getAttribute("colspan")).toBe("3");
    expect(empty.container.querySelectorAll("tbody td")).toHaveLength(1);
    empty.unmount();

    const grouped = renderTable({
      dataUpdatedAt: 12,
      table: table({
        selectable: true,
        table_span: 3,
        count: 1,
        groups: [{ label: "Санхүү", count: 1, rows: [[cell("Бат")]] }],
      }),
    });
    const heading = grouped.getByText("Санхүү · 1").closest("td")!;
    expect(heading.getAttribute("colspan")).toBe("3");
    // The heading's row has the heading cell only, which spans the table.
    expect(grouped.container.querySelectorAll("tbody tr")[0].querySelectorAll("td")).toHaveLength(1);
    grouped.unmount();

    const pill = renderTable({
      dataUpdatedAt: 13,
      table: table({ selectable: true, table_span: 3, count: 4, next_offset: 2 }),
    });
    const pillCell = pill.getByRole("button", { name: "Цааш харуулах" }).closest("td")!;
    expect(pillCell.getAttribute("colspan")).toBe("3");
  });

  it("non_selectable_table_draws_heads_only", () => {
    const second: ReportHeadCellOut = { ...HEAD, label: "Тушаал", href: "/reports/staff/?sort=order" };
    const { container } = renderTable({
      table: table({
        heads: [HEAD, second],
        selectable: false,
        table_span: 2,
        footer: [cell("Нийт"), cell("5")],
        groups: [{ label: "", count: 1, rows: [[cell("Бат"), cell("1")]] }],
      }),
    });

    expect(container.querySelectorAll("thead th")).toHaveLength(2);
    expect(container.querySelectorAll("tbody tr td")).toHaveLength(2);
    expect(container.querySelectorAll("tfoot td")).toHaveLength(2);
  });
});

// Selection (step 5d): the checkbox column, the header box, the selection bar and the rows on screen, wired through the
// real hook as the page wires them.

function personCell(value: string, person: number): ReportCellOut {
  return { value, text: value, money: false, href: `/employees/${person}/`, css: "", style: "", person, edit: null };
}

const TWO_PEOPLE: ReportCellOut[][] = [[personCell("Бат", 7)], [personCell("Сарнай", 8)]];

function peopleTable(overrides: Partial<ReportTableOut> = {}): ReportTableOut {
  return table({
    selectable: true,
    count: 2,
    groups: [{ label: "", count: 2, rows: TWO_PEOPLE }],
    ...overrides,
  });
}

type SelectingProps = Omit<ReportTableProps, "selection"> & { maxPeople?: number };

// The page's wiring: the hook's result goes to the table with the report's selection URLs.
function SelectingTable({ maxPeople = 500, ...props }: SelectingProps) {
  const api = useReportSelection(props.reportKey);
  return (
    <ReportTable
      {...props}
      selection={{ api, urls: { excel: "/api/v1/reports/staff/selected/excel" }, maxPeople, reportKey: props.reportKey }}
    />
  );
}

function renderSelecting(overrides: Partial<SelectingProps> = {}) {
  const props: SelectingProps = {
    reportKey: "staff",
    query: "q=a",
    table: peopleTable(),
    dataUpdatedAt: 1,
    ...overrides,
  };
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SelectingTable {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function rowBox(container: HTMLElement, person: number): HTMLInputElement {
  return container.querySelector<HTMLInputElement>(`tbody tr[data-person="${person}"] input[data-select-row]`)!;
}

function headerBox(container: HTMLElement): HTMLInputElement {
  return container.querySelector<HTMLInputElement>("thead input[data-select-all]")!;
}

describe("ReportTable selection", () => {
  it("without the selection prop the selection column stays blank", () => {
    const { container } = renderTable({ table: peopleTable() });
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelector("tbody tr[data-person]")).toBeNull();
    expect(container.querySelector("#selection-bar")).toBeNull();
  });

  it("a row checkbox picks its person, marks the row and leaves the header box indeterminate", () => {
    const { container } = renderSelecting();

    fireEvent.click(rowBox(container, 7));

    const row = container.querySelector("tbody tr[data-person='7']")!;
    expect(row.classList.contains("is-picked")).toBe(true);
    expect(rowBox(container, 7).checked).toBe(true);
    expect(rowBox(container, 8).checked).toBe(false);
    expect(headerBox(container).checked).toBe(false);
    expect(headerBox(container).indeterminate).toBe(true);
    expect(container.querySelector("#selection-bar [data-count]")!.textContent).toBe("1");
  });

  it("the header box picks every row on screen, then clears them", () => {
    const { container } = renderSelecting();

    fireEvent.click(headerBox(container));
    expect(container.querySelectorAll("tbody tr.is-picked")).toHaveLength(2);
    expect(headerBox(container).checked).toBe(true);
    expect(headerBox(container).indeterminate).toBe(false);
    expect(container.querySelector("#selection-bar [data-count]")!.textContent).toBe("2");

    fireEvent.click(headerBox(container));
    expect(container.querySelectorAll("tbody tr.is-picked")).toHaveLength(0);
    expect(headerBox(container).checked).toBe(false);
    expect(container.querySelector("#selection-bar")).toBeNull();
  });

  it("the selection bar and the body mark appear only while selection is on", () => {
    const { container, getByRole } = renderSelecting();
    expect(container.querySelector("#selection-bar")).toBeNull();
    expect(document.body.dataset.selecting).toBeUndefined();

    fireEvent.click(rowBox(container, 8));
    expect(container.querySelector("#selection-bar")).not.toBeNull();
    expect(document.body.dataset.selecting).toBe("1");

    fireEvent.click(getByRole("button", { name: "Болих" }));
    expect(container.querySelector("#selection-bar")).toBeNull();
    expect(container.querySelectorAll("tbody tr.is-picked")).toHaveLength(0);
    expect(document.body.dataset.selecting).toBeUndefined();
  });

  it("selection on: a row click toggles the person instead of opening the row", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { container } = renderSelecting();
    // The mode is on once a person is picked; the next click on another row toggles that person.
    fireEvent.click(rowBox(container, 7));

    fireEvent.click(container.querySelector("tbody tr[data-person='8'] td:nth-child(2)")!);
    expect(container.querySelector("tbody tr[data-person='8']")!.classList.contains("is-picked")).toBe(true);
    expect(container.querySelector("tbody tr[data-person='7']")!.classList.contains("is-picked")).toBe(true);
    expect(open).not.toHaveBeenCalled();
  });

  it("selection off: a ctrl-click on a row of the grid table opens nothing (grid guard, as report_select.js)", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { container } = renderSelecting();

    fireEvent.click(container.querySelector("tbody tr[data-person='7'] td:nth-child(2)")!, { ctrlKey: true });
    expect(open).not.toHaveBeenCalled();
  });

  it("the next batch keeps the ticks of the people already picked", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { groups: [{ label: "", count: 1, rows: [[personCell("Номин", 9)]] }], next_offset: null }),
    );
    const { container, getByRole, getByText } = renderSelecting({
      table: peopleTable({ count: 3, next_offset: 2 }),
    });

    fireEvent.click(rowBox(container, 7));
    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));

    await waitFor(() => expect(getByText("Номин")).toBeTruthy());
    expect(container.querySelector("tbody tr[data-person='7']")!.classList.contains("is-picked")).toBe(true);
    expect(container.querySelector("tbody tr[data-person='9']")!.classList.contains("is-picked")).toBe(false);
    expect(container.querySelector("#selection-bar [data-count]")!.textContent).toBe("1");
  });

  it("the all-matching offer shows when every row on screen is picked and more batches follow", () => {
    const { container, getByRole } = renderSelecting({ table: peopleTable({ count: 3, next_offset: 2 }) });

    fireEvent.click(headerBox(container));
    expect(getByRole("button", { name: "Бүх 3 мөрийг сонгох" })).toBeTruthy();
  });

  it("over the cap the note replaces the all-matching offer", () => {
    const { container, queryByRole } = renderSelecting({
      table: peopleTable({ count: 3, next_offset: 2 }),
      maxPeople: 2,
    });

    fireEvent.click(headerBox(container));
    expect(queryByRole("button", { name: "Бүх 3 мөрийг сонгох" })).toBeNull();
    expect(container.querySelector("[data-over-cap]")).not.toBeNull();
  });
});

describe("ReportTable selection unmount", () => {
  it("body[data-selecting] is removed when the table unmounts while selecting", () => {
    const { container, unmount } = renderSelecting();

    fireEvent.click(rowBox(container, 7));
    expect(document.body.dataset.selecting).toBe("1");

    unmount();
    expect(document.body.dataset.selecting).toBeUndefined();
  });

  it("a click moves the grid cursor, a key moves it on, and each body cell carries its grid row and column", () => {
    const { getByText, container } = renderTable();
    const table = container.querySelector("table[data-grid]")!;
    const first = getByText("Бат").closest("td")!;
    const second = getByText("Сарнай").closest("td")!;

    fireEvent.click(first);
    expect(first.classList.contains("is-cell-active")).toBe(true);
    expect(first.dataset.r).toBe("0");
    expect(first.dataset.c).toBe("0");

    fireEvent.keyDown(table, { key: "ArrowDown" });
    expect(second.classList.contains("is-cell-active")).toBe(true);
    expect(first.classList.contains("is-cell-active")).toBe(false);
    expect(second.dataset.r).toBe("1");
  });
});

// The grid keys on the real table: the cursor's marks, the scroll, the Tab leave, Enter, Space and the selection click.
function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

describe("ReportTable grid keys", () => {
  afterEach(() => {
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("the cursor cell is aria-current and scrolls into view as it moves", () => {
    // jsdom has no scrollIntoView: the test provides one and reads which element it was called on.
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const { container, getByText } = renderTable();
    const first = getByText("Бат").closest("td")!;
    const second = getByText("Сарнай").closest("td")!;

    fireEvent.click(first);
    expect(first.getAttribute("aria-current")).toBe("true");
    expect(scroll.mock.contexts.at(-1)).toBe(first);
    expect(scroll).toHaveBeenLastCalledWith({ block: "nearest", inline: "nearest" });

    fireEvent.keyDown(container.querySelector("table[data-grid]")!, { key: "ArrowDown" });
    expect(second.getAttribute("aria-current")).toBe("true");
    expect(first.getAttribute("aria-current")).toBeNull();
    expect(scroll.mock.contexts.at(-1)).toBe(second);
  });

  it("a forward Tab on the last cell focuses the element after the table; Shift+Tab on the first cell is left to the browser", () => {
    const { container, getByText } = renderTable();
    // Rendered after the table, so it is the next focusable element in the document.
    const after = document.createElement("button");
    document.body.append(after);
    try {
      const grid = container.querySelector("table[data-grid]")!;
      fireEvent.click(getByText("Сарнай").closest("td")!); // the last row, and the only column
      expect(fireEvent.keyDown(grid, { key: "Tab" })).toBe(false); // prevented: focus went out of the table
      expect(document.activeElement).toBe(after);

      fireEvent.click(getByText("Бат").closest("td")!); // a click puts the focus back in the grid
      expect(document.activeElement).toBe(grid);
      expect(fireEvent.keyDown(grid, { key: "Tab", shiftKey: true })).toBe(true); // first cell: not prevented
    } finally {
      after.remove();
    }
  });

  it("Enter opens the cursor row's record in-app", () => {
    const tbl = table({ count: 1, groups: [{ label: "", count: 1, rows: [[personCell("Бат", 7)]] }] });
    const { container, getByText, getByTestId } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/reports/staff/"]}>
          <ReportTable reportKey="staff" query="q=a" table={tbl} dataUpdatedAt={1} />
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(container.querySelector("table[data-grid]")!, { key: "Enter" });
    expect(getByTestId("where").textContent).toBe("/employees/7/");
  });

  it("Space ticks the row under the cursor in selection mode", () => {
    const { container } = renderSelecting();
    fireEvent.click(container.querySelector("tbody tr[data-person='8'] td:nth-child(2)")!);
    fireEvent.keyDown(container.querySelector("table[data-grid]")!, { key: " " });
    expect(container.querySelector("tbody tr[data-person='8']")!.classList.contains("is-picked")).toBe(true);
    expect(container.querySelector("tbody tr[data-person='7']")!.classList.contains("is-picked")).toBe(false);
  });

  it("a click on a person's row in selection mode picks the person, moves the cursor and focuses the table", () => {
    const { container } = renderSelecting();
    fireEvent.click(rowBox(container, 7)); // the mode is on
    const name = container.querySelector("tbody tr[data-person='8'] td:nth-child(2)")!;
    fireEvent.click(name);
    expect(container.querySelector("tbody tr[data-person='8']")!.classList.contains("is-picked")).toBe(true);
    expect(name.getAttribute("aria-current")).toBe("true");
    expect(document.activeElement).toBe(container.querySelector("table[data-grid]"));
  });
});

// Cell editing on the real table (Task 10): F2, Enter, a printable key and a double click open the editor of an editable
// cell; a saved text replaces the cell with no refetch and moves the cursor; Esc returns focus to the cursor cell.
const EDIT: ReportEditTarget = { route: "cell", person: 7, field: "job_title", kind: "", key: 0, record: 0, salary: false };
const mockEditor = vi.mocked(fetchEditor);
const mockSave = vi.mocked(saveEdit);

function editorOf(over: Partial<ReportEditor> = {}): ReportEditor {
  return {
    blocked: "",
    choices: [],
    error: "",
    hidden: {},
    kind: "text",
    label: "Албан тушаал",
    loaded: "tok1",
    maxlength: 50,
    name: "job_title",
    note: "",
    old: "Бат",
    reason: false,
    reason_text: "",
    required: false,
    value: "Бат",
    ...over,
  };
}

function editableCell(value: string): ReportCellOut {
  return { ...cell(value), edit: EDIT };
}

// Row 0 is editable, row 1 is not.
function editTable(): ReportTableOut {
  return table({
    count: 2,
    groups: [{ label: "", count: 2, rows: [[editableCell("Бат")], [cell("Сарнай")]] }],
  });
}

const gridOf = (container: HTMLElement) => container.querySelector("table[data-grid]") as HTMLTableElement;

describe("ReportTable cell editing", () => {
  beforeEach(() => {
    mockEditor.mockReset();
    mockSave.mockReset();
  });

  it("F2 on an editable cell opens its editor with the cell's value", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });

    expect(mockEditor).toHaveBeenCalledWith(EDIT);
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    expect(container.querySelector<HTMLInputElement>("input")!.value).toBe("Бат");
    expect(document.activeElement).toBe(container.querySelector("input"));
  });

  it("Enter on an editable cell opens the editor instead of the row link", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    expect(fireEvent.keyDown(gridOf(container), { key: "Enter" })).toBe(false);
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
  });

  it("a printable key opens the editor with that key typed", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "x" });

    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    expect(container.querySelector<HTMLInputElement>("input")!.value).toBe("x");
  });

  it("keys typed while the editor loads are not lost", async () => {
    let resolve!: (value: ReportEditor) => void;
    mockEditor.mockReturnValueOnce(new Promise<ReportEditor>((res) => (resolve = res)));
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "x" });
    fireEvent.keyDown(gridOf(container), { key: "y" });
    expect(container.querySelector("input")).toBeNull();

    await act(async () => resolve(editorOf()));
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    expect(container.querySelector<HTMLInputElement>("input")!.value).toBe("xy");
  });

  it("a double click on an editable cell opens its editor; on a group heading it does nothing", async () => {
    mockEditor.mockResolvedValue(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.doubleClick(getByText("Бат").closest("td")!);
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    expect(mockEditor).toHaveBeenCalledTimes(1);

    const grouped = table({
      count: 1,
      groups: [{ label: "Алба", count: 1, rows: [[editableCell("Бат")]] }],
    });
    const again = renderTable({ table: grouped, query: "q=other" }); // its own query: the rows cache is per address
    fireEvent.doubleClick(again.getByText("Алба · 1").closest("td")!);
    expect(mockEditor).toHaveBeenCalledTimes(1);
    expect(again.container.querySelector("input")).toBeNull();
  });

  it("a saved text replaces the cell text with no refetch, and the cursor moves down", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    mockSave.mockResolvedValueOnce({ ok: true, text: "Ахлах", error: "", editor: null } as ReportEditResult);
    const { container, getByText } = renderTable({ table: editTable() });
    const first = getByText("Бат").closest("td")!;
    const second = getByText("Сарнай").closest("td")!;
    fireEvent.click(first);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());

    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });
    await waitFor(() => expect(first.textContent).toBe("Ахлах"));
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockEditor).toHaveBeenCalledTimes(1);
    expect(container.querySelector("input")).toBeNull();
    expect(second.getAttribute("aria-current")).toBe("true");
    // The next cell does not open by itself.
    expect(mockEditor).toHaveBeenCalledTimes(1);
  });

  it("F2 on a cell that cannot be edited opens nothing and shows the note", () => {
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Сарнай").closest("td")!);
    expect(fireEvent.keyDown(gridOf(container), { key: "F2" })).toBe(true);
    expect(mockEditor).not.toHaveBeenCalled();
    expect(container.querySelector("input")).toBeNull();
    expect(getByText(NO_EDIT_MSG)).toBeTruthy();
  });

  it("a table with no editable cell shows no note on F2", () => {
    const { container, getByText, queryByText } = renderTable({ table: table() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    expect(queryByText(NO_EDIT_MSG)).toBeNull();
  });

  it("Enter on a cell that cannot be edited opens the row's record", () => {
    const tbl = table({ count: 1, groups: [{ label: "", count: 1, rows: [[personCell("Сарнай", 9)]] }] });
    const { container, getByText, getByTestId } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/reports/staff/"]}>
          <ReportTable reportKey="staff" query="q=a" table={tbl} dataUpdatedAt={1} />
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(getByText("Сарнай").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "Enter" });
    expect(mockEditor).not.toHaveBeenCalled();
    expect(getByTestId("where").textContent).toBe("/employees/9/");
  });

  it("Esc closes the editor and returns focus to the table, the cursor still on the same cell", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    const first = getByText("Бат").closest("td")!;
    fireEvent.click(first);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());

    fireEvent.keyDown(container.querySelector("input")!, { key: "Escape" });
    expect(container.querySelector("input")).toBeNull();
    expect(document.activeElement).toBe(gridOf(container));
    expect(first.getAttribute("aria-current")).toBe("true");
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("an editor that does not open shows the open-failure message and no editor", async () => {
    mockEditor.mockRejectedValueOnce(new Error("HTTP 500"));
    const { container, getByText, findByRole } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });

    const alert = await findByRole("alert");
    expect(alert.textContent).toBe(NO_FORM_MSG);
    expect(container.querySelector("input")).toBeNull();
  });
});

// Fix round 1: saved texts follow the cell's identity and the address epoch; saves and clicks respect the busy guard.
const savedOk = (text: string): ReportEditResult => ({ ok: true, text, error: "", editor: null }) as ReportEditResult;

function targetOf(person: number): ReportEditTarget {
  return { ...EDIT, person };
}

function personEditable(value: string, person: number): ReportCellOut {
  return { ...cell(value), person, edit: targetOf(person) };
}

const textAt = (container: HTMLElement, r: number, c: number) =>
  container.querySelector(`td[data-r="${r}"][data-c="${c}"]`)?.textContent;

describe("ReportTable cell editing, fix round 1", () => {
  beforeEach(() => {
    mockEditor.mockReset();
    mockSave.mockReset();
  });

  it("an address round trip (A to B and back to A) shows no saved text from the first visit", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    mockSave.mockResolvedValueOnce(savedOk("Ахлах"));
    const { container, getByText, rerenderWith } = renderTable({ table: editTable(), query: "q=a" });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });
    await waitFor(() => expect(textAt(container, 0, 0)).toBe("Ахлах"));

    rerenderWith({ query: "q=b" });
    rerenderWith({ query: "q=a" });
    expect(textAt(container, 0, 0)).toBe("Бат");
  });

  it("a save that finishes after the address changed writes nothing", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    let resolve!: (r: ReportEditResult) => void;
    mockSave.mockReturnValueOnce(new Promise<ReportEditResult>((res) => (resolve = res)));
    const { container, getByText, rerenderWith } = renderTable({ table: editTable(), query: "q=a" });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });

    rerenderWith({ query: "q=b" });
    await act(async () => resolve(savedOk("Поздно")));
    rerenderWith({ query: "q=a" });
    expect(textAt(container, 0, 0)).toBe("Бат");
    expect(container.querySelector("input")).toBeNull();
  });

  it("a refetch that reorders the rows shows each person's own text on their row", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    mockSave.mockResolvedValueOnce(savedOk("Ахлах"));
    const people = (order: [string, number][]) =>
      table({ count: 2, groups: [{ label: "", count: 2, rows: order.map(([v, p]) => [personEditable(v, p)]) }] });
    const { container, getByText, rerenderWith } = renderTable({ table: people([["Бат", 7], ["Сарнай", 8]]) });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });
    await waitFor(() => expect(textAt(container, 0, 0)).toBe("Ахлах"));

    // The refetch brings the rows in another order: the saved text does not follow a position.
    rerenderWith({ dataUpdatedAt: 2, table: people([["Сарнай", 8], ["Бат", 7]]) });
    expect(textAt(container, 0, 0)).toBe("Сарнай");
    expect(textAt(container, 1, 0)).toBe("Бат");
  });

  it("a click on another cell during a save does nothing: the cursor and the editor stay", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    let resolve!: (r: ReportEditResult) => void;
    mockSave.mockReturnValueOnce(new Promise<ReportEditResult>((res) => (resolve = res)));
    const { container, getByText } = renderTable({ table: editTable() });
    const first = getByText("Бат").closest("td")!;
    const second = getByText("Сарнай").closest("td")!;
    fireEvent.click(first);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });

    fireEvent.mouseDown(second);
    fireEvent.click(second);
    expect(first.getAttribute("aria-current")).toBe("true");
    expect(second.getAttribute("aria-current")).toBeNull();
    expect(container.querySelector("input")).not.toBeNull();

    await act(async () => resolve(savedOk("Ахлах")));
    await waitFor(() => expect(first.textContent).toBe("Ахлах"));
  });

  it("an outside mousedown cancels an open editor without saving", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());

    fireEvent.mouseDown(document.body);
    expect(container.querySelector("input")).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("a mousedown inside the editor's form keeps the editor open", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());

    fireEvent.mouseDown(container.querySelector("input")!);
    expect(container.querySelector("input")).not.toBeNull();
  });

  it("Esc with the focus on the table cancels an open editor", async () => {
    mockEditor.mockResolvedValueOnce(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    const first = getByText("Бат").closest("td")!;
    fireEvent.click(first);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());

    fireEvent.keyDown(gridOf(container), { key: "Escape" });
    expect(container.querySelector("input")).toBeNull();
    expect(first.getAttribute("aria-current")).toBe("true");
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("the open-failure message can be dismissed with «Хаах»", async () => {
    mockEditor.mockRejectedValueOnce(new Error("HTTP 500"));
    const { container, getByText, findByRole, getByRole, queryByRole } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await findByRole("alert");

    fireEvent.click(getByRole("button", { name: "Хаах" }));
    expect(queryByRole("alert")).toBeNull();
  });
});

// Bulk edit on the grid (UI_RULES §4 «Bulk edit on report tables»): a paste from the cursor cell and Esc on the table.
describe("ReportTable bulk edit", () => {
  const mockBulk = vi.mocked(bulkCells);

  beforeEach(() => {
    mockBulk.mockReset();
    mockBulk.mockImplementation(async (cells) => ({
      saved: 0,
      cells: cells.map((c) => ({ person: c.person, field: c.field, ok: true, text: c.text, error: "" })),
    }));
  });

  // Row 0 has two editable cells of two people; row 1 is one editable cell.
  function bulkTable(): ReportTableOut {
    const target = (person: number, field: string): ReportEditTarget => ({
      route: "cell",
      person,
      field,
      kind: "",
      key: 0,
      record: 0,
      salary: false,
    });
    const edit = (text: string, t: ReportEditTarget): ReportCellOut => ({ ...cell(text), edit: t });
    return table({
      count: 2,
      groups: [
        {
          label: "",
          count: 2,
          rows: [
            [edit("Бат", target(1, "job_title")), edit("Сарнай", target(1, "job_title_2"))],
            [edit("Анар", target(2, "job_title"))],
          ],
        },
      ],
    });
  }

  it("a paste on the table with the cursor on an editable cell makes one dry run for its cells", async () => {
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.paste(gridOf(container), { clipboardData: { getData: () => "x	y" } });

    await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
    expect(mockBulk.mock.calls[0][1]).toBe(false);
    expect(mockBulk.mock.calls[0][0].map((c) => c.text)).toEqual(["x", "y"]);
    await waitFor(() => expect(container.querySelector("[data-bulk-bar]")?.textContent).toContain("2 нүд өөрчлөгдөнө"));
    expect(container.querySelectorAll("td.is-cell-pending")).toHaveLength(2);
  });

  it("Esc on the table discards the preview: no save, no marks", async () => {
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.paste(gridOf(container), { clipboardData: { getData: () => "x" } });
    await waitFor(() => expect(container.querySelector("[data-bulk-bar]")).not.toBeNull());

    fireEvent.keyDown(gridOf(container), { key: "Escape" });

    expect(container.querySelector("[data-bulk-bar]")).toBeNull();
    expect(container.querySelectorAll("td.is-cell-pending")).toHaveLength(0);
    expect(mockBulk).toHaveBeenCalledTimes(1);
  });

  it("Delete on the cursor cell sends a clear for the cell as a dry run", async () => {
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Анар").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "Delete" });

    await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
    expect(mockBulk.mock.calls[0][0]).toEqual([{ person: 2, field: "job_title", text: "", old: "Анар" }]);
    expect(mockBulk.mock.calls[0][1]).toBe(false);
  });

  it("a double click during a preview opens no editor", async () => {
    mockEditor.mockReset();
    mockEditor.mockResolvedValue(editorOf());
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.paste(gridOf(container), { clipboardData: { getData: () => "x" } });
    await waitFor(() => expect(container.querySelector("[data-bulk-bar]")).not.toBeNull());

    fireEvent.doubleClick(getByText("Анар").closest("td")!);

    expect(mockEditor).not.toHaveBeenCalled();
    expect(container.querySelector("input")).toBeNull();
  });

  it("Ctrl+Enter in an open editor sets its text on the whole Shift range as one dry run", async () => {
    mockEditor.mockReset();
    mockSave.mockReset();
    mockEditor.mockResolvedValue(editorOf());
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    const input = container.querySelector<HTMLInputElement>("input")!;
    fireEvent.change(input, { target: { value: "new" } });

    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });

    await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
    expect(mockBulk.mock.calls[0][0].map((c) => [c.person, c.field, c.text])).toEqual([
      [1, "job_title", "new"],
      [1, "job_title_2", "new"],
    ]);
    expect(mockBulk.mock.calls[0][1]).toBe(false);
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("Ctrl+D fills the Shift range down from its top row through the keyboard", async () => {
    mockBulk.mockClear();
    const { container, getByText } = renderTable({ table: bulkTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(gridOf(container), { key: "d", ctrlKey: true });

    await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
    expect(mockBulk.mock.calls[0][0]).toEqual([{ person: 2, field: "job_title", text: "Бат", old: "Анар" }]);
    expect(mockBulk.mock.calls[0][1]).toBe(false);
  });
});

// Fix round (step 5f review): popups of the choice and date boxes, keys and clicks from them, IME keys, the bulk bar's Tab,
// and the saved-text identity of the rows.
function choiceEditor(count: number): ReportEditor {
  const choices = Array.from({ length: count }, (_, i) => ({ value: `v${i}`, label: `Сонголт ${i}` }));
  return editorOf({ kind: "choice", name: "dept", label: "Хэлтэс", value: "v0", old: "Сонголт 0", choices });
}

async function openChoiceEditor(container: HTMLElement, getByText: (t: string) => HTMLElement) {
  fireEvent.click(getByText("Бат").closest("td")!);
  fireEvent.keyDown(gridOf(container), { key: "F2" });
  await waitFor(() => expect(container.querySelector("input[role='combobox'], select")).not.toBeNull());
}

describe("ReportTable popups of the editor", () => {
  beforeEach(() => {
    mockEditor.mockReset();
    mockSave.mockReset();
  });

  it("a mouse pick in a choice list with a search box keeps the editor, and Enter saves the picked value once", async () => {
    mockEditor.mockResolvedValueOnce(choiceEditor(9));
    mockSave.mockResolvedValueOnce(savedOk("Сонголт 3"));
    const { container, getByText } = renderTable({ table: editTable() });
    await openChoiceEditor(container, getByText);
    const combo = container.querySelector<HTMLInputElement>("input[role='combobox']")!;

    fireEvent.click(combo); // opens the list
    const option = document.querySelector<HTMLElement>(".sel-popup [data-index='3']")!;
    fireEvent.mouseDown(option);
    fireEvent.click(option);

    expect(container.querySelector("input[role='combobox']")).not.toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
    fireEvent.keyDown(combo, { key: "Enter" });
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "v3" });
  });

  it("a mouse pick in a short choice list (a click list) keeps the editor, and Enter saves the picked value", async () => {
    mockEditor.mockResolvedValueOnce(choiceEditor(3));
    mockSave.mockResolvedValueOnce(savedOk("Сонголт 2"));
    const { container, getByText } = renderTable({ table: editTable() });
    await openChoiceEditor(container, getByText);
    const select = container.querySelector<HTMLSelectElement>("select")!;

    fireEvent.mouseDown(select); // opens the list
    const option = document.querySelector<HTMLElement>(".sel-popup [data-index='2']")!;
    fireEvent.mouseDown(option);
    fireEvent.click(option);

    expect(container.querySelector("select")).not.toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
    fireEvent.keyDown(container.querySelector("select")!, { key: "Enter" });
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "v2" });
  });

  it("a mouse pick in a date calendar keeps the editor, and Enter saves the picked day", async () => {
    mockEditor.mockResolvedValueOnce(
      editorOf({ kind: "date", name: "hire_date", label: "Огноо", value: "2026-11-01", old: "2026-11-01" }),
    );
    mockSave.mockResolvedValueOnce(savedOk("2026-11-15"));
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input[name='hire_date']")).not.toBeNull());
    const input = container.querySelector<HTMLInputElement>("input[name='hire_date']")!;

    fireEvent.click(input); // opens the calendar
    const day = Array.from(document.querySelectorAll<HTMLElement>(".dp-popup .dp-day")).find(
      (b) => b.textContent === "15" && !b.classList.contains("dp-other"),
    )!;
    fireEvent.mouseDown(day);
    fireEvent.click(day);

    expect(container.querySelector("input[name='hire_date']")).not.toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "2026-11-15" });
  });

  it("Escape in an open list closes only the list; a second Escape cancels the editor", async () => {
    mockEditor.mockResolvedValueOnce(choiceEditor(3));
    const { container, getByText } = renderTable({ table: editTable() });
    await openChoiceEditor(container, getByText);
    const select = container.querySelector<HTMLSelectElement>("select")!;
    fireEvent.mouseDown(select); // opens the list; focus moves to the list
    const popup = document.querySelector<HTMLElement>(".sel-popup")!;
    expect(popup).not.toBeNull();

    fireEvent.keyDown(popup, { key: "Escape" });
    await waitFor(() => expect(document.querySelector(".sel-popup:not([data-leaving])")).toBeNull());
    expect(container.querySelector("select")).not.toBeNull();

    fireEvent.keyDown(container.querySelector("select")!, { key: "Escape" });
    expect(container.querySelector("select")).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("a typed key in an open list is not taken by the grid (not prevented, not buffered)", async () => {
    mockEditor.mockResolvedValueOnce(choiceEditor(3));
    const { container, getByText } = renderTable({ table: editTable() });
    await openChoiceEditor(container, getByText);
    const select = container.querySelector<HTMLSelectElement>("select")!;
    fireEvent.mouseDown(select);
    const popup = document.querySelector<HTMLElement>(".sel-popup")!;

    expect(fireEvent.keyDown(popup, { key: "x" })).toBe(true);
  });
});

describe("ReportTable keys that are not the grid's", () => {
  beforeEach(() => {
    mockEditor.mockReset();
    mockSave.mockReset();
  });

  it("an IME composition key (isComposing, Process, Dead) opens no editor and is not prevented", () => {
    mockEditor.mockResolvedValue(editorOf());
    const { container, getByText } = renderTable({ table: editTable() });
    fireEvent.click(getByText("Бат").closest("td")!);
    expect(fireEvent.keyDown(gridOf(container), { key: "F2", isComposing: true })).toBe(true);
    expect(fireEvent.keyDown(gridOf(container), { key: "Process" })).toBe(true);
    expect(fireEvent.keyDown(gridOf(container), { key: "Dead" })).toBe(true);
    expect(mockEditor).not.toHaveBeenCalled();
  });

  it("Tab during a bulk preview is not prevented, so the bar's buttons can be reached", async () => {
    const mockBulk = vi.mocked(bulkCells);
    mockBulk.mockReset();
    mockBulk.mockImplementation(async (cells) => ({
      saved: 0,
      cells: cells.map((c) => ({ person: c.person, field: c.field, ok: true, text: c.text, error: "" })),
    }));
    const target: ReportEditTarget = { route: "cell", person: 1, field: "job_title", kind: "", key: 0, record: 0, salary: false };
    const { container, getByText } = renderTable({
      table: table({ count: 1, groups: [{ label: "", count: 1, rows: [[{ ...cell("Бат"), edit: target }]] }] }),
    });
    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.paste(gridOf(container), { clipboardData: { getData: () => "x" } });
    await waitFor(() => expect(container.querySelector("[data-bulk-bar]")).not.toBeNull());

    expect(fireEvent.keyDown(gridOf(container), { key: "Tab" })).toBe(true);
    expect(fireEvent.keyDown(gridOf(container), { key: "Tab", shiftKey: true })).toBe(true);
    expect(fireEvent.keyDown(gridOf(container), { key: "F5" })).toBe(true);
    expect(container.querySelector("[data-bulk-bar]")).not.toBeNull();
  });
});

describe("withSavedTexts keeps the identity of rows without a saved text", () => {
  it("a row with no saved cell is the same object; a row with one is a new one", () => {
    const groups = [{ label: "", count: 2, rows: [[editableCell("Бат")], [cell("Сарнай")]] }];
    const saved = new Map([[targetKey(EDIT), "Шинэ"]]);
    const out = withSavedTexts(groups, saved);
    expect(out[0].rows[1]).toBe(groups[0].rows[1]);
    expect(out[0].rows[0]).not.toBe(groups[0].rows[0]);
    expect(out[0].rows[0][0].text).toBe("Шинэ");
    expect(withSavedTexts(groups, new Map())).toBe(groups);
  });
});
