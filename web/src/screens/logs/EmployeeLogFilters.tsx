import type { KeyboardEvent, FormEvent } from "react";
import type {
  EmployeeLogParams,
  LogChipOut,
  LogEmployeeOptionsOut,
  LogEmployeeQueryOut,
} from "../../api/logs";
import { AppLink } from "../../lib/AppLink";
import { Select, type SelectOption } from "../../widgets/Select";
import { CheckMenu } from "./CheckMenu";
import { searchFromEmployeeParams } from "./logParams";
import { useDebouncedField } from "./useDebouncedField";

// The filter bar of the employee log (app/logs/templates/logs/employee.html, `form#log-filters`). Classes, placeholders
// and labels are copied from the template. `params` is the page's address. `settled` is true only when the rows on
// screen answer exactly `params`; then the selects, the kinds, the sort, the system box and the dates show the server's
// echo (`query`), so a junk value shows as cleaned or as its «all» entry. Until then they show the address.
//
// The four text boxes (q, emp, by, field) follow the address, never the echo: they show and send what was typed, 300 ms
// after the last keystroke, or at once on Enter (the focused box only). No client-side cleaning is done: the server cleans
// the text (logs.params.clean_text, then words()), and the Excel link and the address take the server's cleaned `address`.
// The other controls call onChange at once. Every call sends the whole address (`params` plus the one change), built
// from the params of the latest render.
//
// Known difference: Enter in a box does not submit the form (the form only prevents its default); it sends that box.

export interface EmployeeLogFiltersProps {
  query: LogEmployeeQueryOut;
  options: LogEmployeeOptionsOut;
  chip: LogChipOut | null;
  params: EmployeeLogParams;
  settled: boolean;
  onChange: (params: EmployeeLogParams) => void;
}

const FORM_CLASS = "mt-4 mb-4 flex flex-wrap items-center gap-2 text-sm";
const SEARCH_CLASS = "min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const SMALL_SEARCH_CLASS = "w-48 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const NAME_SEARCH_CLASS = "w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const SELECT_CLASS = "shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm";
const DATE_CLASS = "w-32 border-0 bg-transparent py-2 text-sm focus:outline-none";
const SORT_OPTIONS: SelectOption[] = [
  { value: "", label: "Шинэ нь эхэнд" },
  { value: "1", label: "Хуучин нь эхэнд" },
];

// The address of the log without the person: the chip's «×» keeps every other filter.
function removeEmployeeHref(params: EmployeeLogParams): string {
  const search = searchFromEmployeeParams({ ...params, employee: "" }).toString();
  return search ? `/logs/?${search}` : "/logs/";
}

// Enter in a text box sends that box at once; the form itself is not submitted.
function enterFlushes(flush: () => void) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    flush();
  };
}

export function EmployeeLogFilters({ query, options, chip, params, settled, onChange }: EmployeeLogFiltersProps) {
  // Each text box: shows its text, and resyncs when the address changes from outside (see useDebouncedField).
  const [q, setQ, flushQ] = useDebouncedField(params.q, (text) => onChange({ ...params, q: text }));
  const [emp, setEmp, flushEmp] = useDebouncedField(params.emp, (text) => onChange({ ...params, emp: text }));
  const [by, setBy, flushBy] = useDebouncedField(params.by, (text) => onChange({ ...params, by: text }));
  const [field, setField, flushField] = useDebouncedField(params.field, (text) =>
    onChange({ ...params, field: text }),
  );

  const areaOptions: SelectOption[] = [{ value: "", label: "Бүх хэсэг" }, ...options.areas];
  const dateFrom = settled ? query.date_from : params.from;
  const dateTo = settled ? query.date_to : params.to;

  return (
    <form
      id="log-filters"
      className={FORM_CLASS}
      onSubmit={(e: FormEvent<HTMLFormElement>) => e.preventDefault()}
    >
      {chip && (
        <span className="inline-flex items-center gap-1 rounded-full border border-violet-200 bg-violet-50 py-1 pl-3 pr-1 text-sm text-violet-800">
          Ажилтан: {chip.name}
          <input type="hidden" name="employee" value={chip.id} />
          <AppLink
            to={removeEmployeeHref(params)}
            aria-label="Хасах"
            className="rounded-full px-2 text-violet-700 hover:bg-violet-100"
          >
            ×
          </AppLink>
        </span>
      )}
      <input
        type="search"
        name="q"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={enterFlushes(flushQ)}
        placeholder="Мессеж, өөрчлөлтөөр хайх"
        aria-label="Хайх"
        autoComplete="off"
        className={SEARCH_CLASS}
      />
      <input
        type="search"
        name="emp"
        value={emp}
        onChange={(e) => setEmp(e.target.value)}
        onKeyDown={enterFlushes(flushEmp)}
        placeholder="Ажилтны нэр, код"
        aria-label="Ажилтан"
        autoComplete="off"
        className={SMALL_SEARCH_CLASS}
      />
      <input
        type="search"
        name="by"
        value={by}
        onChange={(e) => setBy(e.target.value)}
        onKeyDown={enterFlushes(flushBy)}
        placeholder="Хэн хийсэн"
        aria-label="Хэн хийсэн"
        autoComplete="off"
        className={NAME_SEARCH_CLASS}
      />
      <CheckMenu
        label="Төрөл"
        options={options.kinds}
        selected={settled ? query.kinds : params.kind}
        onChange={(next) => onChange({ ...params, kind: next })}
      />
      <label htmlFor="log-area" className="sr-only">
        Хэсэг
      </label>
      <Select
        id="log-area"
        name="area"
        value={settled ? query.area : params.area}
        options={areaOptions}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => onChange({ ...params, area: v })}
      />
      <input
        type="text"
        name="field"
        value={field}
        onChange={(e) => setField(e.target.value)}
        onKeyDown={enterFlushes(flushField)}
        placeholder="Талбар, жишээ: Хаяг"
        aria-label="Талбар"
        autoComplete="off"
        className={SMALL_SEARCH_CLASS}
      />
      <label htmlFor="log-oldest" className="sr-only">
        Эрэмбэ
      </label>
      <Select
        id="log-oldest"
        name="oldest"
        value={settled ? (query.oldest ? "1" : "") : params.oldest}
        options={SORT_OPTIONS}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => onChange({ ...params, oldest: v })}
      />
      <div className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-300 bg-surface px-3">
        <span className="shrink-0 text-slate-500">Хугацаа</span>
        <input
          type="date"
          name="from"
          value={dateFrom}
          placeholder="Эхлэх"
          aria-label="Эхлэх огноо"
          onChange={(e) => onChange({ ...params, from: e.target.value })}
          className={DATE_CLASS}
        />
        <span className="text-slate-500">–</span>
        <input
          type="date"
          name="to"
          value={dateTo}
          placeholder="Дуусах"
          aria-label="Дуусах огноо"
          onChange={(e) => onChange({ ...params, to: e.target.value })}
          className={DATE_CLASS}
        />
      </div>
      <label className="flex shrink-0 cursor-pointer items-center gap-2 text-slate-700">
        <input
          type="checkbox"
          name="system"
          value="1"
          checked={settled ? query.system : params.system !== ""}
          onChange={(e) => onChange({ ...params, system: e.target.checked ? "1" : "" })}
        />{" "}
        Системийн үйлдэл
      </label>
      <AppLink to="/logs/" className="text-sm text-slate-500 hover:text-violet-700">
        Цэвэрлэх
      </AppLink>
    </form>
  );
}
