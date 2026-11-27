// The harness is imported first: it stubs fetch before ../../../api/client (and so the reports api) load.
import "../../../api/testSupport";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../../api/schema";
import { PivotLayout } from "./PivotLayout";

type PivotOut = components["schemas"]["ReportPivotOut"];
type GridOut = components["schemas"]["ReportPivotGridOut"];

function grid(overrides: Partial<GridOut> = {}): GridOut {
  return {
    caption: "Цалин",
    col_heads: [],
    col_totals: [],
    corner_label: "Алба",
    empty: false,
    grand: "",
    masked: false,
    note: "",
    rows: [],
    ...overrides,
  };
}

function pivot(overrides: Partial<PivotOut> = {}): PivotOut {
  return { grids: [grid()], ...overrides };
}

function renderPivot(value: PivotOut) {
  return render(
    <MemoryRouter>
      <PivotLayout pivot={value} />
    </MemoryRouter>,
  );
}

afterEach(() => cleanup());

describe("PivotLayout", () => {
  it("draws caption, column heads with links, row heads, cells, totals and the grand total", () => {
    const { container, getByText, getAllByText } = renderPivot(
      pivot({
        grids: [
          grid({
            caption: "Цалин",
            corner_label: "Алба",
            col_heads: [
              { label: "Эрэгтэй", href: "/reports/staff/?cby=sex&cby_v=m" },
              { label: "Эмэгтэй", href: "" },
            ],
            rows: [
              {
                label: "Санхүү",
                href: "/reports/staff/?lby=dept&lby_v=fin",
                cells: [
                  { text: "2,000₮", href: "/reports/staff/?lby=dept&lby_v=fin&cby=sex&cby_v=m" },
                  { text: "1,000₮", href: "" },
                ],
                total: "3,000₮",
              },
            ],
            col_totals: ["2,000₮", "1,000₮"],
            grand: "3,000₮",
          }),
        ],
      }),
    );
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(container.querySelector("div.ptable.ptable-fit.mt-4")).not.toBeNull();
    expect(container.querySelector("caption")?.textContent).toBe("Цалин");
    expect(container.querySelector("thead th[scope='col']")?.textContent).toBe("Алба");
    const headLink = getByText("Эрэгтэй").closest("a");
    expect(headLink?.getAttribute("href")).toBe("/reports/staff/?cby=sex&cby_v=m");
    expect(getByText("Эмэгтэй").tagName).toBe("TH");
    const rowHead = getByText("Санхүү");
    expect(rowHead.tagName).toBe("A");
    expect(rowHead.closest("th")?.getAttribute("scope")).toBe("row");
    expect(getByText("3,000₮", { selector: "td.font-semibold" })).toBeTruthy();
    expect(getAllByText("1,000₮").length).toBe(2);
    expect(getByText("2,000₮", { selector: "tfoot td" })).toBeTruthy();
    expect(container.querySelector("tfoot tr")?.className).toContain("border-slate-300");
    expect(getByText("3,000₮", { selector: "tfoot td" })).toBeTruthy();
    expect(getByText("Дүн", { selector: "tfoot th" })).toBeTruthy();
    expect(getByText("Дүн", { selector: "thead th" })).toBeTruthy();
  });

  it("a head, row or cell without an href is plain text", () => {
    const { container, getByText } = renderPivot(
      pivot({
        grids: [
          grid({
            col_heads: [{ label: "Нэг", href: "" }],
            rows: [{ label: "Мөр", href: "", cells: [{ text: "5", href: "" }], total: "9" }],
            col_totals: ["4"],
            grand: "6",
          }),
        ],
      }),
    );
    expect(container.querySelectorAll("a").length).toBe(0);
    expect(getByText("Нэг").tagName).toBe("TH");
    expect(getByText("Мөр").tagName).toBe("TH");
    expect(getByText("5", { selector: "td:not(.font-semibold)" }).tagName).toBe("TD");
    expect(getByText("9", { selector: "td.font-semibold" }).tagName).toBe("TD");
    expect(getByText("4", { selector: "tfoot td" }).tagName).toBe("TD");
    expect(getByText("6", { selector: "tfoot td" }).tagName).toBe("TD");
  });

  it("two grids for a second value", () => {
    const { container, getAllByText } = renderPivot(
      pivot({
        grids: [
          grid({ caption: "Цалин", rows: [{ label: "А", href: "", cells: [], total: "1" }], grand: "1" }),
          grid({ caption: "Бонус", rows: [{ label: "А", href: "", cells: [], total: "2" }], grand: "2" }),
        ],
      }),
    );
    expect(container.querySelectorAll("table").length).toBe(2);
    expect(container.querySelectorAll("caption")[0].textContent).toBe("Цалин");
    expect(container.querySelectorAll("caption")[1].textContent).toBe("Бонус");
    expect(getAllByText("А").length).toBe(2);
  });

  it("masked note shows only when masked", () => {
    const note = "5-аас цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»).";
    const masked = renderPivot(pivot({ grids: [grid({ masked: true, note })] }));
    expect(masked.getByText(note).className).toContain("text-slate-500");
    masked.unmount();
    const plain = renderPivot(pivot({ grids: [grid({ masked: false, note })] }));
    expect(plain.queryByText(note)).toBeNull();
  });

  it("empty grid shows the empty text", () => {
    const { container, getByText } = renderPivot(pivot({ grids: [grid({ empty: true })] }));
    const text = getByText("Өгөгдөл олдсонгүй");
    expect(text.className).toContain("text-slate-400");
    expect(container.querySelector("table")).toBeNull();
  });

  it("HTML in a label is text", () => {
    const { container, getByText } = renderPivot(
      pivot({
        grids: [
          grid({
            col_heads: [{ label: "<b>x</b>", href: "" }],
            rows: [{ label: "<i>y</i>", href: "", cells: [], total: "0" }],
          }),
        ],
      }),
    );
    expect(getByText("<b>x</b>").tagName).toBe("TH");
    expect(getByText("<i>y</i>").tagName).toBe("TH");
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("i")).toBeNull();
  });

  it("a cell link goes to its address", () => {
    const { getByText } = renderPivot(
      pivot({
        grids: [
          grid({
            rows: [{ label: "А", href: "", cells: [{ text: "7", href: "/reports/staff/?x=1" }], total: "8" }],
          }),
        ],
      }),
    );
    const link = getByText("7", { selector: "td a" });
    expect(link?.getAttribute("href")).toBe("/reports/staff/?x=1");
    expect(link?.getAttribute("title")).toBe("Эдгээр мөрийг хүснэгтээр харах");
    expect(link?.className).toContain("text-violet-700");
  });
});
