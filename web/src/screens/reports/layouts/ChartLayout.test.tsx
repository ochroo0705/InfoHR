// The harness is imported first: it stubs fetch before ../../../api/client (and so the reports api) load.
import "../../../api/testSupport";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../../api/schema";
import { THEMES, type ChartOption } from "./chartTheme";
import { ChartLayout, resetChartLibraryForTests } from "./ChartLayout";

// The ECharts modules are replaced, so no canvas is needed. The loader's use() and the instance are spies.
const mocks = vi.hoisted(() => {
  const instance = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  return { instance, init: vi.fn(() => instance), use: vi.fn() };
});

vi.mock("echarts/core", () => ({ init: mocks.init, use: mocks.use }));
vi.mock("echarts/charts", () => ({ BarChart: {}, LineChart: {}, PieChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  ToolboxComponent: {},
}));
vi.mock("echarts/renderers", () => ({ SVGRenderer: {} }));

type ChartOut = components["schemas"]["ReportChartOut"];

function chart(overrides: Partial<ChartOut> = {}): ChartOut {
  return {
    category_label: "Алба",
    hrefs: [],
    kind: "bar",
    kind_label: "Баганан",
    labels: ["Санхүү", "Ажил"],
    masked: false,
    money: false,
    note: "",
    percent: false,
    rows: [
      { label: "Санхүү", href: "/reports/staff/?lby=dept&lby_v=fin", cells: [], total: "3,000₮" },
      { label: "Ажил", href: "", cells: [], total: "1,000₮" },
    ],
    series: [],
    series_labels: [],
    value_label: "Нийлбэр",
    values: [3000, 1000],
    ...overrides,
  };
}

function renderChart(value: ChartOut) {
  return render(
    <MemoryRouter>
      <ChartLayout chart={value} />
    </MemoryRouter>,
  );
}

const FAILED_TEXT = "График ачаалж чадсангүй. Доорх хүснэгтээс харна уу.";

beforeEach(() => {
  vi.clearAllMocks();
  resetChartLibraryForTests();
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
});

describe("ChartLayout", () => {
  it("table rows link or are text and totals show", async () => {
    const { container, getByRole, getByText, queryByRole } = renderChart(
      chart({
        series_labels: ["Эрэгтэй", "Эмэгтэй"],
        rows: [
          {
            label: "Санхүү",
            href: "/reports/staff/?lby=dept&lby_v=fin",
            cells: ["2,000₮", "1,000₮"],
            total: "3,000₮",
          },
          { label: "Ажил", href: "", cells: ["500₮", "500₮"], total: "1,000₮" },
        ],
      }),
    );
    await waitFor(() => expect(mocks.init).toHaveBeenCalled());

    const link = getByRole("link", { name: "Санхүү" });
    expect(link.getAttribute("href")).toBe("/reports/staff/?lby=dept&lby_v=fin");
    expect(link.getAttribute("title")).toBe("Эдгээр мөрийг хүснэгтээр харах");
    expect(queryByRole("link", { name: "Ажил" })).toBeNull();
    expect(getByText("Ажил")).toBeTruthy();
    expect(getByText("2,000₮")).toBeTruthy();
    expect(getByText("3,000₮")).toBeTruthy();
    expect(getByText("Нийт")).toBeTruthy();
    expect(getByText("Эрэгтэй")).toBeTruthy();
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("the failure note shows when the library fails to load", async () => {
    mocks.use.mockImplementationOnce(() => {
      throw new Error("load failed");
    });
    const { container, getByText } = renderChart(chart());

    await waitFor(() => expect(container.querySelector("[data-chart-failed]")).not.toBeNull());
    expect(getByText(FAILED_TEXT).className).toContain("bg-amber-50");
    expect(mocks.init).not.toHaveBeenCalled();
    // the numbers stay under the failed drawing
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("masked note shows", async () => {
    const note = "3-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»).";
    const { getByText } = renderChart(chart({ masked: true, note }));
    await waitFor(() => expect(mocks.init).toHaveBeenCalled());

    const shown = getByText(note);
    expect(shown.className).toContain("mt-2 text-sm text-slate-500");
  });

  it("empty chart shows the empty text", () => {
    const { container, getByText } = renderChart(chart({ rows: [], labels: [], values: [] }));

    const empty = getByText("Өгөгдөл олдсонгүй");
    expect(empty.className).toContain("mt-4 py-6 text-center text-sm text-slate-400");
    expect(container.querySelector("table")).toBeNull();
    expect(container.querySelector("[role='img']")).toBeNull();
    expect(mocks.init).not.toHaveBeenCalled();
  });

  it("the chart is disposed on unmount", async () => {
    const { unmount } = renderChart(chart());
    await waitFor(() => expect(mocks.instance.setOption).toHaveBeenCalled());

    unmount();
    expect(mocks.instance.dispose).toHaveBeenCalled();
  });

  it("the chart is drawn with the svg renderer, as charts.js does", async () => {
    renderChart(chart());
    await waitFor(() => expect(mocks.init).toHaveBeenCalled());

    const [, , opts] = mocks.init.mock.calls[0] as unknown as [unknown, unknown, { renderer: string }];
    expect(opts.renderer).toBe("svg");
  });

  it("a data-theme change redraws", async () => {
    renderChart(chart());
    await waitFor(() => expect(mocks.init).toHaveBeenCalledTimes(1));

    document.documentElement.setAttribute("data-theme", "dark");

    await waitFor(() => expect(mocks.init).toHaveBeenCalledTimes(2));
    const calls = mocks.instance.setOption.mock.calls;
    const option = calls[calls.length - 1][0] as ChartOption;
    expect(option.textStyle.color).toBe(THEMES.dark.text);
    expect(option.color).toEqual(THEMES.dark.series);
    expect(mocks.instance.dispose).toHaveBeenCalled();
  });
});
