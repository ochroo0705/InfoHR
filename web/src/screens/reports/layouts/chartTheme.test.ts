import { describe, expect, it } from "vitest";
import type { components } from "../../../api/schema";
import { buildOption, THEMES } from "./chartTheme";

type ChartOut = components["schemas"]["ReportChartOut"];

function chart(overrides: Partial<ChartOut> = {}): ChartOut {
  return {
    category_label: "Алба",
    hrefs: [],
    kind: "bar",
    kind_label: "Баганан",
    labels: ["A", "B"],
    masked: false,
    money: false,
    note: "",
    percent: false,
    rows: [],
    series: [],
    series_labels: [],
    value_label: "Тоо",
    values: [3, 5],
    ...overrides,
  };
}

type Params = { name?: string; seriesName?: string; value?: unknown; marker?: string };

function tooltipText(option: { tooltip: Record<string, unknown> }, params: Params | Params[]): string {
  const format = option.tooltip.formatter as (p: Params | Params[]) => string;
  return format(params);
}

describe("buildOption", () => {
  it("gives a bar, line, donut and stacked option from the payload", () => {
    const bar = buildOption(chart({ kind: "bar", values: [3, null] }), "light");
    expect(bar.series[0].type).toBe("bar");
    expect(bar.series[0].data).toEqual([3, null]);
    expect(bar.legend.show).toBe(false);
    expect(bar.xAxis?.type).toBe("category");

    const line = buildOption(chart({ kind: "line", values: [1, null] }), "light");
    expect(line.series[0].type).toBe("line");
    expect(line.series[0].data).toEqual([1, null]);

    const donut = buildOption(chart({ kind: "donut", values: [3, null] }), "light");
    expect(donut.series[0].type).toBe("pie");
    expect(donut.series[0].data).toEqual([
      { name: "A", value: 3 },
      { name: "B", value: null },
    ]);
    expect(donut.legend.show).toBe(true);

    const stacked = buildOption(
      chart({
        kind: "stacked",
        series: [
          { label: "X", values: [1, null] },
          { label: "Y", values: [2, 3] },
        ],
        series_labels: ["X", "Y"],
      }),
      "light",
    );
    expect(stacked.series).toHaveLength(2);
    expect(stacked.series[0]).toMatchObject({ type: "bar", name: "X", stack: "total", data: [1, null] });
    expect(stacked.series[1]).toMatchObject({ type: "bar", name: "Y", stack: "total", data: [2, 3] });
    expect(stacked.legend.show).toBe(true);
  });

  it("uses the dark palette for dark", () => {
    const light = buildOption(chart(), "light");
    const dark = buildOption(chart(), "dark");
    expect(dark.color).toEqual(THEMES.dark.series);
    expect(light.color).toEqual(THEMES.light.series);
    expect(dark.textStyle.color).toBe(THEMES.dark.text);
    expect(dark.series[0].itemStyle).toEqual({ color: THEMES.dark.accent });
    expect(dark.color).not.toEqual(light.color);
  });

  it("a long label list or a long label makes a horizontal bar", () => {
    const many = buildOption(chart({ labels: ["a", "b", "c", "d", "e", "f", "g"], values: [1, 2, 3, 4, 5, 6, 7] }), "light");
    expect(many.yAxis?.type).toBe("category");
    expect(many.xAxis?.type).toBe("value");
    expect(many.yAxis?.inverse).toBe(true);
    expect(many.series[0].label).toMatchObject({ position: "right" });

    const long = buildOption(chart({ labels: ["A", "Маш урт нэртэй ангилал тийм"] }), "light");
    expect(long.yAxis?.type).toBe("category");

    const short = buildOption(chart({ labels: ["A", "B", "C"], values: [1, 2, 3] }), "light");
    expect(short.xAxis?.type).toBe("category");
    expect(short.series[0].label).toMatchObject({ position: "top" });
  });

  it("tooltip and axis text contain no markup for a label with HTML", () => {
    const label = "<b>x</b> & <img src=x>";
    const option = buildOption(
      chart({
        kind: "stacked",
        labels: [label],
        values: [4],
        series: [{ label: "<i>s</i>", values: [4] }],
        series_labels: ["<i>s</i>"],
      }),
      "light",
    );
    const text = tooltipText(option, [{ name: label, seriesName: "<i>s</i>", value: 4, marker: "" }]);
    expect(text).not.toContain("<b>");
    expect(text).not.toContain("<img");
    expect(text).not.toContain("<i>");
    expect(text).toContain("&lt;b&gt;x&lt;/b&gt; &amp; &lt;img src=x&gt;");
    expect(text).toContain("4");
    // the axis label is drawn as plain text by the library, so it stays the raw string (this long label makes the bar horizontal)
    expect(option.yAxis?.data).toEqual([label]);

    const donut = buildOption(chart({ kind: "donut", labels: [label], values: [4] }), "light");
    const slice = tooltipText(donut, { name: label, value: 4, marker: "" });
    expect(slice).not.toContain("<b>");
  });

  it("shows a dash for a null value in the tooltip and axis", () => {
    const option = buildOption(chart({ values: [null, 5] }), "light");
    const text = tooltipText(option, [{ name: "A", seriesName: "", value: null, marker: "" }]);
    expect(text).toContain("—");
    const axisFormat = (option.yAxis?.axisLabel as { formatter: (v: number) => string }).formatter;
    expect(axisFormat(1234.56)).toBe("1,234.6");
  });

  it("adds the tugrik sign for money and a percent sign for percent", () => {
    const money = buildOption(chart({ money: true }), "light");
    const moneyText = tooltipText(money, [{ name: "A", value: 1234.4, marker: "" }]);
    expect(moneyText).toContain("1,234₮");
    const percent = buildOption(chart({ percent: true }), "light");
    const percentText = tooltipText(percent, [{ name: "A", value: 12.5, marker: "" }]);
    expect(percentText).toContain("12.5%");
  });
});
