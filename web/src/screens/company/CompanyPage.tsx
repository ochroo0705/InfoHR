import { useEffect } from "react";
import { useCompany, type CompanyPageOut } from "../../api/company";
import { Forbidden, NotFound } from "../../routes/ErrorPage";

// Port of app/employees/templates/employees/company.html and _company.html: the company figures page at
// /employees/company/. Classes, element order, SVG attributes and Mongolian text are copied from the templates. Every
// figure, heading, label and chart geometry comes from the API (CompanyPageOut); the page computes nothing.
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";

type LineOut = CompanyPageOut["headcount"];
type BarsOut = CompanyPageOut["departments"];

export function CompanyPage() {
  const company = useCompany();
  const data = company.data;

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    if (!data) return;
    const previous = document.title;
    document.title = data.title + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [data]);

  // The data check comes first: a failed background refetch keeps the page on screen (see the alert below).
  if (!data) {
    if (company.error) {
      const status = (company.error as { status?: number }).status;
      if (status === 403) return <Forbidden />;
      if (status === 404) return <NotFound />;
      return <p className="text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p>;
    }
    // Loading shows nothing here: the shell's loading bar is the only feedback, as on the Django page.
    return null;
  }

  return (
    <>
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">{data.title}</h1>
        <span className="ml-auto text-sm text-slate-500">{data.today}</span>
      </div>
      {company.error ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      <section className="card-soft mb-5 p-4" data-company aria-labelledby="company-title">
        <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 id="company-title" className="sec-title">
            {data.title}
          </h2>
          {data.partial_scope ? (
            <span className="rounded-full bg-violet-50 px-2 text-xs font-medium text-violet-700" data-company-scope>
              {data.scope_label}
            </span>
          ) : null}
          <span className="ml-auto flex gap-3 text-sm text-slate-700">
            <span>{data.hires_text}</span>
            <span>{data.leavers_text}</span>
          </span>
        </div>
        {data.partial_history ? <p className="mb-2 text-xs text-slate-500">{data.history_note}</p> : null}
        <div className="mt-3 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <LineHeading line={data.headcount} />
            <LineChart chart={data.headcount} />
          </div>
          <div>
            <LineHeading line={data.turnover} />
            <LineChart chart={data.turnover} />
            <p className="mt-1 text-xs text-slate-400">{data.turnover_note}</p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-600">{data.departments.title}</h3>
            <BarChart chart={data.departments} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-600">{data.tenure.title}</h3>
            <BarChart chart={data.tenure} />
          </div>
        </div>
      </section>
    </>
  );
}

// The chart's heading: its title and the last month's figure (empty when there is none).
function LineHeading({ line }: { line: LineOut }) {
  return (
    <h3 className="mb-1 flex items-baseline justify-between gap-2 text-xs font-medium text-slate-600">
      <span>{line.title}</span>
      <span className="text-sm font-semibold tabular-nums text-slate-800">{line.head}</span>
    </h3>
  );
}

// _chart_line.html: one polyline per unbroken run, the last point's dot, and the first and last month labels.
function LineChart({ chart }: { chart: LineOut }) {
  if (chart.no_data) {
    return <p className="text-xs text-slate-400">{chart.no_data_text}</p>;
  }
  return (
    <figure className="m-0">
      <svg
        viewBox={chart.view_box}
        role="img"
        aria-label={chart.label}
        className="h-16 w-full overflow-visible"
        preserveAspectRatio="none"
        data-line-chart
      >
        {chart.polylines.map((run, i) => (
          <polyline
            key={i}
            points={run}
            fill="none"
            className="stroke-violet-600"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {chart.last_dot ? (
          <circle cx={chart.last_dot.cx} cy={chart.last_dot.cy} r={3} className="fill-violet-600" />
        ) : null}
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-slate-500">
        <span>{chart.first_label}</span>
        <span>{chart.last_label}</span>
      </figcaption>
    </figure>
  );
}

// _chart_bars.html: one row per bar, the label, a track filled to the bar's width, and the value.
function BarChart({ chart }: { chart: BarsOut }) {
  if (chart.no_data) {
    return <p className="text-xs text-slate-400">{chart.no_data_text}</p>;
  }
  return (
    <ul className="m-0 list-none space-y-1.5 p-0" role="img" aria-label={chart.summary} data-bar-chart>
      {chart.bars.map((bar, i) => (
        <li
          key={i}
          className="grid grid-cols-[minmax(0,8rem)_1fr_2rem] items-center gap-2 text-xs text-slate-500"
        >
          <span className="truncate" title={bar.label}>
            {bar.label}
          </span>
          <span className="h-2 rounded bg-slate-100">
            <span className="block h-2 rounded bg-violet-500" style={{ width: bar.width }} />
          </span>
          <span className="text-right tabular-nums">{bar.value}</span>
        </li>
      ))}
    </ul>
  );
}
