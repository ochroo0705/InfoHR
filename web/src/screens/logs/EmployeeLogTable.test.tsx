import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { LogEmployeeRowOut } from "../../api/logs";
import { EmployeeLogTable, type EmployeeLogTableProps } from "./EmployeeLogTable";

function entry(over: Partial<LogEmployeeRowOut> = {}): LogEmployeeRowOut {
  return {
    by_name: "Систем",
    changes: [],
    date: "2026-11-20",
    employee_code: "E001",
    employee_id: 5,
    employee_name: "Бат Болд",
    id: 1,
    is_correction: false,
    is_note: false,
    kind: "history",
    kind_class: "bg-violet-50 text-violet-700",
    kind_label: "Түүх",
    message: "Цалин өөрчлөгдсөн",
    order_id: null,
    time: "10:15",
    ...over,
  };
}

let observerCallback: IntersectionObserverCallback | null = null;

beforeEach(() => {
  observerCallback = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        observerCallback = callback;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderTable(overrides: Partial<EmployeeLogTableProps> = {}) {
  const props: EmployeeLogTableProps = {
    rows: [],
    hasMore: false,
    loadingMore: false,
    onMore: vi.fn(),
    onOpenOrder: vi.fn(),
    ...overrides,
  };
  const view = render(
    <MemoryRouter>
      <EmployeeLogTable {...props} />
    </MemoryRouter>,
  );
  return { ...view, props };
}

function rowOf(container: HTMLElement, index = 0): HTMLTableRowElement {
  return container.querySelectorAll("tbody tr")[index] as HTMLTableRowElement;
}

describe("EmployeeLogTable", () => {
  it("row without an order has no tab stop, no handler, no button and no hover class", () => {
    const { container, props } = renderTable({ rows: [entry()] });
    const tr = rowOf(container);
    expect(tr.className).not.toContain("cursor-pointer");
    expect(tr.className).not.toContain("hover:bg-violet-50");
    expect(tr.className).not.toContain("focus-visible:outline-violet-500");
    expect(tr.hasAttribute("tabindex")).toBe(false);
    expect(tr.querySelector("button")).toBeNull();
    expect(tr.getAttribute("role")).toBeNull();

    fireEvent.click(tr);
    fireEvent.keyDown(tr, { key: "Enter" });
    fireEvent.keyDown(tr, { key: " " });
    expect(props.onOpenOrder).not.toHaveBeenCalled();
  });

  it("row with an order is a tab stop, opens from a click, and has no button", () => {
    const item = entry({ order_id: 9 });
    const { container, props } = renderTable({ rows: [item] });
    const tr = rowOf(container);
    expect(tr.className).toContain("cursor-pointer");
    expect(tr.className).toContain("hover:bg-violet-50");
    expect(tr.className).toContain("focus-visible:outline-violet-500");
    expect(tr.getAttribute("tabindex")).toBe("0");
    expect(tr.getAttribute("role")).toBeNull();
    expect(tr.querySelector("button")).toBeNull();
    expect(tr.textContent).toContain("2026-11-20");

    fireEvent.click(tr);
    expect(props.onOpenOrder).toHaveBeenCalledTimes(1);
    expect(props.onOpenOrder).toHaveBeenLastCalledWith(item);
  });

  it("Enter and Space on the row open the order; other keys do not", () => {
    const item = entry({ order_id: 9 });
    const { container, props } = renderTable({ rows: [item] });
    const tr = rowOf(container);

    fireEvent.keyDown(tr, { key: "Enter" });
    expect(props.onOpenOrder).toHaveBeenCalledTimes(1);
    expect(props.onOpenOrder).toHaveBeenLastCalledWith(item);

    fireEvent.keyDown(tr, { key: " " });
    expect(props.onOpenOrder).toHaveBeenCalledTimes(2);
    expect(props.onOpenOrder).toHaveBeenLastCalledWith(item);

    fireEvent.keyDown(tr, { key: "a" });
    fireEvent.keyDown(tr, { key: "Escape" });
    expect(props.onOpenOrder).toHaveBeenCalledTimes(2);
  });

  it("the name link does not open the order, by click or by Enter and Space", () => {
    const { container, props } = renderTable({ rows: [entry({ order_id: 9 })] });
    const link = screen.getByRole("link", { name: "Бат Болд" });
    expect(link.getAttribute("href")).toBe("/employees/5/");
    fireEvent.click(link);
    fireEvent.keyDown(link, { key: "Enter" });
    fireEvent.keyDown(link, { key: " " });
    expect(props.onOpenOrder).not.toHaveBeenCalled();
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
  });

  it("a note keeps line breaks and html is drawn as text", () => {
    const { container } = renderTable({
      rows: [entry({ is_note: true, kind: "note", message: "<b>эхний</b>\nхоёр дахь" })],
    });
    const note = container.querySelector("p.whitespace-pre-line") as HTMLElement;
    expect(note.className).toBe("whitespace-pre-line rounded-lg bg-sky-50 px-3 py-2");
    expect(note.textContent).toBe("<b>эхний</b>\nхоёр дахь");
    expect(note.querySelector("b")).toBeNull();
  });

  it("a correction message is amber, other messages slate", () => {
    const { container } = renderTable({
      rows: [entry({ is_correction: true, message: "Засвар" }), entry({ id: 2, message: "Энгийн" })],
    });
    expect(container.querySelector("p.text-amber-700")?.textContent).toBe("Засвар");
    expect(container.querySelector("p.text-slate-700")?.textContent).toBe("Энгийн");
  });

  it("shows the changes list when the entry has changes", () => {
    const { container } = renderTable({
      rows: [entry({ changes: [{ field: "Цалин", old: "100", new: "" }] })],
    });
    expect(container.querySelector("dl")?.textContent).toContain("(хоосон)");
  });

  it("empty state", () => {
    const { container } = renderTable({ rows: [] });
    const cell = screen.getByText("Бүртгэл олдсонгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("5");
    expect(container.querySelector(".ptable.ptable-fit.card-soft")).not.toBeNull();
  });

  it("the pill calls onMore once when it scrolls into view and again on click", () => {
    const { props } = renderTable({ rows: [entry()], hasMore: true });
    expect(observerCallback).not.toBeNull();
    observerCallback!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    expect(props.onMore).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).toHaveBeenCalledTimes(2);
  });

  it("settling draws no empty-state row", () => {
    renderTable({ rows: [], settling: true });
    expect(screen.queryByText("Бүртгэл олдсонгүй")).toBeNull();
  });

  it("autoLoad false keeps the pill from loading by scrolling, and its click still loads", () => {
    const { props } = renderTable({ rows: [entry()], hasMore: true, autoLoad: false });
    expect(observerCallback).toBeNull();
    expect(props.onMore).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).toHaveBeenCalledTimes(1);
  });

  it("while a batch loads the pill neither observes nor calls onMore on click", () => {
    const { container, props } = renderTable({ rows: [entry()], hasMore: true, loadingMore: true });
    expect(observerCallback).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).not.toHaveBeenCalled();
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("htmx-request");
  });
});
