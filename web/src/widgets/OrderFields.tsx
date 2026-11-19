import { useEffect, useRef, useState } from "react";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { suggestOrderNumber } from "../api/hire";
import { BoxedControl, initialValue, type FormValues } from "./FormFields";

// The four order boxes (`employees/_order_fields.html`, with `_order_number_field.html` for the number box): the number
// with the «Санал болгох» button, the date, the summary (two columns) and the issuer. Shared by the hire page and the
// event pop-up. The caller picks the fields and their order; this component draws them and decides no rule (no
// required decisions, no heading text).
// The «Санал болгох» button follows app/static/js/order_suggest.js exactly:
// - it asks the server with the date box's value, and sends no date when that value is empty;
// - it is disabled while the request runs;
// - an answer with a number fills the number box (always, even over a typed number) and fills the date box only when
//   the date box is still empty (checked when the answer comes, not when the click happened);
// - an answer without a number, or a failed request, shows the note under the number box. A good answer hides it again.
// The number box is the field named `number` or ending with `-number`, the date box the one named `date` or ending with
// `-date` (the script's `name="number"` or `name$="-number"`). A summary box spans two columns.
// Callers must update their state with a functional updater (set(name, value) => setEdits(prev => ...)): the block can
// call onChange twice in a row (number, then date), and a plain snapshot would drop the first change.
// Errors are drawn under the box they belong to (`errors[name]`), as Django draws them.

const SUGGEST_NOTE = "Дугаарыг санал болгох боломжгүй, гараар оруулна уу.";

export type OrderFieldsProps = {
  // The boxes to draw, in order. Names carry the `order-` prefix in the hire and event forms.
  fields: EmployeeFormFieldOut[];
  // The current text per field name.
  values: FormValues;
  // Django's messages per field name, drawn under the box.
  errors: Record<string, string[]>;
  onChange: (name: string, value: string) => void;
};

// The Django rule for the boxes the script finds: the bare name or the name after a hyphen.
function namedLike(name: string, suffix: string): boolean {
  return name === suffix || name.endsWith("-" + suffix);
}

export function OrderFields({ fields, values, errors, onChange }: OrderFieldsProps) {
  const numberName = fields.find((field) => namedLike(field.name, "number"))?.name;
  const dateName = fields.find((field) => namedLike(field.name, "date"))?.name;

  const [busy, setBusy] = useState(false);
  const [noteShown, setNoteShown] = useState(false);

  // Set false on unmount: a request still pending then must not update state or call onChange.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The latest values, read after the request (the script reads the date box at that moment, not at the click).
  const latest = useRef(values);
  useEffect(() => {
    latest.current = values;
  });

  const shownOf = (field: EmployeeFormFieldOut) => values[field.name] ?? initialValue(field);

  async function suggest() {
    const dateAtClick = dateName ? (latest.current[dateName] ?? "") : "";
    setBusy(true);
    try {
      const answer = await suggestOrderNumber(dateAtClick);
      if (!mounted.current) return;
      setNoteShown(!answer.number);
      if (!answer.number) return;
      if (numberName) onChange(numberName, answer.number);
      if (dateName && !(latest.current[dateName] ?? "")) onChange(dateName, answer.date);
    } catch {
      if (mounted.current) setNoteShown(true);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {fields.map((field) => {
        const fieldErrors = errors[field.name] ?? [];
        const isNumber = field.name === numberName;
        const isSummary = field.name.endsWith("summary");
        const control = (
          <BoxedControl
            field={field}
            value={shownOf(field)}
            invalid={fieldErrors.length > 0}
            onChange={onChange}
          />
        );
        return (
          <label key={field.name} className={isSummary ? "block text-sm md:col-span-2" : "block text-sm"}>
            {field.label}
            {field.required ? " *" : null}
            {isNumber ? (
              <>
                <span className="flex gap-2">
                  {control}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={suggest}
                    className="shrink-0 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Санал болгох
                  </button>
                </span>
                <span className={noteShown ? "text-xs text-slate-500" : "hidden text-xs text-slate-500"}>
                  {SUGGEST_NOTE}
                </span>
              </>
            ) : (
              control
            )}
            {fieldErrors.map((message, i) => (
              <span key={i} className="text-xs text-red-600">
                {message}
              </span>
            ))}
          </label>
        );
      })}
    </div>
  );
}
