import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../../api/schema";
import { TimelineLayout } from "./TimelineLayout";

type TimelineOut = components["schemas"]["ReportTimelineOut"];
type TimelineBarOut = components["schemas"]["ReportTimelineBarOut"];
type TimelineGroupOut = components["schemas"]["ReportTimelineGroupOut"];

function bar(overrides: Partial<TimelineBarOut> = {}): TimelineBarOut {
  return {
    href: "",
    label: "Ажил: 2026-03-01 – 2026-03-10",
    left_pct: 10,
    mark: "",
    tip: "2026-03-01 – 2026-03-10 · 10 өдөр",
    tip_title: "Ажил",
    title: "Ажил",
    width_pct: 25,
    ...overrides,
  };
}

function group(overrides: Partial<TimelineGroupOut> = {}): TimelineGroupOut {
  return { bars: [bar()], count: 1, label: "", ...overrides };
}

function timeline(overrides: Partial<TimelineOut> = {}): TimelineOut {
  return {
    all_href: "/reports/x/?layout=timeline&lyear=all",
    cap: 100,
    clipped: false,
    enter_href: "/reports/x/?layout=timeline&lyear=2026",
    first: "2026-01-01",
    groups: [group()],
    last: "2026-12-31",
    off_axis: 0,
    over_cap: 0,
    ticks: [{ label: "2026-04", left_pct: 25 }],
    today_pct: 40,
    total: 1,
    undated: 0,
    year: 2026,
    year_next_href: "/reports/x/?layout=timeline&lyear=2027",
    year_prev_href: "/reports/x/?layout=timeline&lyear=2025",
    years: 5,
    ...overrides,
  };
}

function renderTimeline(value: TimelineOut) {
  return render(
    <MemoryRouter>
      <TimelineLayout timeline={value} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
});

describe("TimelineLayout", () => {
  it("bars are positioned by left and width percent and the today line shows", () => {
    const { container } = renderTimeline(timeline());
    const bars = container.querySelectorAll("[data-bar]");
    expect(bars).toHaveLength(1);
    const style = (bars[0] as HTMLElement).style;
    expect(style.left).toBe("10%");
    expect(style.width).toBe("25%");
    expect(bars[0].getAttribute("aria-label")).toBe("Ажил: 2026-03-01 – 2026-03-10");
    expect(bars[0].className).toContain("bg-violet-500");
    // The today line is drawn in the track and in the axis row.
    const today = container.querySelectorAll("[data-today]");
    expect(today.length).toBeGreaterThan(0);
    expect((today[0] as HTMLElement).style.left).toBe("40%");
    expect(today[0].getAttribute("title")).toBe("Өнөөдөр");
    // The tick and the first and last dates come from the API.
    expect(screen.getByText("2026-04")).toBeTruthy();
    expect(screen.getByText("2026-01-01")).toBeTruthy();
    expect(screen.getByText("2026-12-31")).toBeTruthy();
  });

  it("year window arrows, «Бүгд» and «Он»", () => {
    const { unmount } = renderTimeline(timeline());
    const prev = screen.getByRole("link", { name: "Өмнөх жил" });
    expect(prev.getAttribute("href")).toBe("/reports/x/?layout=timeline&lyear=2025");
    expect(screen.getByRole("link", { name: "Дараах жил" }).getAttribute("href")).toBe(
      "/reports/x/?layout=timeline&lyear=2027",
    );
    expect(screen.getByText("2026")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Бүгд" }).getAttribute("href")).toBe(
      "/reports/x/?layout=timeline&lyear=all",
    );
    expect(screen.queryByRole("link", { name: "Он" })).toBeNull();
    unmount();

    renderTimeline(timeline({ year: null, year_prev_href: null, year_next_href: null }));
    const enter = screen.getByRole("link", { name: "Он" });
    expect(enter.getAttribute("href")).toBe("/reports/x/?layout=timeline&lyear=2026");
    expect(enter.getAttribute("title")).toBe("Нэг жилээр харах");
    expect(screen.queryByRole("link", { name: "Бүгд" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Өмнөх жил" })).toBeNull();
  });

  it("a disabled year arrow is a span with aria-disabled", () => {
    const { container } = renderTimeline(timeline({ year_prev_href: null }));
    const disabled = container.querySelector('[aria-disabled="true"]');
    expect(disabled).not.toBeNull();
    expect(disabled?.tagName).toBe("SPAN");
    expect(within(disabled as HTMLElement).getByText("Өмнөх жил").className).toContain("sr-only");
    expect(screen.queryByRole("link", { name: "Өмнөх жил" })).toBeNull();
    expect(screen.getByRole("link", { name: "Дараах жил" })).toBeTruthy();
  });

  it("group heads only for named groups", () => {
    const { container, unmount } = renderTimeline(
      timeline({
        groups: [group({ bars: [bar({ title: "A", tip_title: "A" })], count: 3, label: "Хэлтэс А" })],
      }),
    );
    expect(screen.getByText("Хэлтэс А · 3")).toBeTruthy();
    unmount();

    const ungrouped = renderTimeline(timeline({ groups: [group({ label: "", count: 1 })] }));
    expect(ungrouped.container.textContent).not.toContain("· 1");
    expect(ungrouped.container.querySelectorAll("[data-bar]")).toHaveLength(1);
  });

  it("every note shows with its count", () => {
    renderTimeline(
      timeline({
        clipped: true,
        cap: 100,
        off_axis: 4,
        over_cap: 2,
        undated: 3,
        years: 5,
      }),
    );
    expect(screen.getByText("Огноогүй: 3")).toBeTruthy();
    expect(screen.getByText("Хүрээнээс гадуур: 4")).toBeTruthy();
    expect(screen.getByText("Хугацааны хүрээ 5 жилээр хязгаарлагдсан.")).toBeTruthy();
    expect(screen.getByText("Эхний 100-г харууллаа. Шүүлтүүрээр нарийвчилна уу.")).toBeTruthy();
  });

  it("empty timeline shows the empty text", () => {
    const { unmount } = renderTimeline(
      timeline({ total: 0, groups: [], first: "", last: "", ticks: [], today_pct: null }),
    );
    expect(screen.getByText("Өгөгдөл олдсонгүй")).toBeTruthy();
    expect(screen.queryByText(/Огноогүй/)).toBeNull();
    unmount();

    // Rows exist but none is drawn and none is off the axis: the empty text shows under the tools.
    renderTimeline(timeline({ groups: [group({ bars: [] , count: 2 })], first: "", last: "", ticks: [] }));
    expect(screen.getByText("Өгөгдөл олдсонгүй")).toBeTruthy();
  });
});
