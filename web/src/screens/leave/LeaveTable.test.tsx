import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { LeaveRowOut } from "../../api/leave";
import { LeaveTable, truncateComment } from "./LeaveTable";

const ROW: LeaveRowOut = {
  id: 1,
  employee_id: 7,
  employee_name: "Бат Болд",
  leave_type: "Жилийн амралт",
  state: "Бүртгэсэн",
  state_chip: false,
  start: "2026-03-01",
  end: "2026-03-03",
  days: 3,
  comment: "Гэр бүл",
  counts: true,
  cancel_label: "Цуцлах",
};

const CANCELLED: LeaveRowOut = {
  ...ROW,
  id: 2,
  employee_id: 8,
  employee_name: "Дорж Сарна",
  state: "Цуцалсан",
  counts: false,
  cancel_label: null,
};

const MISTAKE: LeaveRowOut = {
  ...ROW,
  id: 3,
  employee_id: 9,
  employee_name: "Номин Оюу",
  state: "Буруу бүртгэсэн",
  state_chip: true,
  cancel_label: "Буруу гэж тэмдэглэх",
};

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname}</div>;
}

type Handlers = { onEdit: ReturnType<typeof vi.fn>; onCancel: ReturnType<typeof vi.fn>; onMore: ReturnType<typeof vi.fn> };

function renderTable(
  props: Partial<Parameters<typeof LeaveTable>[0]> & { rows: LeaveRowOut[] },
): Handlers & { container: HTMLElement } {
  const handlers: Handlers = { onEdit: vi.fn(), onCancel: vi.fn(), onMore: vi.fn() };
  const { container } = render(
    <MemoryRouter initialEntries={["/leave/"]}>
      <Routes>
        <Route
          path="/leave/"
          element={
            <LeaveTable
              canRecord={true}
              emptyText="Чөлөө бүртгэгдээгүй"
              hasMore={false}
              loadingMore={false}
              onMore={handlers.onMore}
              onEdit={handlers.onEdit}
              onCancel={handlers.onCancel}
              {...props}
            />
          }
        />
        <Route path="*" element={<p>other page</p>} />
      </Routes>
      <Probe />
    </MemoryRouter>,
  );
  return { ...handlers, container };
}

function rowOf(name: string): HTMLElement {
  const link = screen.getByRole("link", { name });
  const row = link.closest("tr");
  if (!row) throw new Error("no row");
  return row;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LeaveTable", () => {
  it("renders the employee link, type, dates, working days and comment", () => {
    renderTable({ rows: [ROW] });
    const link = screen.getByRole("link", { name: "Бат Болд" });
    expect(link.getAttribute("href")).toBe("/employees/7/");
    const row = rowOf("Бат Болд");
    expect(row.textContent).toContain("Жилийн амралт");
    expect(row.textContent).toContain("2026-03-01 – 2026-03-03");
    const days = Array.from(row.querySelectorAll("td")).find((cell) => cell.textContent?.startsWith("Ажлын өдөр"));
    expect(days?.textContent).toBe("Ажлын өдөр: 3");
    expect(row.textContent).toContain("Гэр бүл");
  });

  it("draws a row that does not count grey and struck through, with no cancel button", () => {
    renderTable({ rows: [CANCELLED] });
    const row = rowOf("Дорж Сарна");
    expect(row.className).toContain("line-through");
    expect(row.className).toContain("text-slate-400");
    expect(row.querySelector("button")).toBeNull();
  });

  it("shows the state as a chip after the type only when state_chip is set", () => {
    renderTable({ rows: [ROW, MISTAKE] });
    expect(rowOf("Бат Болд").textContent).not.toContain("Бүртгэсэн");
    const chip = rowOf("Номин Оюу").querySelector("span.rounded");
    expect(chip?.textContent).toBe("Буруу бүртгэсэн");
  });

  it("the cancel button shows the API's text and calls onCancel without opening the edit pop-up", () => {
    const { onCancel, onEdit } = renderTable({ rows: [ROW] });
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(onCancel).toHaveBeenCalledWith(1);
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("a row click opens the edit pop-up when the user may record and the row counts", () => {
    const { onEdit } = renderTable({ rows: [ROW] });
    fireEvent.click(rowOf("Бат Болд"));
    expect(onEdit).toHaveBeenCalledWith(1);
  });

  it("a row click goes to the employee page when the user may not record", async () => {
    const { onEdit } = renderTable({ rows: [ROW], canRecord: false });
    fireEvent.click(rowOf("Бат Болд"));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/7/"));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("a row that does not count goes to the employee page even for a user who may record", async () => {
    const { onEdit } = renderTable({ rows: [CANCELLED] });
    fireEvent.click(rowOf("Дорж Сарна"));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/8/"));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("the employee name does not trigger the row action", async () => {
    const { onEdit } = renderTable({ rows: [ROW] });
    fireEvent.click(screen.getByRole("link", { name: "Бат Болд" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/7/"));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("Space on the focused row runs the row action too", () => {
    const { onEdit } = renderTable({ rows: [ROW] });
    fireEvent.keyDown(rowOf("Бат Болд"), { key: " " });
    expect(onEdit).toHaveBeenCalledWith(1);
  });

  it("Enter on the focused row runs the row action; keys from the cancel button do not", () => {
    const { onEdit, onCancel } = renderTable({ rows: [ROW] });
    const row = rowOf("Бат Болд");
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("role")).toBeNull();

    fireEvent.keyDown(row, { key: "Enter" });
    expect(onEdit).toHaveBeenCalledWith(1);

    onEdit.mockClear();
    fireEvent.keyDown(screen.getByRole("button", { name: "Цуцлах" }), { key: "Enter" });
    expect(onEdit).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("shows the empty text in a full-width row when there are no rows and no more batches", () => {
    const { container } = renderTable({ rows: [] });
    const cell = screen.getByText("Чөлөө бүртгэгдээгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("6");
    expect(container.querySelector("[data-more-row]")).toBeNull();
  });

  it("hides the empty text while more batches follow, and the more button calls onMore", () => {
    const { onMore } = renderTable({ rows: [], hasMore: true });
    expect(screen.queryByText("Чөлөө бүртгэгдээгүй")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(onMore).toHaveBeenCalledTimes(1);
  });

  it("the more button does nothing while a batch is loading", () => {
    const { onMore } = renderTable({ rows: [ROW], hasMore: true, loadingMore: true });
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(onMore).not.toHaveBeenCalled();
  });

  it("cuts a comment longer than 60 characters to 59 and an ellipsis", () => {
    const long = "а".repeat(70);
    expect(truncateComment(long)).toBe("а".repeat(59) + "…");
    expect(truncateComment("а".repeat(60))).toBe("а".repeat(60));
    renderTable({ rows: [{ ...ROW, comment: long }] });
    expect(rowOf("Бат Болд").textContent).toContain("а".repeat(59) + "…");
  });
});
