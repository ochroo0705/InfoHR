import type { ItemOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import type { ToggleHandler } from "./AttentionItem";

// A name chip of an undated Анхаарах group (`_attention_chip.html`): the short name (short name · code when two
// people share it, `item.clash`), linked to the person, and a × that hides the item. Items without an employee
// show «Жагсаалт» and no ×.
export function AttentionChip({ item, onToggle }: { item: ItemOut; onToggle: ToggleHandler }) {
  const employee = item.employee;
  const label = employee ? (item.clash ? `${employee.short_name} · ${employee.code}` : employee.short_name) : "Жагсаалт";

  return (
    <span data-chip className="group/chip inline-flex items-center rounded-full border border-slate-200 bg-surface text-xs">
      {employee ? (
        <AppLink
          to={item.url + item.anchor}
          className="rounded-l-full py-0.5 pl-2.5 pr-1 font-medium text-slate-700 hover:text-violet-700"
          title={employee.full_name}
        >
          {label}
        </AppLink>
      ) : (
        <AppLink
          to={item.url}
          className="rounded-l-full py-0.5 pl-2.5 pr-1 font-medium text-slate-700 hover:text-violet-700"
        >
          {label}
        </AppLink>
      )}
      {employee ? (
        <button
          type="button"
          onClick={() => onToggle([item.key], "dismiss")}
          className="rounded-r-full px-2 py-1 text-slate-500 hover:text-slate-600"
          title="Мэдлээ — надад дахин харуулахгүй"
          aria-label={`Мэдлээ: ${employee.full_name}`}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}
