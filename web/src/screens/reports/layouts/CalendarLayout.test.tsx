import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../../api/schema";
import { CalendarLayout } from "./CalendarLayout";

type CalendarOut = components["schemas"]["ReportCalendarOut"];
type DayOut = components["schemas"]["ReportDayOut"];
type EntryOut = components["schemas"]["ReportEntryOut"];

function entry(overrides: Partial<EntryOut> = {}): EntryOut {
  return { href: "", mark: "", note: "", title: "Оруулга", ...overrides };
}

function day(iso: string, overrides: Partial<DayOut> = {}): DayOut {
  return {
    entries: [],
    in_month: true,
    is_today: false,
    iso,
    more: 0,
    more_href: "",
    number: Number(iso.slice(8, 10)),
    ...overrides,
  };
}

// A month of 6 weeks (42 cells) starting on Monday 2026-04-27, with the month of May 2026.
function monthCells(): DayOut[][] {
  const cells: DayOut[] = [];
  const start = new Date(Date.UTC(2026, 3, 27));
  for (let i = 0; i < 42; i++) {
    const date = new Date(start.getTime() + i * 86400000);
    const iso = date.toISOString().slice(0, 10);
    cells.push(day(iso, { in_month: iso.startsWith("2026-05") }));
  }
  const weeks: DayOut[][] = [];
  for (let i = 0; i < 42; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function monthCalendar(overrides: Partial<CalendarOut> = {}): CalendarOut {
  return {
    days: [],
    heading: "2026 оны 5-р сар",
    keep: [],
    mode: "month",
    month_value: "2026-05",
    next_href: "/reports/x/?layout=calendar&lmonth=2026-06",
    prev_href: "/reports/x/?layout=calendar&lmonth=2026-04",
    switch_href: "/reports/x/?layout=calendar&lweek=2026-05-04",
    today_href: "/reports/x/?layout=calendar",
    total: 3,
    undated: 0,
    weeks: monthCells(),
    ...overrides,
  };
}

function weekCalendar(overrides: Partial<CalendarOut> = {}): CalendarOut {
  const days: DayOut[] = [];
  for (let i = 0; i < 7; i++) {
    const iso = `2026-05-${String(4 + i).padStart(2, "0")}`;
    days.push(day(iso));
  }
  return {
    days,
    heading: "2026-05-04 – 2026-05-10",
    keep: [],
    mode: "week",
    month_value: "",
    next_href: "/reports/x/?layout=calendar&lweek=2026-05-11",
    prev_href: "/reports/x/?layout=calendar&lweek=2026-04-27",
    switch_href: "/reports/x/?layout=calendar&lmonth=2026-05",
    today_href: "/reports/x/?layout=calendar&lweek=2026-05-04",
    total: 3,
    undated: 0,
    weeks: [],
    ...overrides,
  };
}

function renderCalendar(calendar: CalendarOut, onChange = vi.fn(), query = "layout=calendar") {
  const utils = render(
    <MemoryRouter>
      <CalendarLayout calendar={calendar} query={query} onChange={onChange} />
    </MemoryRouter>,
  );
  return { ...utils, onChange };
}

afterEach(() => {
  cleanup();
});

describe("CalendarLayout", () => {
  it("month grid has seven weekday heads and a cell per day with today ringed", () => {
    const weeks = monthCells();
    weeks[1][2] = { ...weeks[1][2], is_today: true };
    const { container } = renderCalendar(monthCalendar({ weeks }));
    const grid = container.querySelector(".grid-cols-7") as HTMLElement;
    expect(grid.className).toContain("hidden");
    expect(grid.className).toContain("sm:grid");
    const heads = Array.from(grid.children).slice(0, 7).map((node) => node.textContent);
    expect(heads).toEqual(["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"]);
    const cells = container.querySelectorAll("[data-day]");
    expect(cells.length).toBe(42);
    const today = container.querySelector("[data-today]") as HTMLElement;
    expect(today.getAttribute("data-day")).toBe(weeks[1][2].iso);
    expect(today.className).toContain("ring-2 ring-violet-600");
    const outside = container.querySelector(`[data-day="2026-04-27"]`) as HTMLElement;
    expect(outside.className).toContain("bg-slate-50");
  });

  it("the phone day list shows only busy days or the empty text", () => {
    const weeks = monthCells();
    // weeks[1][3] is 2026-05-07, inside May; weeks[0][3] is 2026-04-30, outside it.
    weeks[1][3] = { ...weeks[1][3], entries: [entry({ title: "Ажил" })] };
    const { container, rerender } = renderCalendar(monthCalendar({ weeks }));
    const sections = container.querySelectorAll("[data-list-day]");
    expect(Array.from(sections).map((node) => node.getAttribute("data-list-day"))).toEqual([weeks[1][3].iso]);
    expect(container.textContent).not.toContain("Энэ сард оруулга алга");

    // An out-of-month day with an entry is drawn in the grid (greyed) but is not in the phone list.
    const outside = monthCells();
    outside[0][3] = { ...outside[0][3], entries: [entry({ title: "Хуучин" })] };
    const grey = renderCalendar(monthCalendar({ weeks: outside }));
    expect(grey.container.querySelectorAll("[data-list-day]").length).toBe(0);
    expect(grey.container.querySelector(`[data-day="${outside[0][3].iso}"]`)?.textContent).toContain("Хуучин");
    expect(grey.container.textContent).toContain("Энэ сард оруулга алга");
    grey.unmount();

    const empty = monthCells();
    rerender(
      <MemoryRouter>
        <CalendarLayout calendar={monthCalendar({ weeks: empty, total: 1 })} query="" onChange={vi.fn()} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll("[data-list-day]").length).toBe(0);
    expect(container.textContent).toContain("Энэ сард оруулга алга");
  });

  it("the week phone list uses the week empty text", () => {
    const { container } = renderCalendar(weekCalendar());
    expect(container.querySelectorAll("[data-list-day]").length).toBe(0);
    expect(container.textContent).toContain("Энэ долоо хоногт оруулга алга");
  });

  it("a disabled arrow is a span with aria-disabled and sr-only text", () => {
    const { container, getByLabelText } = renderCalendar(monthCalendar({ prev_href: "" }));
    const span = container.querySelector('span[aria-disabled="true"]') as HTMLElement;
    expect(span).not.toBeNull();
    expect(span.tagName).toBe("SPAN");
    const srOnly = span.querySelector(".sr-only") as HTMLElement;
    expect(srOnly.textContent).toBe("Өмнөх сар");
    expect(span.querySelector('[aria-hidden="true"]')?.textContent).toBe("‹");
    expect(container.querySelector('a[aria-label="Өмнөх сар"]')).toBeNull();
    expect(getByLabelText("Дараах сар").getAttribute("href")).toBe(monthCalendar().next_href);
  });

  it("the month input navigates on change with min 1900-01 and max 2100-12", () => {
    const { getByLabelText, onChange } = renderCalendar(
      monthCalendar(),
      vi.fn(),
      "layout=calendar&lmonth=2026-05&add=a%20b",
    );
    // The shared DatePicker in month mode: a text box that keeps the name and the value.
    const input = getByLabelText("Сар сонгох") as HTMLInputElement;
    expect(input.getAttribute("name")).toBe("lmonth");
    expect(input.value).toBe("2026-05");
    // A partial value does not navigate; the page keeps the typed text until the value is complete.
    fireEvent.change(input, { target: { value: "2027-0" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "2027-01" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("layout=calendar&lmonth=2027-01&add=a%20b");
  });

  it("the month box ignores empty, out-of-range and unchanged values", () => {
    const { getByLabelText, onChange } = renderCalendar(monthCalendar(), vi.fn(), "layout=calendar&lmonth=2026-05");
    const input = getByLabelText("Сар сонгох") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "1899-12" } });
    fireEvent.change(input, { target: { value: "2026-13" } });
    fireEvent.change(input, { target: { value: "2026-05" } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("week and month switch links", () => {
    const month = renderCalendar(monthCalendar());
    const weekLink = month.getByText("7 хоног").closest("a") as HTMLAnchorElement;
    expect(weekLink.getAttribute("href")).toBe(monthCalendar().switch_href);
    const current = month.getByText("Сар");
    expect(current.getAttribute("aria-current")).toBe("true");
    expect(current.tagName).toBe("SPAN");
    month.unmount();

    const week = renderCalendar(weekCalendar());
    const monthLink = week.getByText("Сар").closest("a") as HTMLAnchorElement;
    expect(monthLink.getAttribute("href")).toBe(weekCalendar().switch_href);
    const weekCurrent = week.getByText("7 хоног");
    expect(weekCurrent.getAttribute("aria-current")).toBe("true");
    expect(weekCurrent.tagName).toBe("SPAN");
    expect(week.getByText("Өнөөдөр").getAttribute("href")).toBe(weekCalendar().today_href);
  });

  it("the week arrows use week labels and the month form is month mode only", () => {
    const week = renderCalendar(weekCalendar());
    expect(week.getByLabelText("Өмнөх долоо хоног").getAttribute("href")).toBe(weekCalendar().prev_href);
    expect(week.getByLabelText("Дараах долоо хоног").getAttribute("href")).toBe(weekCalendar().next_href);
    expect(week.container.querySelector("input[type='month']")).toBeNull();
  });

  it("+N is a link in month and plain text in week", () => {
    const monthWeeks = monthCells();
    monthWeeks[0][3] = {
      ...monthWeeks[0][3],
      more: 4,
      more_href: "/reports/x/?layout=calendar&lweek=2026-04-27",
    };
    const month = renderCalendar(monthCalendar({ weeks: monthWeeks }));
    // The grid and the phone list both print the «+4» of the day; the grid's one is the link.
    const links = Array.from(month.container.querySelectorAll("a")).filter((node) => node.textContent === "+4");
    expect(links.length).toBe(1);
    expect(links[0].getAttribute("href")).toContain("lweek=2026-04-27");
    // weeks[0][3] is outside May, so the phone list does not print it: the grid's link is the only «+4».
    expect(month.getAllByText("+4").length).toBe(1);
    month.unmount();

    const weekDays = weekCalendar().days;
    weekDays[0] = { ...weekDays[0], more: 3, more_href: "" };
    const week = renderCalendar(weekCalendar({ days: weekDays }));
    const plain = week.getAllByText("+3");
    expect(plain.length).toBe(2);
    expect(plain.every((node) => node.closest("a") === null)).toBe(true);
  });

  it("undated note", () => {
    const { getByText, queryByText, unmount } = renderCalendar(monthCalendar({ undated: 2 }));
    expect(getByText("Огноогүй: 2")).toBeTruthy();
    unmount();
    expect(queryByText(/Огноогүй/)).toBeNull();
    const none = renderCalendar(monthCalendar({ undated: 0 }));
    expect(none.queryByText(/Огноогүй/)).toBeNull();
  });

  it("entry chip links only with an href and HTML in a title is text", () => {
    const weeks = monthCells();
    weeks[0][3] = {
      ...weeks[0][3],
      entries: [
        entry({ title: "Линк", href: "/reports/x/?layout=table", mark: "bg-emerald-100 text-emerald-800", note: "Тэмдэглэл" }),
        entry({ title: "<b>Текст</b>", note: "<i>x</i>" }),
      ],
    };
    const { container, getAllByText } = renderCalendar(monthCalendar({ weeks }));
    // The day's chips are in the grid and again in the phone list; the first match is the grid's.
    const link = getAllByText("Линк")[0].closest("a") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/reports/x/?layout=table");
    const chip = link.closest("li") as HTMLElement;
    expect(chip.getAttribute("title")).toBe("Линк · Тэмдэглэл");
    expect(chip.className).toContain("bg-emerald-100 text-emerald-800");

    const plain = getAllByText("<b>Текст</b>")[0];
    expect(plain.closest("a")).toBeNull();
    expect(plain.closest("li")?.className).toContain("bg-violet-100 text-violet-800");
    expect(plain.closest("li")?.getAttribute("title")).toBe("<b>Текст</b> · <i>x</i>");
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("i")).toBeNull();
  });

  it("empty calendar shows the empty text", () => {
    const { getByText, container } = renderCalendar(monthCalendar({ total: 0, weeks: [] }));
    expect(getByText("Өгөгдөл олдсонгүй")).toBeTruthy();
    expect(container.querySelector("h2")).toBeNull();
    expect(container.querySelector("input[type='month']")).toBeNull();
  });
});
