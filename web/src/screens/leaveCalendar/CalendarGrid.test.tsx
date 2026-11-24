import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { LeaveCalendarOut } from "../../api/leavePages";
import { CalendarGrid } from "./CalendarGrid";

// Three days: the first is a holiday and off, the second is today. Two people: one has annual leave, a long leave
// day, and an off day; the other has other leave.
const VIEW: LeaveCalendarOut = {
  can_settings: false,
  days: [
    { date: "2026-03-01", day: 1, off: true, holiday: true, today: false },
    { date: "2026-03-02", day: 2, off: false, holiday: false, today: true },
    { date: "2026-03-03", day: 3, off: false, holiday: false, today: false },
  ],
  department: null,
  departments: [],
  lines: [
    {
      employee_id: 7,
      employee_name: "Бат Болд",
      cells: [
        { kind: "", leave_type_id: null, title: "" },
        { kind: "annual", leave_type_id: 5, title: "Жилийн амралт" },
        { kind: "long", leave_type_id: null, title: "Урт чөлөө" },
      ],
    },
    {
      employee_id: 8,
      employee_name: "Дорж Сарна",
      cells: [
        { kind: "", leave_type_id: null, title: "" },
        { kind: "other", leave_type_id: 6, title: "Өвчтэй" },
        { kind: "", leave_type_id: null, title: "" },
      ],
    },
  ],
  month: "2026-03",
  next: "2026-04",
  not_configured: "",
  prev: "2026-02",
  this_month: "",
  title: "Багийн хуанли — 2026-03",
};

function renderGrid() {
  return render(
    <MemoryRouter>
      <CalendarGrid view={VIEW} />
    </MemoryRouter>,
  );
}

function cellsOf(rowIndex: number): HTMLElement[] {
  const row = document.querySelectorAll("tbody tr")[rowIndex];
  // The first cell is the employee's name.
  return Array.from(row.querySelectorAll<HTMLElement>("td")).slice(1);
}

describe("CalendarGrid", () => {
  afterEach(() => {
    cleanup();
  });

  it("marks a holiday day in the header with data-holiday and red text", () => {
    renderGrid();
    const holiday = document.querySelector<HTMLElement>('th[data-holiday="2026-03-01"]');
    expect(holiday?.className).toContain("text-red-600");
  });

  it("marks today in the header with data-today and the ring", () => {
    renderGrid();
    const today = document.querySelector<HTMLElement>('th[data-today="2026-03-02"]');
    expect(today?.className).toContain("ring-violet-600");
    expect(document.querySelector('th[data-today="2026-03-01"]')).toBeNull();
  });

  it("colours counted leave by kind and marks the leave type", () => {
    renderGrid();
    const annual = cellsOf(0)[1];
    expect(annual.className).toContain("bg-violet-200");
    expect(annual.getAttribute("data-leave")).toBe("5");
    expect(annual.getAttribute("title")).toBe("Жилийн амралт");

    const other = cellsOf(1)[1];
    expect(other.className).toContain("bg-amber-200");
    expect(other.getAttribute("data-leave")).toBe("6");
  });

  it("colours long leave sky and marks it with data-long-leave and its title", () => {
    renderGrid();
    const long = cellsOf(0)[2];
    expect(long.className).toContain("bg-sky-200");
    expect(long.hasAttribute("data-long-leave")).toBe(true);
    expect(long.getAttribute("title")).toBe("Урт чөлөө");
    expect(long.hasAttribute("data-leave")).toBe(false);
  });

  it("shows an off day in the slate colour, and an empty working day with no colour", () => {
    renderGrid();
    const off = cellsOf(0)[0];
    expect(off.className).toContain("bg-slate-100");
    const empty = cellsOf(1)[2];
    expect(empty.className).not.toContain("bg-");
    expect(empty.hasAttribute("data-leave")).toBe(false);
  });

  it("links each name to the employee page", () => {
    renderGrid();
    expect(screen.getByRole("link", { name: "Бат Болд" }).getAttribute("href")).toBe("/employees/7/");
  });
});
