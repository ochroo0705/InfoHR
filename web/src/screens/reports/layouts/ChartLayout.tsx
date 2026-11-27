import { useEffect, useRef, useState } from "react";
import { TLink } from "../../../lib/viewTransition";
import {
  buildOption,
  type ChartOut,
  type ChartTheme,
  horizontalHeight,
  isHorizontal,
} from "./chartTheme";

// The chart layout (app/reports/templates/reports/layouts/chart.html, static/js/charts.js, UI_RULES §4b). The drawing is
// ECharts, loaded on first use as a separate lazy chunk (the dynamic imports below). The numbers are always shown
// under it as a plain table, so the figures stay readable when the drawing fails. Every label is finished text.

export interface ChartLayoutProps {
  chart: ChartOut;
}

type EChartsCore = typeof import("echarts/core");
type ChartInstance = ReturnType<EChartsCore["init"]>;
// The option is built by buildOption (chartTheme.ts, tested there); its plain shape is not ECharts' typed option.
type EChartsOption = Parameters<ChartInstance["setOption"]>[0];

const LINK_CLASS = "text-violet-700 hover:underline";
const LINK_TITLE = "Эдгээр мөрийг хүснэгтээр харах";
const FAILED_TEXT = "График ачаалж чадсангүй. Доорх хүснэгтээс харна уу.";

// The library is loaded once; a failed load is forgotten, so a later chart may try again.
let library: Promise<EChartsCore> | null = null;

export function loadECharts(): Promise<EChartsCore> {
  if (library === null) {
    const pending = Promise.all([
      import("echarts/core"),
      import("echarts/charts"),
      import("echarts/components"),
      import("echarts/renderers"),
    ]).then(([core, charts, components, renderers]) => {
      core.use([
        charts.BarChart,
        charts.LineChart,
        charts.PieChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        components.ToolboxComponent,
        renderers.SVGRenderer,
      ]);
      return core;
    });
    library = pending;
    pending.catch(() => {
      if (library === pending) library = null;
    });
  }
  return library;
}

// Tests only: forgets the loaded library so the next chart loads it again.
export function resetChartLibraryForTests(): void {
  library = null;
}

function readTheme(): ChartTheme {
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "light";
}

export function ChartLayout({ chart }: ChartLayoutProps) {
  if (chart.rows.length === 0) {
    return (
      <p className="mt-4 py-6 text-center text-sm text-slate-400">
        Өгөгдөл олдсонгүй
      </p>
    );
  }
  return (
    <>
      <ChartFigure chart={chart} />
      <ChartTable chart={chart} />
      {chart.masked ? (
        <p className="mt-2 text-sm text-slate-500">{chart.note}</p>
      ) : null}
    </>
  );
}

function ChartFigure({ chart }: { chart: ChartOut }) {
  const ref = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<ChartTheme>(readTheme);
  const [failed, setFailed] = useState(false);
  const linked = chart.hrefs.some((href) => href !== "");
  const horizontal = isHorizontal(chart);

  // A theme change (data-theme on <html>) gives a new theme, and the effect below redraws with its colours.
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let active = true;
    let instance: ChartInstance | null = null;
    let resizer: ResizeObserver | null = null;
    setFailed(false);
    loadECharts()
      .then((echarts) => {
        if (!active) return;
        // svg, as charts.js draws: the labels are text nodes, not pixels, and the figure prints and copies like the page.
        instance = echarts.init(el, undefined, { renderer: "svg" });
        instance.setOption(
          buildOption(chart, theme) as unknown as EChartsOption,
        );
        if (linked) {
          instance.on("click", (params: { dataIndex?: number }) => {
            const href =
              typeof params.dataIndex === "number"
                ? chart.hrefs[params.dataIndex]
                : undefined;
            if (href) window.location.href = href;
          });
        }
        if (typeof ResizeObserver !== "undefined") {
          resizer = new ResizeObserver(() => instance?.resize());
          resizer.observe(el);
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      resizer?.disconnect();
      instance?.dispose();
    };
  }, [chart, theme, linked]);

  return (
    <>
      <div className="mt-4">
        <div
          ref={ref}
          role="img"
          aria-label={`${chart.kind_label}: ${chart.value_label}`}
          hidden={failed}
          className={`h-80 w-full${linked ? " cursor-pointer" : ""}`}
          style={
            horizontal
              ? { height: `${horizontalHeight(chart.labels.length)}px` }
              : undefined
          }
        />
        {failed ? (
          <p
            data-chart-failed
            className="mb-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-800"
          >
            {FAILED_TEXT}
          </p>
        ) : null}
      </div>
    </>
  );
}

function ChartTable({ chart }: { chart: ChartOut }) {
  const hasSeries = chart.series_labels.length > 0;
  return (
    <div className="ptable mt-4 overflow-x-auto">
      <table>
        <thead>
          <tr>
            <th scope="col">{chart.category_label || "Ангилал"}</th>
            {chart.series_labels.map((label, index) => (
              <th key={index} scope="col" className="text-right">
                {label}
              </th>
            ))}
            <th scope="col" className="text-right">
              {hasSeries ? "Нийт" : chart.value_label}
            </th>
          </tr>
        </thead>
        <tbody>
          {chart.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              <td>
                {row.href ? (
                  <TLink
                    to={row.href}
                    className={LINK_CLASS}
                    title={LINK_TITLE}
                  >
                    {row.label}
                  </TLink>
                ) : (
                  row.label
                )}
              </td>
              {row.cells.map((cell, cellIndex) => (
                <td key={cellIndex} className="text-right">
                  {cell}
                </td>
              ))}
              <td className="text-right">{row.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
