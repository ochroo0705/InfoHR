import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LeaveRequestRowOut } from "../../api/leaveRequests";
import { LeaveRequestsTable } from "./LeaveRequestsTable";

const WAITING: LeaveRequestRowOut = {
  id: 1,
  employee_name: "Бат Болд",
  leave_type: "Жилийн амралт",
  start: "2026-03-01",
  end: "2026-03-03",
  working_days: 3,
  waiting: true,
  current_step: 1,
  step_count: 2,
  rule: "Шууд удирдлага",
  status_label: "Хүлээгдэж буй",
  since: "2026-02-27",
};

const DONE: LeaveRequestRowOut = {
  ...WAITING,
  id: 2,
  employee_name: "Дорж Сарна",
  waiting: false,
  current_step: null,
  step_count: null,
  rule: "",
  status_label: "Батлагдсан",
  since: null,
};

type Handlers = { onMore: ReturnType<typeof vi.fn>; onOpen: ReturnType<typeof vi.fn> };

function renderTable(props: Partial<Parameters<typeof LeaveRequestsTable>[0]> & { rows: LeaveRequestRowOut[] }) {
  const handlers: Handlers = { onMore: vi.fn(), onOpen: vi.fn() };
  const view = render(
    <LeaveRequestsTable
      emptyText="Хүсэлт олдсонгүй"
      hasMore={false}
      loadingMore={false}
      onMore={handlers.onMore}
      onOpen={handlers.onOpen}
      {...props}
    />,
  );
  return { ...view, ...handlers };
}

function rowOf(name: string): HTMLElement {
  const cell = screen.getByText(name);
  const row = cell.closest("tr");
  if (!row) throw new Error("no row");
  return row;
}

function cellsOf(name: string): string[] {
  return Array.from(rowOf(name).querySelectorAll("td")).map((td) => td.textContent ?? "");
}

describe("LeaveRequestsTable", () => {
  afterEach(() => {
    cleanup();
  });

  it("the columns are Django's, in its order", () => {
    const { container } = renderTable({ rows: [WAITING] });
    const heads = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(heads).toEqual([
      "Ажилтан",
      "Төрөл",
      "Хугацаа",
      "Ажлын өдөр",
      "Шат",
      "Батлах",
      "Төлөв",
      "Хүлээж эхэлсэн",
    ]);
  });

  it("a waiting row shows its step as current/count, the rule and the since date", () => {
    renderTable({ rows: [WAITING] });
    expect(cellsOf("Бат Болд")).toEqual([
      "Бат Болд",
      "Жилийн амралт",
      "2026-03-01 – 2026-03-03",
      "3",
      "1/2",
      "Шууд удирдлага",
      "Хүлээгдэж буй",
      "2026-02-27",
    ]);
  });

  it("a row that is not waiting shows a dash for step, rule and since", () => {
    renderTable({ rows: [DONE] });
    expect(cellsOf("Дорж Сарна")).toEqual([
      "Дорж Сарна",
      "Жилийн амралт",
      "2026-03-01 – 2026-03-03",
      "3",
      "—",
      "—",
      "Батлагдсан",
      "—",
    ]);
  });

  it("the working days cell is right-aligned", () => {
    renderTable({ rows: [WAITING] });
    const days = rowOf("Бат Болд").querySelectorAll("td")[3];
    expect(days.className.includes("text-right")).toBe(true);
  });

  it("the table sits in its own scrolling card (no card fold below md)", () => {
    const { container } = renderTable({ rows: [WAITING] });
    const card = container.querySelector("table")?.parentElement;
    expect(card?.className.includes("overflow-x-auto")).toBe(true);
    expect(container.querySelector("tr")?.className.includes("block")).toBe(false);
  });

  it("no rows and no more batches: the empty text in one full-width row", () => {
    const { container } = renderTable({ rows: [], emptyText: "Хүсэлт олдсонгүй" });
    const cell = container.querySelector("tbody td");
    expect(cell?.getAttribute("colspan")).toBe("8");
    expect(cell?.textContent).toBe("Хүсэлт олдсонгүй");
  });

  it("no empty text while another batch can come", () => {
    renderTable({ rows: [], hasMore: true });
    expect(screen.queryByText("Хүсэлт олдсонгүй")).toBeNull();
    expect(screen.getByRole("button", { name: "Цааш харуулах" })).toBeTruthy();
  });

  it("the more pill asks for the next batch on click, but not while one is loading", () => {
    const first = renderTable({ rows: [WAITING], hasMore: true });
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(first.onMore).toHaveBeenCalledTimes(1);
    cleanup();

    const loading = renderTable({ rows: [WAITING], hasMore: true, loadingMore: true });
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(loading.onMore).not.toHaveBeenCalled();
  });

  it("a row is a tab stop with no role=button of its own", () => {
    renderTable({ rows: [WAITING] });
    const row = rowOf("Бат Болд");
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.hasAttribute("role")).toBe(false);
  });

  it("a click on the row opens it with its id", () => {
    const { onOpen } = renderTable({ rows: [WAITING] });
    fireEvent.click(rowOf("Бат Болд"));
    expect(onOpen).toHaveBeenCalledWith(1);
  });

  it("Enter and Space on the row open it; other keys do not", () => {
    const { onOpen } = renderTable({ rows: [WAITING] });
    const row = rowOf("Бат Болд");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onOpen).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(row, { key: " " });
    expect(onOpen).toHaveBeenLastCalledWith(1);
    expect(onOpen).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(row, { key: "a" });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
