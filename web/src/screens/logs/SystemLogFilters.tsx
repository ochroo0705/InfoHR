import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import type { LogSystemOptionsOut, LogSystemQueryOut, SystemLogParams } from "../../api/logs";
import { AppLink } from "../../lib/AppLink";
import { DatePicker } from "../../widgets/DatePicker";
import { Select, type SelectOption } from "../../widgets/Select";
import { CheckMenu } from "./CheckMenu";
import { useDebouncedField } from "./useDebouncedField";

// The filter bar of the system log (app/logs/templates/logs/system.html, `form#log-filters`). Classes, placeholders and
// labels are copied from the template. `params` is the page's address. `settled` is true only when the rows on screen
// answer exactly `params`; then the selects, the category menu and the dates show the server's echo (`query`), so a junk
// value shows as cleaned or as its «all» entry. Until then they show the address.
//
// The four text boxes (q, by, target, ip) follow the address, never the echo, as the employee log's filter bar does: they
// show what the user typed and send it 300 ms after the last keystroke, or at once on Enter (the focused box only). The
// other controls call onChange at once. Every call sends the whole address (`params` plus the one change), built from the
// params of the latest render.
//
// Known difference: Enter in a box does not submit the form (the form only prevents its default); it sends that box.

export interface SystemLogFiltersProps {
  query: LogSystemQueryOut;
  options: LogSystemOptionsOut;
  params: SystemLogParams;
  settled: boolean;
  onChange: (params: SystemLogParams) => void;
}

const FORM_CLASS = "mt-4 mb-4 flex flex-wrap items-center gap-2 text-sm";
const SEARCH_CLASS = "min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const BY_CLASS = "w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const TARGET_CLASS = "w-44 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const IP_CLASS = "w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const SELECT_CLASS = "shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm";
const DATE_CLASS = "w-32 border-0 bg-transparent py-2 text-sm focus:outline-none";
const SORT_OPTIONS: SelectOption[] = [
  { value: "", label: "Шинэ нь эхэнд" },
  { value: "1", label: "Хуучин нь эхэнд" },
];

// Enter in a text box sends that box at once; the form itself is not submitted.
function enterFlushes(flush: () => void) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    flush();
  };
}

export function SystemLogFilters({ query, options, params, settled, onChange }: SystemLogFiltersProps) {
  // Each text box: shows its text, and resyncs when the address changes from outside (see useDebouncedField).
  const [q, setQ, flushQ] = useDebouncedField(params.q, (text) => onChange({ ...params, q: text }));
  const [by, setBy, flushBy] = useDebouncedField(params.by, (text) => onChange({ ...params, by: text }));
  const [target, setTarget, flushTarget] = useDebouncedField(params.target, (text) =>
    onChange({ ...params, target: text }),
  );
  const [ip, setIp, flushIp] = useDebouncedField(params.ip, (text) => onChange({ ...params, ip: text }));

  const actionOptions: SelectOption[] = [{ value: "", label: "Бүх үйлдэл" }, ...options.actions];
  const dateFrom = settled ? query.date_from : params.from;
  const dateTo = settled ? query.date_to : params.to;

  // The picker is fully controlled and reports every keystroke, so the typed text lives here; the address changes only for
  // an empty box or a whole date, and the text follows the address again when it changes from outside (Цэвэрлэх, Back).
  const [fromText, setFromText] = useState<string>(dateFrom);
  const [toText, setToText] = useState<string>(dateTo);
  useEffect(() => setFromText(dateFrom), [dateFrom]);
  useEffect(() => setToText(dateTo), [dateTo]);
  // The picker reports every keystroke; the address changes only for an empty box or a whole date (YYYY-MM-DD), as
  // Django does (its box sends on `change`, after the text is cleaned).
  const setDate = (key: "from" | "to", v: string) => {
    (key === "from" ? setFromText : setToText)(v);
    if (v === "" || /^\d{4}-\d{2}-\d{2}$/.test(v)) onChange({ ...params, [key]: v });
  };

  return (
    <form
      id="log-filters"
      className={FORM_CLASS}
      onSubmit={(e: FormEvent<HTMLFormElement>) => e.preventDefault()}
    >
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
        name="by"
        value={by}
        onChange={(e) => setBy(e.target.value)}
        onKeyDown={enterFlushes(flushBy)}
        placeholder="Хэн хийсэн"
        aria-label="Хэн хийсэн"
        autoComplete="off"
        className={BY_CLASS}
      />
      <input
        type="search"
        name="target"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        onKeyDown={enterFlushes(flushTarget)}
        placeholder="Зорилт, жишээ: Ажилтан"
        aria-label="Зорилт"
        autoComplete="off"
        className={TARGET_CLASS}
      />
      <input
        type="search"
        name="ip"
        value={ip}
        onChange={(e) => setIp(e.target.value)}
        onKeyDown={enterFlushes(flushIp)}
        placeholder="IP, жишээ: 10.0."
        aria-label="IP хаяг"
        autoComplete="off"
        className={IP_CLASS}
      />
      <CheckMenu
        label="Ангилал"
        options={options.categories}
        selected={settled ? query.categories : params.category}
        onChange={(next) => onChange({ ...params, category: next })}
      />
      <label htmlFor="log-action" className="sr-only">
        Үйлдэл
      </label>
      <Select
        id="log-action"
        name="action"
        value={settled ? query.action : params.action}
        options={actionOptions}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => onChange({ ...params, action: v })}
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
        <DatePicker
          name="from"
          value={fromText}
          placeholder="Эхлэх"
          ariaLabel="Эхлэх огноо"
          onChange={(v) => setDate("from", v)}
          className={DATE_CLASS}
        />
        <span className="text-slate-500">–</span>
        <DatePicker
          name="to"
          value={toText}
          placeholder="Дуусах"
          ariaLabel="Дуусах огноо"
          onChange={(v) => setDate("to", v)}
          className={DATE_CLASS}
        />
      </div>
      <AppLink to="/logs/system/" className="text-sm text-slate-500 hover:text-violet-700">
        Цэвэрлэх
      </AppLink>
    </form>
  );
}
