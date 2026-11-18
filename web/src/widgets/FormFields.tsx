import { useCallback, useMemo, useState, type ChangeEvent, type ReactNode, type RefObject } from "react";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { Soft, SOFT, type SoftKind } from "../screens/employee/Soft";
import { DatePicker } from "./DatePicker";
import { MoneyInput } from "./MoneyInput";
import { Select } from "./Select";

// One renderer for a form the server describes (`EmployeeFormFieldOut`, see app/employees/services/form_schema.py).
// Two looks, both from the Django templates they replace:
// - "soft": each field is a `Soft` box (the tab field grid of UI_RULES §2e, `hr.SOFT`), returned as a list of boxes so
//   the caller can put each one in a <td> (inline list rows, Task 15b).
// - "boxed": the modal layout of `employees/_modal.html`: a two-column grid, each field a <label> with its text, a
//   " *" when required, the control with the `hr.BOXED` classes, the help text and the errors under it. `reason` spans
//   both columns.
// The kinds are the ones `describe_field` returns (text, textarea, number, date, select, checkbox) plus "money" for a
// MoneyField amount (Task 7). A money box is a MoneyInput: it shows digits grouped by commas, but reports the PLAIN
// number ("2500000") to `onChange`, because the server reads the posted value and ignores nothing else.
// Values are strings as the browser would post them. A checkbox is "on" or "". `values` holds the current text per
// name; a name missing from it falls back to the field's own value (`initialValue`).

export type FormField = EmployeeFormFieldOut;
export type FormValues = Record<string, string>;

// hr.BOXED with the width of the modal's boxes (`w-full`), as the Select and MoneyInput boxes draw it.
export const BOXED = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
// A date box keeps room on the right for the calendar button (DatePicker's own FIELD does the same).
const BOXED_DATE = "w-full rounded-lg border border-slate-300 py-2 pl-3 pr-9 text-sm";
// The soft box's width in a table cell (hr.field width="w-full min-w-20" as the inline rows draw it).
const SOFT_WIDTH = "w-full min-w-20";
const SOFT_KINDS: readonly string[] = ["select", "checkbox", "text", "textarea", "date", "number"];

// The text a field starts with: the server's value; a checkbox starts "on" when the server marks it checked.
export function initialValue(field: FormField): string {
  if (field.kind === "checkbox") return field.checked ? "on" : "";
  return field.value ?? "";
}

function baselineOf(fields: FormField[]): FormValues {
  return Object.fromEntries(fields.map((field) => [field.name, initialValue(field)]));
}

// A money box reports its grouped text; the plain number is what is posted.
function plainOf(field: FormField, text: string): string {
  return field.kind === "money" ? text.replace(/,/g, "") : text;
}

function softKind(kind: string): SoftKind {
  return SOFT_KINDS.includes(kind) ? (kind as SoftKind) : "text";
}

function errorsOf(errors: Record<string, string[]>, name: string): string[] {
  return errors[name] ?? [];
}

// One soft box of a form. `value` is the current text, `errors` the messages for this field. A money field is drawn
// here as a MoneyInput with the soft classes, since `Soft` has no money kind; it gets the same changed mark and errors.
export function SoftBox({
  field,
  value,
  errors = [],
  onChange,
  formId,
  id,
}: {
  field: FormField;
  value: string;
  errors?: string[];
  onChange: (name: string, value: string) => void;
  formId?: string;
  // The control's id (an inline row passes `inline-<kind>-<field>`). Money boxes keep no id here.
  id?: string;
}): ReactNode {
  if (field.kind !== "money") {
    return (
      <Soft
        label={field.label}
        kind={softKind(field.kind)}
        value={value}
        choice={field.choice}
        combo={field.combo}
        checked={value === "on"}
        placeholder={field.placeholder}
        width={SOFT_WIDTH}
        name={field.name}
        form={formId}
        onChange={onChange}
        error={errors}
        changed={value !== initialValue(field)}
        choices={field.choices}
        id={id}
      />
    );
  }
  const invalid = errors.length > 0;
  const box = (
    <MoneyInput
      name={field.name}
      form={formId}
      value={value}
      placeholder={field.placeholder}
      aria-label={field.label}
      aria-invalid={invalid || undefined}
      className={`${SOFT_WIDTH} ${SOFT}`}
      onChange={(text) => onChange(field.name, plainOf(field, text))}
    />
  );
  // The wrapper stays the same element in both states (only its class changes), so the input is not remounted on the
  // first keystroke and keeps its focus.
  return (
    <>
      <span className={value !== initialValue(field) ? "f-changed contents" : "contents"}>{box}</span>
      {errors.map((message, i) => (
        <p key={i} className="mt-1 text-xs text-red-600">
          {message}
        </p>
      ))}
    </>
  );
}

// The control of one boxed field. `firstRef` is set on the native controls only (input, textarea, select of a plain kind):
// Select, DatePicker and MoneyInput keep their own element, so a focus target for them is not offered.
// Exported so a single field (the hire page's HireField) draws the same control as FormFields does.
export function BoxedControl({
  field,
  value,
  invalid,
  id,
  formId,
  onChange,
  firstRef,
}: {
  field: FormField;
  value: string;
  invalid: boolean;
  id?: string;
  formId?: string;
  onChange: (name: string, value: string) => void;
  firstRef?: (el: HTMLElement | null) => void;
}): ReactNode {
  const name = field.name;
  const ariaInvalid = invalid || undefined;
  switch (field.kind) {
    case "checkbox":
      return (
        <input
          ref={firstRef}
          type="checkbox"
          id={id}
          name={name}
          form={formId}
          required={field.required}
          checked={value === "on"}
          aria-invalid={ariaInvalid}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(name, e.target.checked ? "on" : "")}
          className="h-4 w-4 accent-violet-600"
        />
      );
    case "select":
      return (
        <Select
          id={id}
          name={name}
          form={formId}
          value={value}
          options={field.choices}
          search={field.combo}
          required={field.required}
          invalid={invalid}
          className={BOXED}
          onChange={(next) => onChange(name, next)}
        />
      );
    case "date":
      return (
        <DatePicker
          id={id}
          name={name}
          form={formId}
          value={value}
          required={field.required}
          invalid={invalid}
          placeholder={field.placeholder || undefined}
          className={BOXED_DATE}
          onChange={(next) => onChange(name, next)}
        />
      );
    case "money":
      return (
        <MoneyInput
          id={id}
          name={name}
          form={formId}
          value={value}
          required={field.required}
          aria-invalid={ariaInvalid}
          placeholder={field.placeholder || undefined}
          className={BOXED}
          onChange={(text) => onChange(name, plainOf(field, text))}
        />
      );
    case "textarea":
      return (
        <textarea
          ref={firstRef}
          id={id}
          name={name}
          form={formId}
          required={field.required}
          rows={2}
          maxLength={field.max_length ?? undefined}
          value={value}
          placeholder={field.placeholder || undefined}
          aria-invalid={ariaInvalid}
          className={BOXED}
          onChange={(e) => onChange(name, e.target.value)}
        />
      );
    case "number":
      return (
        <input
          ref={firstRef}
          type="number"
          id={id}
          name={name}
          form={formId}
          required={field.required}
          value={value}
          placeholder={field.placeholder || undefined}
          aria-invalid={ariaInvalid}
          className={BOXED}
          onChange={(e) => onChange(name, e.target.value)}
        />
      );
    default:
      return (
        <input
          ref={firstRef}
          type="text"
          id={id}
          name={name}
          form={formId}
          required={field.required}
          maxLength={field.max_length ?? undefined}
          value={value}
          placeholder={field.placeholder || undefined}
          aria-invalid={ariaInvalid}
          className={BOXED}
          onChange={(e) => onChange(name, e.target.value)}
        />
      );
  }
}

export interface FormFieldsProps {
  fields: FormField[];
  // The current text per field name. A name missing here falls back to the field's own value.
  values: FormValues;
  // Django's messages per field name.
  errors: Record<string, string[]>;
  // Called with each change as (name, value); a money value is already plain ("2500000").
  onChange: (name: string, value: string) => void;
  variant: "boxed" | "soft";
  // The prefix of the boxed controls' ids: id = `${idPrefix}-${name}` (Django's inline ids, `inline-<kind>-<field>`).
  // Soft boxes take their own ids (Soft uses useId), so idPrefix does not reach them.
  idPrefix?: string;
  // The id of the <form> the boxes post with (the `form` attribute). Unset: no attribute.
  formId?: string;
  // Receives the first field's native control (boxed: input, textarea or a plain select; not Select, DatePicker or money).
  firstFieldRef?: RefObject<HTMLElement | null>;
}

export function FormFields({
  fields,
  values,
  errors,
  onChange,
  variant,
  idPrefix,
  formId,
  firstFieldRef,
}: FormFieldsProps): ReactNode {
  const shownOf = (field: FormField) => values[field.name] ?? initialValue(field);
  // Stable across renders, so a native control's ref is not re-run on every render.
  const setFirst = useCallback(
    (el: HTMLElement | null) => {
      if (firstFieldRef) firstFieldRef.current = el;
    },
    [firstFieldRef],
  );

  if (variant === "soft") {
    return (
      <>
        {fields.map((field) => (
          <SoftBox
            key={field.name}
            field={field}
            value={shownOf(field)}
            errors={errorsOf(errors, field.name)}
            onChange={onChange}
            formId={formId}
          />
        ))}
      </>
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {fields.map((field, index) => {
        const fieldErrors = errorsOf(errors, field.name);
        const invalid = fieldErrors.length > 0;
        const labelClass = ["block text-sm", field.name === "reason" ? "md:col-span-2" : ""].filter(Boolean).join(" ");
        return (
          <label key={field.name} className={labelClass}>
            {field.label}
            {field.required ? " *" : null}
            <BoxedControl
              field={field}
              value={shownOf(field)}
              invalid={invalid}
              id={idPrefix ? `${idPrefix}-${field.name}` : undefined}
              formId={formId}
              onChange={onChange}
              firstRef={index === 0 ? setFirst : undefined}
            />
            {field.help ? <span className="block text-xs text-slate-500">{field.help}</span> : null}
            {fieldErrors.map((message, i) => (
              <span key={i} className="block text-xs text-red-600">
                {message}
              </span>
            ))}
          </label>
        );
      })}
    </div>
  );
}

// The values of a form, starting from the fields' own values. `set` changes one; `reset` drops every edit, so the values
// are the fields' own again; `dirty` is true when a field of `fields` differs from its own value (an edit to a name that
// is not in `fields` does not count).
//
// Contract for `resetKey` (the form's identity, e.g. `${kind}/${key}` or the correction path):
// - A new `fields` array for the same form (a refetch after a save elsewhere, a re-render) keeps the edits, so typing is
//   never lost to a refetch. The baseline becomes the new fields' values; edits stay as they were.
// - A change of `resetKey` (a different form) drops every edit at once, during the render, so the first render of the
//   new form already shows its own values.
// - `reset()` is for after a successful save: the caller refetches and then drops the edits it just saved.
// A field added later (a reload) reads its own value until it is edited.
export function useFormValues(
  fields: FormField[],
  resetKey?: string,
): {
  values: FormValues;
  set: (name: string, value: string) => void;
  reset: () => void;
  dirty: boolean;
} {
  const baseline = useMemo(() => baselineOf(fields), [fields]);
  const [edits, setEdits] = useState<FormValues>({});
  const [keyed, setKeyed] = useState(resetKey);
  // A change of form drops the edits while rendering (React's "adjust state when a prop changes" pattern).
  if (keyed !== resetKey) {
    setKeyed(resetKey);
    setEdits({});
  }
  const values = useMemo(() => ({ ...baseline, ...edits }), [baseline, edits]);
  const set = useCallback((name: string, value: string) => setEdits((prev) => ({ ...prev, [name]: value })), []);
  const reset = useCallback(() => setEdits({}), []);
  const dirty = useMemo(
    () => fields.some((field) => values[field.name] !== baseline[field.name]),
    [fields, values, baseline],
  );
  return { values, set, reset, dirty };
}

// The body values of a form: every field as a string. A checkbox is "on" or "" (as a browser posts it), a money value
// has no commas. Callers merge the form's `hidden` map (the loaded_* snapshots) into the result.
export function toPostValues(fields: FormField[], values: FormValues): FormValues {
  const out: FormValues = {};
  for (const field of fields) {
    const raw = values[field.name] ?? initialValue(field);
    if (field.kind === "checkbox") out[field.name] = raw === "on" ? "on" : "";
    else out[field.name] = plainOf(field, raw);
  }
  return out;
}
