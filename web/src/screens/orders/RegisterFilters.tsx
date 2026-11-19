import { useEffect, useRef, useState, type FormEvent } from "react";
import type {
  OrderRegisterAllLabelsOut,
  OrderRegisterOptionsOut,
  OrderRegisterQueryOut,
  RegisterParams,
} from "../../api/orderRegister";
import { AppLink } from "../../lib/AppLink";
import { Select, type SelectOption } from "../../widgets/Select";

// The filter bar of the order register (orders.html `form#order-filters`). Classes and the placeholder are copied from
// the template. `params` is the page's current picks (the address). `settled` is true only when the data on screen
// answers exactly `params`; until then the selects show the picks, and once settled they show the server's echo, so a
// bad value in the address shows as its «Бүх …» entry. The search box follows `params.q` (the address), never the echo.
// It calls onChange 300 ms after the last keystroke (the Django `delay:300ms`); a select or Enter calls it at once. A
// payload is always built from `params`, never from the echo. The text sent is the cleaned text (the server's cleaning).
//
// Known limitation (accepted): a change from outside that leaves `params.q` as it is (a «Цэвэрлэх» or link within the
// 300 ms quiet time, with the same search text) does not cancel a pending send.
const DEBOUNCE_MS = 300;
const Q_MAX = 100;
const FORM_CLASS = "mt-4 mb-4 flex flex-wrap items-center gap-2 text-sm";
const SEARCH_CLASS = "min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm";
const SELECT_CLASS = "shrink-0 rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm";
const PLACEHOLDER = "Дугаар, ажилтны нэр, кодоор хайх";

export interface RegisterFiltersProps {
  options: OrderRegisterOptionsOut;
  query: OrderRegisterQueryOut;
  allLabels: OrderRegisterAllLabelsOut;
  params: RegisterParams;
  settled: boolean;
  onChange: (params: RegisterParams) => void;
}

// An echoed number as the text the selects use; null (cleaned away, or none set) is the «all» entry.
function echo(value: number | null): string {
  return value == null ? "" : String(value);
}

// The server's cleaning of the search text: strip, then cut to 100 characters. The cut counts code points, as the
// server's Python slice does.
function cleanQ(text: string): string {
  return Array.from(text.trim()).slice(0, Q_MAX).join("");
}

export function RegisterFilters({
  options,
  query,
  allLabels,
  params,
  settled,
  onChange,
}: RegisterFiltersProps) {
  const [q, setQ] = useState(params.q);
  // The newest search text typed (may not be sent yet). The box keeps what is typed; this is what a send uses.
  const qRef = useRef(params.q);
  // The cleaned text this component last passed up.
  const lastEmitted = useRef(params.q);
  // Cleaned texts passed up whose render has not reached `params.q` yet, oldest first. Renders arrive in order.
  const pending = useRef<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function cancelTimer() {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  // Sends the whole filter set: the page's picks, the latest search text, and the one field that changed.
  function emit(change: Partial<RegisterParams> = {}) {
    cancelTimer();
    const text = cleanQ(qRef.current);
    const next: RegisterParams = { ...params, q: text, ...change };
    // A text equal to the last one passed up needs no render to change the address, so it is not waited for.
    if (text !== lastEmitted.current) pending.current.push(text);
    lastEmitted.current = text;
    onChange(next);
  }

  // The timer fires after a render, so it calls the latest emit (the page may have changed the picks meanwhile).
  const emitRef = useRef(emit);
  useEffect(() => {
    emitRef.current = emit;
  });

  function onQInput(value: string) {
    setQ(value);
    qRef.current = value;
    cancelTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      emitRef.current();
    }, DEBOUNCE_MS);
  }

  // The address's search text changed. A text this box passed up and not yet seen come back is our own render: the
  // entries up to it are done, and the box is left alone (typing is never overwritten). Anything else is a change from
  // outside (back or forward, «Цэвэрлэх», a link): it is shown, and a pending send is dropped.
  useEffect(() => {
    const p = params.q;
    const at = pending.current.indexOf(p);
    if (at !== -1) {
      pending.current = pending.current.slice(at + 1);
      return;
    }
    if (pending.current.length === 0 && p === lastEmitted.current) return;
    cancelTimer();
    setQ(p);
    qRef.current = p;
    lastEmitted.current = p;
    pending.current = [];
  }, [params.q]);

  // Clears a pending search when the box goes away.
  useEffect(() => () => cancelTimer(), []);

  // Enter in the search box sends at once, without waiting for the quiet time.
  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    emit();
  }

  // The picks until the data answers them, then the server's echo (a cleaned value shows as its «all» entry).
  const yearValue = settled ? echo(query.year) : params.year;
  const typeValue = settled ? echo(query.order_type) : params.order_type;
  const departmentValue = settled ? echo(query.department) : params.department;
  const stateValue = settled ? query.state : params.state;

  const yearOptions: SelectOption[] = [{ value: "", label: allLabels.year }, ...options.years];
  const typeOptions: SelectOption[] = [{ value: "", label: allLabels.order_type }, ...options.types];
  const departmentOptions: SelectOption[] = [{ value: "", label: allLabels.department }, ...options.departments];
  const stateOptions: SelectOption[] = [{ value: "", label: allLabels.state }, ...options.states];

  return (
    <form id="order-filters" className={FORM_CLASS} onSubmit={onSubmit}>
      <input
        type="search"
        name="q"
        value={q}
        onChange={(e) => onQInput(e.target.value)}
        placeholder={PLACEHOLDER}
        autoComplete="off"
        className={SEARCH_CLASS}
      />
      <input type="hidden" name="sort" id="order-sort" value={params.sort} />
      <Select
        name="year"
        value={yearValue}
        options={yearOptions}
        search={false}
        className={SELECT_CLASS}
        onChange={(v) => emit({ year: v })}
      />
      <Select
        name="order_type"
        value={typeValue}
        options={typeOptions}
        className={SELECT_CLASS}
        onChange={(v) => emit({ order_type: v })}
      />
      <Select
        name="department"
        value={departmentValue}
        options={departmentOptions}
        className={SELECT_CLASS}
        onChange={(v) => emit({ department: v })}
      />
      <Select
        name="state"
        value={stateValue}
        options={stateOptions}
        className={SELECT_CLASS}
        onChange={(v) => emit({ state: v })}
      />
      <AppLink to="/employees/orders/" className="text-sm text-slate-500 hover:text-violet-700">
        Цэвэрлэх
      </AppLink>
    </form>
  );
}
