import type { ReportLayoutBarOut } from "../../../api/reports";
import { Select } from "../../../widgets/Select";
import { set } from "../filterAddress";

// The layout's own columns under the filters (app/reports/templates/reports/_layout_bar.html): one plain select per entry
// of `bar.selects`, in the API's order. Classes and label markup are copied from the template. A change replaces only
// that parameter in the address (filterAddress.set) and hands the new address to onChange once; every other part of
// `query` (repeated add= and cols=, the order) stays as typed. The bar holds no keep pairs: the address already has them.

export interface LayoutBarProps {
  bar: ReportLayoutBarOut;
  query: string; // the current address query (with or without its leading "?")
  onChange: (nextQuery: string) => void;
}

const FORM_CLASS = "mt-3 flex flex-wrap items-center gap-2 text-sm";
const LABEL_CLASS = "flex max-w-full items-center gap-2 rounded-lg border border-slate-300 bg-surface pl-3";
const LABEL_TEXT_CLASS = "shrink-0 text-slate-500";
const SELECT_CLASS = "max-w-full bg-transparent py-2 pl-1 pr-8 text-sm";

export function LayoutBar({ bar, query, onChange }: LayoutBarProps) {
  if (bar.selects.length === 0) return null;
  return (
    <form aria-label="Харагдацын багана" className={FORM_CLASS}>
      {bar.selects.map((select) => (
        <label key={select.name} className={LABEL_CLASS}>
          <span className={LABEL_TEXT_CLASS}>{select.label}</span>
          <Select
            name={select.name}
            value={select.selected}
            options={select.options}
            search={false}
            className={SELECT_CLASS}
            ariaLabel={select.label}
            onChange={(value) => onChange(set(query, select.name, value))}
          />
        </label>
      ))}
    </form>
  );
}
