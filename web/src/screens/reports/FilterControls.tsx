import type { ReactNode } from "react";
import type { components } from "../../api/schema";
import { Select, type SelectOption } from "../../widgets/Select";
import { DateField, NumberField } from "./CommitFields";

// The controls of the report filter bar (app/reports/templates/reports/_filters.html). Classes, labels and the «Бүх …»
// first entries are copied from the template. Each option list comes from the API (`bar.options`); the value shown
// comes from the address, which is the API's cleaned query (`table.query`), so a dirty address shows as cleaned.
// Names not listed here return null from renderFilterControl (the bar draws nothing for them). A change calls
// ctx.onChange(name, value); the bar turns that into the new address.

type ReportBarOut = components["schemas"]["ReportBarOut"];
type ReportFilterOptionsOut = components["schemas"]["ReportFilterOptionsOut"];
type ReportOptionOut = components["schemas"]["ReportOptionOut"];

export interface FilterControlContext {
  bar: ReportBarOut;
  query: string;
  onChange: (name: string, value: string) => void;
}

type Spec = {
  aria: string; // the template's aria-label (read through a sr-only label, as SystemLogFilters does)
  empty: string | null; // the «Бүх …» first entry; null when the template has none
  options: (o: ReportFilterOptionsOut) => ReportOptionOut[];
  plain?: boolean; // a plain name: never marked as applied (report_filters.js PLAIN)
  combo?: boolean; // the template has no data-search="off": a typing box from 8 entries (Select's own rule)
  current?: (ctx: FilterControlContext) => string; // the value the bar shows when it is not read from the address
};

const MODES: ReportOptionOut[] = [
  { value: "", label: "Нэгтгэсэн: нэг ажилтан — нэг мөр" },
  { value: "children", label: "Хүүхэд бүрээр: нэг хүүхэд — нэг мөр" },
];

const QUARTERS: ReportOptionOut[] = [
  { value: "1", label: "1-р улирал" },
  { value: "2", label: "2-р улирал" },
  { value: "3", label: "3-р улирал" },
  { value: "4", label: "4-р улирал" },
];

export const SELECTS: Record<string, Spec> = {
  state: { aria: "Төлөв", empty: null, options: (o) => o.states },
  emptype: { aria: "Ажилтны төрөл", empty: "Бүх төрөл", options: (o) => o.emptypes },
  branch: { aria: "Салбар", empty: "Бүх салбар", options: (o) => o.branches },
  department: { aria: "Хэлтэс", empty: "Бүх хэлтэс", options: (o) => o.departments },
  position: { aria: "Албан тушаал", empty: "Бүх албан тушаал", options: (o) => o.positions },
  gender: { aria: "Хүйс", empty: "Бүх хүйс", options: (o) => o.genders },
  change: { aria: "Өөрчлөлт", empty: "Бүх өөрчлөлт", options: (o) => o.change_kinds },
  reason: { aria: "Шалтгаан", empty: "Бүх шалтгаан", options: (o) => o.reasons },
  order_type: { aria: "Тушаалын төрөл", empty: "Бүх төрөл", options: (o) => o.order_types },
  discipline: { aria: "Шийтгэлийн төрөл", empty: "Бүх төрөл", options: (o) => o.discipline_types },
  leave_type: { aria: "Төрөл", empty: "Бүх төрөл", options: (o) => o.leave_types },
  leave_state: { aria: "Төлөв", empty: "Бүх төлөв", options: (o) => o.leave_states },
  absence_type: { aria: "Төрөл", empty: "Бүх төрөл", options: (o) => o.absence_types },
  attribute: { aria: "Шинж", empty: null, options: (o) => o.attributes, plain: true },
  contact_type: { aria: "Холбоо барих төрөл", empty: "Бүх төрөл", options: (o) => o.contact_types },
  tr_type: { aria: "Хэлбэр", empty: "Бүх хэлбэр", options: (o) => o.training_types },
  present_type: { aria: "Бэлгийн төрөл", empty: "Бүх бэлэг", options: (o) => o.present_types },
  employee: { aria: "Ажилтан", empty: "Бүх ажилтан", options: (o) => o.people, combo: true },
  mode: { aria: "Горим", empty: null, options: () => MODES },
  quarter: {
    aria: "Улирал",
    empty: null,
    options: () => QUARTERS,
    plain: true,
    current: (ctx) => String(ctx.bar.options.quarter ?? ""),
  },
};

// The class lists of the template's select; the applied variant paints it violet (the React port has no report-filters
// stylesheet, so the classes are swapped here, as input.css does for data-applied).
const SELECT_CLASS = "w-full rounded-lg border border-slate-300 bg-surface py-2 pl-3 pr-8 text-sm";
const SELECT_APPLIED_CLASS = "w-full rounded-lg border border-violet-500 bg-violet-50 py-2 pl-3 pr-8 text-sm font-medium text-violet-900";

// The holders of the range controls (the date pair, the age pair, the as-of box) and their applied variant.
const HOLDER_CLASS = "flex items-center gap-1 rounded-lg border border-slate-300 bg-surface px-3";
const HOLDER_APPLIED = "border-violet-500 bg-violet-50 text-violet-900 font-medium";
const BARE_INPUT_CLASS = "w-full min-w-0 border-0 bg-transparent py-2 text-sm focus:outline-none";
const BOX_INPUT_CLASS = "w-full rounded-lg border border-slate-300 bg-surface px-3 py-2 text-sm";

function holderClass(base: string, applied: boolean): string {
  return applied ? base.replace("border-slate-300 bg-surface", HOLDER_APPLIED) : base;
}

type SelectState = {
  name: string;
  list: SelectOption[];
  value: string;
  disabled: boolean;
  applied: boolean;
  spec: Spec;
};

// The state of one select: its options, the value the address gives it, and whether it is applied. The default is the
// first entry of the list (the «Бүх …» entry, or the first real option), as in report_filters.js.
function selectState(name: string, ctx: FilterControlContext): SelectState | null {
  const spec = SELECTS[name];
  if (!spec) return null;
  const real = spec.options(ctx.bar.options);
  const list: SelectOption[] = [
    ...(spec.empty === null ? [] : [{ value: "", label: spec.empty }]),
    ...real.map((o) => ({ value: o.value, label: o.label })),
  ];
  const params = new URLSearchParams(ctx.query);
  const fallback = list.length > 0 ? list[0].value : "";
  const value = spec.current ? spec.current(ctx) : (params.get(name) ?? fallback);
  // The state filter is ignored for a type with no working state: its control is disabled (not submitted), as the template.
  const emptype = params.get("emptype") ?? "";
  const disabled = name === "state" && ctx.bar.options.no_working_state.some((o) => o.value === emptype);
  const applied = !disabled && !spec.plain && list.length > 0 && value !== list[0].value;
  return { name, list, value, disabled, applied, spec };
}

function selectNode(state: SelectState, onChange: (value: string) => void): ReactNode {
  const id = `report-filter-${state.name}`;
  return (
    <div data-filter={state.name} data-applied={state.applied ? "" : undefined} className="min-w-0">
      <label htmlFor={id} className="sr-only">
        {state.spec.aria}
      </label>
      <Select
        id={id}
        name={state.name}
        value={state.value}
        options={state.list}
        search={state.spec.combo ? undefined : false}
        disabled={state.disabled}
        className={state.applied ? SELECT_APPLIED_CLASS : SELECT_CLASS}
        onChange={onChange}
      />
    </div>
  );
}

// The address's value of a text-like parameter, trimmed ("" when absent).
function textOf(query: string, name: string): string {
  return (new URLSearchParams(query).get(name) ?? "").trim();
}

// The period's default span is this calendar year (report_filters.js: from = 1 January, to = 31 December).
function periodApplied(ctx: FilterControlContext): boolean {
  const year = new Date().getFullYear();
  const { period_from: from, period_to: to } = ctx.bar.options;
  return (from !== "" && from !== `${year}-01-01`) || (to !== "" && to !== `${year}-12-31`);
}

// True when the control holds a value other than its default, and is not disabled (report_filters.js `applied`).
export function filterControlApplied(name: string, ctx: FilterControlContext): boolean {
  switch (name) {
    case "period":
      return periodApplied(ctx);
    case "as_of":
      return textOf(ctx.query, "as_of") !== "";
    case "age_range":
      return textOf(ctx.query, "age_from") !== "" || textOf(ctx.query, "age_to") !== "";
    default:
      return selectState(name, ctx)?.applied ?? false;
  }
}

// The grid cell a filter takes in the bar: the period spans two columns (_filters.html).
export function filterSpan(name: string): string {
  return name === "period" ? "sm:col-span-2" : "";
}

function PeriodControl({ ctx }: { ctx: FilterControlContext }) {
  const { period_from: from, period_to: to } = ctx.bar.options;
  const applied = periodApplied(ctx);
  return (
    <div data-filter="period" data-applied={applied ? "" : undefined} className={holderClass(HOLDER_CLASS, applied)}>
      <span className="shrink-0 text-slate-500">Хугацаа</span>
      <DateField
        name="from"
        value={from}
        syncKey={ctx.query}
        ariaLabel="Эхлэх огноо"
        placeholder="Эхлэх"
        className={BARE_INPUT_CLASS}
        onCommit={(v) => ctx.onChange("from", v)}
      />
      <span className="text-slate-500">–</span>
      <DateField
        name="to"
        value={to}
        syncKey={ctx.query}
        ariaLabel="Дуусах огноо"
        placeholder="Дуусах"
        className={BARE_INPUT_CLASS}
        onCommit={(v) => ctx.onChange("to", v)}
      />
    </div>
  );
}

function AsOfControl({ ctx }: { ctx: FilterControlContext }) {
  const value = textOf(ctx.query, "as_of");
  const applied = value !== "";
  return (
    <div
      data-filter="as_of"
      data-applied={applied ? "" : undefined}
      className={holderClass("flex items-center gap-2 rounded-lg border border-slate-300 bg-surface pl-3 focus-within:border-violet-500", applied)}
    >
      <span className="shrink-0 text-slate-500">Огноо</span>
      <DateField
        name="as_of"
        value={value}
        syncKey={ctx.query}
        ariaLabel="Огноо"
        placeholder="Өнөөдөр"
        className="w-full border-0 bg-transparent px-1 py-2 text-sm focus:outline-none"
        onCommit={(v) => ctx.onChange("as_of", v)}
      />
    </div>
  );
}

function AgeControl({ ctx }: { ctx: FilterControlContext }) {
  const low = textOf(ctx.query, "age_from");
  const high = textOf(ctx.query, "age_to");
  const applied = low !== "" || high !== "";
  return (
    <div data-filter="age_range" data-applied={applied ? "" : undefined} className={holderClass(HOLDER_CLASS, applied)}>
      <span className="shrink-0 text-slate-500">Нас</span>
      <NumberField
        name="age_from"
        value={low}
        syncKey={ctx.query}
        ariaLabel="Доод нас"
        placeholder="Доод"
        min={0}
        max={120}
        className={BARE_INPUT_CLASS}
        onCommit={(v) => ctx.onChange("age_from", v)}
      />
      <span className="text-slate-500">–</span>
      <NumberField
        name="age_to"
        value={high}
        syncKey={ctx.query}
        ariaLabel="Дээд нас"
        placeholder="Дээд"
        min={0}
        max={120}
        className={BARE_INPUT_CLASS}
        onCommit={(v) => ctx.onChange("age_to", v)}
      />
    </div>
  );
}

// The survey year is a plain name: it shows the bar's year and is never marked applied.
function YearControl({ ctx }: { ctx: FilterControlContext }) {
  const year = ctx.bar.options.year;
  return (
    <NumberField
      name="year"
      dataFilter="year"
      value={year === null ? "" : String(year)}
      syncKey={ctx.query}
      ariaLabel="Он"
      min={1990}
      max={2100}
      className={BOX_INPUT_CLASS}
      onCommit={(v) => ctx.onChange("year", v)}
    />
  );
}

// The select, date pair, age pair or year box for one filter name of the bar, or null when this module does not draw
// that name. The wrapper carries data-filter and, when applied, data-applied (the template put them on the select
// itself; the shared Select widget takes no extra attributes).
export function renderFilterControl(name: string, ctx: FilterControlContext): ReactNode | null {
  switch (name) {
    case "period":
      return <PeriodControl ctx={ctx} />;
    case "as_of":
      return <AsOfControl ctx={ctx} />;
    case "age_range":
      return <AgeControl ctx={ctx} />;
    case "year":
      return <YearControl ctx={ctx} />;
    default: {
      const state = selectState(name, ctx);
      if (!state) return null;
      return selectNode(state, (value) => ctx.onChange(name, value));
    }
  }
}

// The «Бүлэглэх» select (_filters.html): drawn only when the report offers grouping choices, outside the bar's items.
// Its value is the address's group; the group text, when set, is the current choice's own label.
export function renderGroupControl(ctx: FilterControlContext): ReactNode | null {
  const choices = ctx.bar.options.group_choices;
  if (choices.length === 0) return null;
  const group = textOf(ctx.query, "group");
  const list: SelectOption[] = [{ value: "", label: "Бүлэглэхгүй" }];
  // The template lists the current grouping first with its text; a choice with the same key is already in the list.
  if (group !== "" && ctx.bar.options.group_text !== "" && !choices.some((c) => c.value === group)) {
    list.push({ value: group, label: ctx.bar.options.group_text });
  }
  list.push(...choices.map((c) => ({ value: c.value, label: c.label })));
  const applied = group !== "";
  const id = "report-filter-group";
  return (
    <div data-applied={applied ? "" : undefined} className="min-w-0">
      <label htmlFor={id} className="sr-only">
        Бүлэглэх
      </label>
      <Select
        id={id}
        name="group"
        value={group}
        options={list}
        search={false}
        className={applied ? SELECT_APPLIED_CLASS : SELECT_CLASS}
        onChange={(value) => ctx.onChange("group", value)}
      />
    </div>
  );
}

// True when the group select holds a grouping (it counts for «Цэвэрлэх», as every select does).
export function groupControlApplied(ctx: FilterControlContext): boolean {
  return ctx.bar.options.group_choices.length > 0 && textOf(ctx.query, "group") !== "";
}
