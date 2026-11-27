import type { components } from "../../../api/schema";

// The chart option of the report chart (app/static/js/charts.js, toOption, formatterFor, isHorizontal, horizontalHeight).
// This file is pure: it imports no ECharts code, so the library stays in its own lazy chunk (ChartLayout loads it).
// ECharts cannot read oklch() colours, so the palettes are hex constants, one set per theme.

export type ChartOut = components["schemas"]["ReportChartOut"];
export type ChartTheme = "light" | "dark";

export interface ChartPalette {
  accent: string;
  text: string;
  grid: string;
  surface: string;
  series: string[];
}

export const THEMES: Record<ChartTheme, ChartPalette> = {
  light: {
    accent: "#c0392b",
    text: "#34495e",
    grid: "#d5dcdf",
    surface: "#ffffff",
    series: ["#dc2626", "#f59e0b", "#16a34a", "#3b82f6", "#5f6b6d", "#bdc6c8", "#8a9598"],
  },
  dark: {
    accent: "#d9574a",
    text: "#d5dcdf",
    grid: "#2f4357",
    surface: "#1e2b38",
    series: ["#ef4444", "#fbbf24", "#22c55e", "#60a5fa", "#95a5a6", "#3b5167", "#6c7e8c"],
  },
};

// A value that is not a number shows as a dash (charts.js NOT_A_NUMBER).
export const NOT_A_NUMBER = "—";

// Thousands with commas, one decimal at most: 1234 gives "1,234".
export function formatNumber(value: number): string {
  const parts = String(Math.round(value * 10) / 10).split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return parts.join(".");
}

function finite(value: number | null): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// The value formatter of the chart: money gets the tugrik sign, a percent gets «%», otherwise a plain number.
export function formatterFor(chart: Pick<ChartOut, "money" | "percent">): (value: number | null) => string {
  if (chart.money) {
    return (value) => (finite(value) ? formatNumber(Math.round(value)) + "₮" : NOT_A_NUMBER);
  }
  if (chart.percent) {
    return (value) => (finite(value) ? formatNumber(value) + "%" : NOT_A_NUMBER);
  }
  return (value) => (finite(value) ? formatNumber(value) : NOT_A_NUMBER);
}

// A bar or stacked chart is horizontal with more than 6 categories or a label longer than 14 characters; hbar always is.
export function isHorizontal(chart: Pick<ChartOut, "kind" | "labels">): boolean {
  if (chart.kind === "hbar") return true;
  const longest = chart.labels.reduce((m, label) => Math.max(m, String(label).length), 0);
  return (chart.kind === "bar" || chart.kind === "stacked") && (chart.labels.length > 6 || longest > 14);
}

// 32 px a bar and 60 px for the axis, at least 320 and at most 1200 px.
export function horizontalHeight(count: number): number {
  return Math.min(1200, Math.max(320, count * 32 + 60));
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

// Text that goes into tooltip HTML: every label and value is escaped, so a category name is never markup.
export function escapeText(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

interface TipParam {
  name?: string;
  seriesName?: string;
  value?: unknown;
  marker?: string;
}

function tipValue(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

// Every string that reaches the tooltip HTML goes through escapeText. This is required by the echarts 5.6.0 advisory
// GHSA-fgmj-fm8m-jvvx (the library's tooltip renders its text as HTML); the fix is a major bump, so 5.6.0 stays pinned.
function tooltipFormatter(kind: string, fmt: (value: number | null) => string) {
  return (params: TipParam | TipParam[]): string => {
    const list = Array.isArray(params) ? params : [params];
    if (kind === "donut" || kind === "pie") {
      const p = list[0];
      return `${p.marker ?? ""}${escapeText(p.name ?? "")}: ${escapeText(fmt(tipValue(p.value)))}`;
    }
    const head = list.length > 0 && list[0].name ? `${escapeText(list[0].name)}<br/>` : "";
    const lines = list.map((p) => {
      const name = p.seriesName ? `${escapeText(p.seriesName)}: ` : "";
      return `${p.marker ?? ""}${name}${escapeText(fmt(tipValue(p.value)))}`;
    });
    return head + lines.join("<br/>");
  };
}

export interface ChartOption {
  backgroundColor: string;
  animation: boolean;
  animationDuration: number;
  color: string[];
  textStyle: { color: string };
  toolbox: Record<string, unknown>;
  tooltip: Record<string, unknown>;
  legend: Record<string, unknown>;
  grid?: Record<string, unknown>;
  xAxis?: Record<string, unknown>;
  yAxis?: Record<string, unknown>;
  series: Array<Record<string, unknown>>;
}

// The ECharts option of one chart, for the given theme.
export function buildOption(chart: ChartOut, theme: ChartTheme): ChartOption {
  const t = THEMES[theme];
  const fmt = formatterFor(chart);
  const labels = chart.labels.map((l) => String(l));
  const base = {
    backgroundColor: "transparent",
    animation: true,
    animationDuration: 600,
    color: t.series,
    textStyle: { color: t.text },
    toolbox: { right: 0, feature: { saveAsImage: {} } },
  };

  if (chart.kind === "donut" || chart.kind === "pie") {
    return {
      ...base,
      tooltip: { trigger: "item", formatter: tooltipFormatter(chart.kind, fmt) },
      legend: { show: true, bottom: 0, textStyle: { color: t.text } },
      series: [
        {
          type: "pie",
          radius: chart.kind === "donut" ? ["55%", "80%"] : "75%",
          center: ["50%", "45%"],
          label: { show: true, formatter: "{d}%", color: "#ffffff" },
          itemStyle: { borderColor: t.surface, borderWidth: 2 },
          data: labels.map((name, i) => ({ name, value: chart.values[i] ?? null })),
        },
      ],
    };
  }

  const horizontal = isHorizontal(chart);
  const stacked = chart.kind === "stacked" && Array.isArray(chart.series) && chart.series.length > 0;
  const isLine = chart.kind === "line" || chart.kind === "area";
  let series: Array<Record<string, unknown>>;
  if (stacked) {
    series = chart.series.map((s, i) => ({
      type: "bar",
      name: String(s.label),
      stack: "total",
      data: s.values,
      itemStyle: { color: t.series[i % t.series.length] },
    }));
  } else if (isLine) {
    series = [
      {
        type: "line",
        data: chart.values,
        symbol: "circle",
        symbolSize: 8,
        lineStyle: { color: t.accent, width: 2 },
        itemStyle: { color: t.accent },
      },
    ];
    if (chart.kind === "area") series[0].areaStyle = { color: t.accent, opacity: 0.25 };
  } else {
    series = [
      {
        type: "bar",
        data: chart.values,
        barMaxWidth: 48,
        itemStyle: { color: t.accent },
        label: {
          show: true,
          color: t.text,
          position: horizontal ? "right" : "top",
          formatter: (p: { value?: unknown }) => fmt(tipValue(p.value)),
        },
      },
    ];
  }

  const category: Record<string, unknown> = {
    type: "category",
    data: labels,
    axisLabel: { color: t.text, rotate: horizontal ? 0 : 30 },
    axisLine: { lineStyle: { color: t.grid } },
  };
  const value: Record<string, unknown> = {
    type: "value",
    axisLabel: { color: t.text, formatter: (v: number) => fmt(tipValue(v)) },
    splitLine: { lineStyle: { color: t.grid } },
  };
  const option: ChartOption = {
    ...base,
    tooltip: { trigger: "axis", formatter: tooltipFormatter(chart.kind, fmt) },
    legend: { show: stacked, bottom: 0, textStyle: { color: t.text } },
    grid: { left: 8, right: 24, top: 40, bottom: stacked ? 72 : 40, containLabel: true },
    series,
  };
  if (horizontal) {
    category.inverse = true; // the first category is at the top, as the table has it
    option.xAxis = value;
    option.yAxis = category;
  } else {
    option.xAxis = category;
    option.yAxis = value;
  }
  return option;
}
