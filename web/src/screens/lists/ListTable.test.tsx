import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ListColumnOut, ListRowOut } from "../../api/lists";
import { ListTable } from "./ListTable";

const COLUMNS: ListColumnOut[] = [
  { name: "name", label: "Нэр" },
  { name: "size_type", label: "Төрөл" },
];

const ROWS: ListRowOut[] = [
  { id: 7, cells: ["M", "Хувцас"] },
  { id: -3, cells: ["XL", "Гутал"] },
];

afterEach(() => {
  cleanup();
});

describe("ListTable", () => {
  it("draws the header labels and the cells as given", () => {
    render(<ListTable columns={COLUMNS} rows={ROWS} onOpen={() => {}} />);

    expect(screen.getByRole("columnheader", { name: "Нэр" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Төрөл" })).toBeTruthy();
    const rows = screen.getAllByRole("row");
    // The header row plus the two entries.
    expect(rows).toHaveLength(3);
    expect(rows[1].textContent).toBe("MХувцас");
    expect(rows[2].textContent).toBe("XLГутал");
  });

  it("shows the empty row across every column when there are no entries", () => {
    render(<ListTable columns={COLUMNS} rows={[]} onOpen={() => {}} />);

    const cell = screen.getByText("бүртгэгдээгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("2");
    expect(cell.className).toContain("text-slate-400");
  });

  it("opens the entry on a click with its pk", () => {
    const onOpen = vi.fn();
    render(<ListTable columns={COLUMNS} rows={ROWS} onOpen={onOpen} />);

    fireEvent.click(screen.getByText("XL"));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(-3);
  });

  it("makes every row a tab stop and opens it with Enter or Space", () => {
    const onOpen = vi.fn();
    render(<ListTable columns={COLUMNS} rows={ROWS} onOpen={onOpen} />);

    const [first] = screen.getAllByRole("row").slice(1);
    expect(first.getAttribute("tabindex")).toBe("0");

    fireEvent.keyDown(first, { key: "Enter" });
    expect(onOpen).toHaveBeenLastCalledWith(7);

    fireEvent.keyDown(first, { key: " " });
    expect(onOpen).toHaveBeenLastCalledWith(7);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("ignores other keys on a row", () => {
    const onOpen = vi.fn();
    render(<ListTable columns={COLUMNS} rows={ROWS} onOpen={onOpen} />);

    fireEvent.keyDown(screen.getAllByRole("row")[1], { key: "a" });

    expect(onOpen).not.toHaveBeenCalled();
  });
});
