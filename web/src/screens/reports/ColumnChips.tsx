import type { ReactNode } from "react";
import type { components } from "../../api/schema";
import { TLink } from "../../lib/viewTransition";
import { Select, type SelectOption } from "../../widgets/Select";
import { DateField, NumberField } from "./CommitFields";

// The column-filter chips of the report filter bar (app/reports/templates/reports/_column_filters.html, part chips).
// Each chip is one grid cell with its ✕ (a link to remove_href). The chip's query parameters come from the API
// (`params`, in order: one for a choice or code, the `_from` and `_to` bounds of a range); values are positional with
// them. A change edits only the chip's own parameter through filterAddress.set and hands the new address to onChange.

type ReportColumnChipOut = components["schemas"]["ReportColumnChipOut"];

export interface ColumnChipsProps {
  chips: ReportColumnChipOut[];
  query: string; // the settled cleaned address (table.query): what the chips display
  // One edit of the address: the parameter takes the value and the rest of the latest requested address stays (the
  // FilterBar builds it, so edits made while a new address loads compose).
  onEdit: (name: string, value: string) => void;
}

const CHIP_CLASS =
  "flex min-w-0 items-center gap-1 rounded-lg border border-slate-300 bg-surface pl-3 pr-1 text-sm sm:col-span-2";
const CHIP_SELECT_CLASS = "min-w-0 flex-1 border-0 bg-transparent py-2 pr-6 text-sm focus:outline-none";
const CHIP_INPUT_CLASS = "w-full min-w-0 border-0 bg-transparent py-2 text-sm focus:outline-none";
const REMOVE_CLASS = "shrink-0 rounded-full px-2 py-1 text-violet-700 hover:bg-violet-100";

export function ColumnChips({ chips, query, onEdit }: ColumnChipsProps) {
  return (
    <>
      {chips.map((chip) => (
        <ColumnChip key={chip.name} chip={chip} query={query} onEdit={onEdit} />
      ))}
    </>
  );
}

function ColumnChip({ chip, query, onEdit }: { chip: ReportColumnChipOut; query: string; onEdit: ColumnChipsProps["onEdit"] }) {
  const edit = (param: string, value: string) => onEdit(param, value);
  const values = chip.values;
  const first = chip.params[0] ?? "";
  const second = chip.params[1] ?? "";
  const id = `report-chip-${chip.name}`;

  let body: ReactNode;
  if (chip.kind === "code" || chip.kind === "choice") {
    const list: SelectOption[] = [
      { value: "", label: "Бүгд" },
      ...chip.options.map((o) => ({ value: o.value, label: o.label })),
    ];
    body = (
      <>
        <label htmlFor={id} className="sr-only">
          {chip.label}
        </label>
        <Select
          id={id}
          name={first}
          value={values[0] ?? ""}
          options={list}
          search={false}
          className={CHIP_SELECT_CLASS}
          onChange={(value) => edit(first, value)}
        />
      </>
    );
  } else if (chip.kind === "date") {
    body = (
      <>
        <DateField
          name={first}
          value={values[0] ?? ""}
          syncKey={query}
          ariaLabel={`${chip.label}: эхлэх`}
          placeholder="Эхлэх"
          className={CHIP_INPUT_CLASS}
          onCommit={(v) => edit(first, v)}
        />
        <span className="text-slate-500">–</span>
        <DateField
          name={second}
          value={values[1] ?? ""}
          syncKey={query}
          ariaLabel={`${chip.label}: дуусах`}
          placeholder="Дуусах"
          className={CHIP_INPUT_CLASS}
          onCommit={(v) => edit(second, v)}
        />
      </>
    );
  } else {
    body = (
      <>
        <NumberField
          name={first}
          value={values[0] ?? ""}
          syncKey={query}
          ariaLabel={`${chip.label}: доод`}
          placeholder="Доод"
          min={0}
          className={CHIP_INPUT_CLASS}
          onCommit={(v) => edit(first, v)}
        />
        <span className="text-slate-500">–</span>
        <NumberField
          name={second}
          value={values[1] ?? ""}
          syncKey={query}
          ariaLabel={`${chip.label}: дээд`}
          placeholder="Дээд"
          min={0}
          className={CHIP_INPUT_CLASS}
          onCommit={(v) => edit(second, v)}
        />
      </>
    );
  }

  return (
    <>
      {/* every shown chip keeps its `add` entry, so a chip whose value is cleared stays on screen after a change */}
      <input type="hidden" name="add" value={chip.name} />
      <div className={CHIP_CLASS} data-column-chip={chip.name}>
        <span className="shrink-0 text-slate-500">{chip.label}</span>
        {body}
        <TLink to={chip.remove_href} aria-label="Шүүлтүүрийг арилгах" className={REMOVE_CLASS}>
          ×
        </TLink>
      </div>
    </>
  );
}
