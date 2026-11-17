import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TodayOut } from "../../api/today";
import { TodayStrip } from "./TodayStrip";

// The three lazy hooks are replaced by spies, so no request is made. Each test sets what they return.
const h = vi.hoisted(() => ({
  useAway: vi.fn(),
  useUpcoming: vi.fn(),
  useHires: vi.fn(),
}));
vi.mock("../../api/today", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/today")>()),
  useAway: (day: string | null) => h.useAway(day),
  useUpcoming: (kind: string, enabled: boolean) => h.useUpcoming(kind, enabled),
  useHires: (enabled: boolean) => h.useHires(enabled),
}));

const closed = { data: undefined, isSuccess: false, isError: false };

type Cell = TodayOut["strip"]["cells"][number];

function cell(over: Partial<Cell>): Cell {
  return {
    day: "2026-11-18",
    num: 18,
    weekday: "Ням",
    count: 3,
    shade: "low",
    is_today: false,
    holiday: "",
    clickable: true,
    ...over,
  };
}

function makeData(over: { showLeave?: boolean; showBirthdays?: boolean; holidays?: number } = {}): TodayOut {
  const holidays = Array.from({ length: over.holidays ?? 0 }, (_, i) => ({
    day: `2026-12-0${i + 1}`,
    name: `Баяр ${i + 1}`,
  }));
  return {
    today: "2026-11-17",
    headcount: 12,
    away_today: 1,
    has_own_page: true,
    shortcuts: { add_employee: true, record_leave: true, orders: true },
    box: { tone: "calm", urgent_count: 0, soon_count: 0, gap_count: 0, urgent: [], soon: [], gaps: [], hidden: [] },
    show_views: false,
    strip: {
      show_leave: over.showLeave ?? true,
      first: "2026-11-17",
      last: "2026-11-18",
      today_line: "Өнөөдөр чөлөөтэй хүн алга.",
      cells: [
        cell({ day: "2026-11-17", num: 17, weekday: "Бям", count: 0, shade: "zero", is_today: true }),
        cell({ day: "2026-11-18", num: 18, weekday: "Ням", count: null, shade: "off", clickable: false }),
      ],
    },
    upcoming: {
      holidays,
      open_vacancies: 2,
      checklist: { open: 1, overdue: 0 },
      show_birthdays: over.showBirthdays ?? true,
      birthdays: 2,
      anniversaries: 1,
      new_hires: 0,
    },
    company: null,
  } as unknown as TodayOut;
}

function renderStrip(data: TodayOut) {
  return render(
    <MemoryRouter>
      <TodayStrip data={data} />
    </MemoryRouter>,
  );
}

describe("TodayStrip", () => {
  beforeEach(() => {
    h.useAway.mockReset().mockReturnValue(closed);
    h.useUpcoming.mockReset().mockReturnValue(closed);
    h.useHires.mockReset().mockReturnValue(closed);
  });

  afterEach(() => {
    cleanup();
  });

  it("without the leave right: no away strip, and the upcoming panel spans two columns", () => {
    const { container } = renderStrip(makeData({ showLeave: false }));

    expect(container.querySelector("[data-away-strip]")).toBeNull();
    const upcoming = container.querySelector("[data-upcoming]");
    expect(upcoming?.className).toContain("lg:col-span-2");
  });

  it("an off day is a plain box, not a button", () => {
    renderStrip(makeData());

    expect(screen.queryByRole("button", { name: "2026-11-18: 0 хүн чөлөөтэй" })).toBeNull();
    expect(screen.getByRole("button", { name: "2026-11-17: 0 хүн чөлөөтэй" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "2026-11-17: 0 хүн чөлөөтэй" }).hasAttribute("data-today")).toBe(true);
  });

  it("clicking a counted day asks useAway for that day", () => {
    renderStrip(makeData());

    fireEvent.click(screen.getByRole("button", { name: "2026-11-17: 0 хүн чөлөөтэй" }));

    expect(h.useAway).toHaveBeenLastCalledWith("2026-11-17");
  });

  it("5 holidays show 3 and «+2»", () => {
    const { container } = renderStrip(makeData({ holidays: 5 }));

    const line = container.querySelector("[data-holidays]")?.textContent ?? "";
    expect(line).toContain("Баяр 1");
    expect(line).toContain("Баяр 3");
    expect(line).not.toContain("Баяр 4");
    expect(line.endsWith("+2")).toBe(true);
  });

  it("show_birthdays false: no birthday line", () => {
    renderStrip(makeData({ showBirthdays: false }));

    expect(screen.queryByRole("button", { name: /Төрсөн өдөр/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Ажилласан жилийн ой/ })).toBeTruthy();
  });

  it("the vacancies line links to the recruitment list (recruitment:vacancies is /recruitment/)", () => {
    renderStrip(makeData());

    const link = screen.getByRole("link", { name: "Нээлттэй ажлын байр 2 →" });
    expect(link.getAttribute("href")).toBe("/recruitment/");
  });

  it("the calendar link goes to the leave calendar", () => {
    renderStrip(makeData());

    const link = screen.getByRole("link", { name: "Бүтэн хуанли →" });
    expect(link.getAttribute("href")).toBe("/leave/calendar/");
  });
});
