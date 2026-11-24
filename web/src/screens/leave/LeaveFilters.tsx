import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import type { LeaveListOut, LeaveListParams } from "../../api/leave";
import { DatePicker } from "../../widgets/DatePicker";
import { Select, type SelectOption } from "../../widgets/Select";
import { useDebouncedField } from "../logs/useDebouncedField";
import { DEFAULT_STATUS } from "./leaveParams";

// The filter bar of the leave list (app/leave/templates/leave/list.html, its filter `form`). Classes, placeholders and
// labels are copied from the template. `params` is the page's address; `onChange` gets the whole new set of filters, and
// the page writes it to the address.
//
// The search box shows what is typed and sends it 300 ms after the last keystroke, or at once on Enter (the Django
// `delay:300ms` box). The other controls call onChange at once. A date is sent when the box is empty or holds a whole
// date (YYYY-MM-DD); a half-typed date stays in the box only.
//
// A filter change drops the `employee` filter: the form does not carry it, so Django's htmx request drops it too. The
// search box then shows the typed text, as in Django.

export interface LeaveFiltersProps {
  params: LeaveListParams;
  types: LeaveListOut["types"];
  onChange: (params: LeaveListParams) => void;
}

const FORM_CLASS = "mt-4 flex flex-wrap items-center gap-2 text-sm";
const SEARCH_CLASS = "min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm";
// UI_RULES §5: the selected text never sits under the arrow.
const SELECT_CLASS = "shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm";
const DATE_BOX_CLASS = "flex items-center gap-1 rounded-lg border border-slate-300 bg-surface pl-3 focus-within:border-violet-500";
const DATE_CLASS = "w-28 rounded-lg border-0 bg-transparent px-2 py-2 text-sm focus:outline-none sm:w-36";
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const STATUS_OPTIONS: SelectOption[] = [
  { value: "recorded", label: "Бүртгэсэн" },
  { value: "cancelled", label: "Цуцалсан" },
  { value: "mistake", label: "Буруу бүртгэсэн" },
  { value: "rejected", label: "Татгалзсан" },
  { value: "all", label: "Бүгд" },
];

// The filters of the form only: the employee filter is not one of them (see the note above).
function change(params: LeaveListParams, patch: Partial<LeaveListParams>): LeaveListParams {
  return {
    q: params.q,
    status: params.status,
    type: params.type,
    from: params.from,
    to: params.to,
    ...patch,
  };
}

// Enter in the search box sends it at once; the form itself is not submitted.
function enterFlushes(flush: () => void) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    flush();
  };
}

export function LeaveFilters({ params, types, onChange }: LeaveFiltersProps) {
  const [q, setQ, flushQ] = useDebouncedField(params.q ?? "", (text) => onChange(change(params, { q: text })));

  const typeOptions: SelectOption[] = [
    { value: "", label: "Бүх төрөл" },
    ...types.map((t) => ({ value: String(t.value), label: t.label })),
  ];

  // The date pickers report every keystroke, so the typed text lives here; it follows the address when the address
  // changes from outside (Back, «Цэвэрлэх»). The address changes only for an empty box or a whole date.
  const [fromText, setFromText] = useState(params.from ?? "");
  const [toText, setToText] = useState(params.to ?? "");
  useEffect(() => setFromText(params.from ?? ""), [params.from]);
  useEffect(() => setToText(params.to ?? ""), [params.to]);

  const setDate = (key: "from" | "to", v: string) => {
    (key === "from" ? setFromText : setToText)(v);
    if (v === "" || ISO_DATE.test(v)) onChange(change(params, { [key]: v }));
  };

  return (
    <form className={FORM_CLASS} onSubmit={(e: FormEvent<HTMLFormElement>) => e.preventDefault()}>
      <input
        type="search"
        name="q"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={enterFlushes(flushQ)}
        placeholder="Ажилтны нэр, кодоор хайх"
        aria-label="Хайх"
        autoComplete="off"
        className={SEARCH_CLASS}
      />
      <label htmlFor="leave-type" className="sr-only">
        Төрөл
      </label>
      <Select
        id="leave-type"
        name="type"
        value={params.type ?? ""}
        options={typeOptions}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => onChange(change(params, { type: v }))}
      />
      <label htmlFor="leave-status" className="sr-only">
        Төлөв
      </label>
      <Select
        id="leave-status"
        name="status"
        value={params.status || DEFAULT_STATUS}
        options={STATUS_OPTIONS}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => onChange(change(params, { status: v }))}
      />
      <div className={DATE_BOX_CLASS}>
        <span className="text-slate-500">Хугацаа</span>
        <DatePicker
          name="from"
          value={fromText}
          placeholder="Эхлэх"
          ariaLabel="Эхлэх огноо"
          onChange={(v) => setDate("from", v)}
          className={DATE_CLASS}
        />
        <span className="text-slate-400">–</span>
        <DatePicker
          name="to"
          value={toText}
          placeholder="Дуусах"
          ariaLabel="Дуусах огноо"
          onChange={(v) => setDate("to", v)}
          className={DATE_CLASS}
        />
      </div>
    </form>
  );
}
