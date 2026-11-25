// The harness is imported first: it stubs fetch before ../../api/client (and so ../../api/reports) load.
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers, urlOf } from "../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import { setCsrf } from "../../api/client";
import type { ReportCellOut, ReportHeadCellOut, ReportTableOut } from "../../api/reports";
import { ReportTable, type ReportTableProps } from "./ReportTable";

const HEAD: ReportHeadCellOut = {
  label: "Нэр",
  href: "/reports/staff/?sort=name",
  append_href: "/reports/staff/?sort=name,-number",
  arrow: "",
  css: "",
  sticky_left: "",
};

function cell(value: string): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0 };
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
      { value: "2500000.00", text: "2500000.00", money: true, href: "", css: "text-right", style: "", person: 0 },
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
