import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LeaveTypeOut } from "../../api/leaveSetup";
import { TypesTable } from "./TypesTable";

const PAID: LeaveTypeOut = {
  id: 1,
  name: "Жилийн амралт",
  is_paid: true,
  uses_annual_balance: true,
  is_active: true,
  order: 0,
  staff_may_request: true,
};

const OLD: LeaveTypeOut = {
  id: 2,
  name: "Хуучин төрөл",
  is_paid: false,
  uses_annual_balance: false,
  is_active: false,
  order: 1,
  staff_may_request: false,
};

function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest("tr") as HTMLElement;
}

describe("TypesTable", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the header and one row per type with Тийм or Үгүй in each flag cell", () => {
    render(<TypesTable types={[PAID, OLD]} onOpen={vi.fn()} />);

    const header = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(header).toEqual([
      "Нэр",
      "Цалинтай",
      "Ээлжийн амралтаас хасна",
      "Идэвхтэй",
      "Ажилтан хүсэлт гаргана",
    ]);
    const cells = within(rowOf("Жилийн амралт"))
      .getAllByRole("cell")
      .map((td) => td.textContent);
    expect(cells).toEqual(["Жилийн амралт", "Тийм", "Тийм", "Тийм", "Тийм"]);
    const oldCells = within(rowOf("Хуучин төрөл"))
      .getAllByRole("cell")
      .map((td) => td.textContent);
    expect(oldCells).toEqual(["Хуучин төрөл", "Үгүй", "Үгүй", "Үгүй", "Үгүй"]);
  });

  it("an inactive type is struck through and grey", () => {
    render(<TypesTable types={[PAID, OLD]} onOpen={vi.fn()} />);

    expect(rowOf("Хуучин төрөл").className).toContain("line-through");
    expect(rowOf("Хуучин төрөл").className).toContain("text-slate-400");
    expect(rowOf("Жилийн амралт").className).not.toContain("line-through");
  });

  it("a click on a row opens that type with its id", () => {
    const onOpen = vi.fn();
    render(<TypesTable types={[PAID, OLD]} onOpen={onOpen} />);

    fireEvent.click(screen.getByText("Хуучин төрөл"));

    expect(onOpen).toHaveBeenCalledWith(2);
  });

  it("Enter and Space on a focused row open it too", () => {
    const onOpen = vi.fn();
    render(<TypesTable types={[PAID]} onOpen={onOpen} />);

    fireEvent.keyDown(rowOf("Жилийн амралт"), { key: "Enter" });
    fireEvent.keyDown(rowOf("Жилийн амралт"), { key: " " });

    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(onOpen).toHaveBeenLastCalledWith(1);
  });

  it("no types says so in a full-width row", () => {
    render(<TypesTable types={[]} onOpen={vi.fn()} />);

    const cell = screen.getByText("Чөлөөний төрөл бүртгээгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("5");
    expect(cell.className).toContain("text-slate-500");
  });
});
