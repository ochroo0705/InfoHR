import { useId, type ReactNode } from "react";
import { useMeta } from "../../shell/useMeta";
import { DatePicker } from "../../widgets/DatePicker";
import { Select } from "../../widgets/Select";
import { ClashChoice } from "./ClashChoice";
import { usePageField } from "./PageForm";

// The soft box of a tab's field grid (`hr.SOFT` and the widget kinds of `hr.field`, UI_RULES §2e). Shared by the Work,
// Salary and Personal tabs. Without `onChange` the box is read-only: a select draws only its current option and stops mousedown and
// keydown, so it looks the same but does not open (disabled would change the look). With `onChange` a text, number, textarea or
// checkbox box is controlled by its parent and reports each change as `onChange(name, value)`, a checkbox as "on" or "" as the browser
// would post it. A select (the shared `Select`) picks from `choices` and reports the picked value, or "" when cleared through the
// blank entry. A date (the shared `DatePicker`) reports a complete ISO date ("YYYY-MM-DD") when it is typed or picked in full, and ""
// when cleared; a partial or non-ISO typed text (such as "2024-01") is reported as typed, as Django's box posts it, and Python
// validates it (Task 11 ruling). `label` is the form field's accessible name (`aria_label` from the
// API), never the row's text. A multi-line box (textarea) is one line tall and grows with its text (`hr.field`: rows="1", resize-none,
// field-sizing content). `error` draws Django's `_field.html` messages after the box; `changed` marks the box as edited (`f-changed`).

export const SOFT =
  "f-soft rounded-md border border-slate-200 bg-slate-50 px-2 py-1 hover:border-slate-400 hover:bg-surface focus:border-violet-600 focus:bg-surface focus:outline-none";

export type SoftKind = "select" | "checkbox" | "text" | "textarea" | "date" | "number";

export function Soft({
  label,
  kind,
  value,
  choice,
  combo = false,
  checked,
  placeholder = "—",
  width = "w-full",
  name,
  form,
  onChange,
  error,
  changed = false,
  choices,
  canAdd = false,
  id: idProp,
}: {
  label: string;
  kind: SoftKind;
  value: string;
  choice?: string;
  // A select with a quick-add list: Django draws it as a combo text box (select.js), showing the current option's text.
  combo?: boolean;
  checked?: boolean;
  placeholder?: string;
  width?: string;
  // The form field's name, sent with each change when `onChange` is given.
  name?: string;
  // The id of the <form> the box posts with (Django's `form="..."` attribute). The page form has no wrapper, so a box
  // names its form here.
  form?: string;
  onChange?: (name: string, value: string) => void;
  // Django's error messages for this field; they also mark the box aria-invalid.
  error?: string[];
  // True when the value was changed and not saved yet (the violet edge of `.f-changed .f-soft`).
  changed?: boolean;
  // The options of an editable select, in order. The caller sends the full list from the server, including the blank entry
  // ({value: "", label: ""}) that an optional field has first (Django's empty option); Soft does not add one itself. A `value`
  // missing from `choices` shows as a blank box, so the caller must send every option the saved value can be.
  choices?: { value: string; label: string }[];
  // Passed to the shared Select: the add line shows only with an add URL too, which no Soft box has yet.
  canAdd?: boolean;
  // The id of the control (an inline row's box is `inline-<kind>-<field>`). Unset: a generated id.
  id?: string;
}) {
  const editable = onChange !== undefined;
  const invalid = (error?.length ?? 0) > 0;
  const fieldName = name ?? "";
  const className = `${width} ${SOFT}`;
  const generatedId = useId();
  const id = idProp ?? generatedId;

  function box() {
    if (kind === "checkbox") {
      if (!editable) {
        // readOnly does not stop a checkbox click. A controlled checkbox with a no-op onChange makes React put the `checked`
        // prop back after each click, so the box stays as it was.
        return (
          <input
            type="checkbox"
            readOnly
            checked={checked}
            onChange={() => {}}
            aria-label={label}
            aria-invalid={invalid || undefined}
            autoComplete="off"
            className="h-4 w-4 accent-violet-600"
          />
        );
      }
      return (
        <input
          type="checkbox"
          name={fieldName}
          id={id}
          form={form}
          checked={checked}
          onChange={(e) => onChange(fieldName, e.target.checked ? "on" : "")}
          aria-label={label}
          aria-invalid={invalid || undefined}
          autoComplete="off"
          className="h-4 w-4 accent-violet-600"
        />
      );
    }
    if (kind === "select" && editable) {
      // The shared Select: a combo text box when `combo` (search on), else its click list (search off). The visible label
      // is a screen-reader label bound to the field, since Select takes no aria-label.
      // Enter inside a combo box picks the highlighted row first, as Django's select.js does; the next Enter submits the
      // page form. Select is the step-1 port of select.js and is not changed for this.
      return (
        <>
          <label htmlFor={combo ? `sel-${id}` : id} className="sr-only">
            {label}
          </label>
          <Select
            id={id}
            name={fieldName}
            form={form}
            value={value}
            options={choices ?? []}
            search={combo}
            canAdd={canAdd}
            className={className}
            invalid={invalid}
            onChange={(next) => onChange(fieldName, next)}
          />
        </>
      );
    }
    if (kind === "select" && combo) {
      // The combo box of select.js: a text input with the select's classes, plus sel-combo for its arrow. Read-only here.
      return (
        <input
          type="text"
          readOnly
          value={choice ?? ""}
          role="combobox"
          aria-expanded="false"
          aria-autocomplete="list"
          aria-label={label}
          autoComplete="off"
          spellCheck={false}
          className={`${className} sel-combo`}
        />
      );
    }
    if (kind === "select") {
      return (
        <select
          aria-label={label}
          defaultValue={value}
          className={className}
          onMouseDown={(e) => e.preventDefault()}
          onKeyDown={(e) => e.preventDefault()}
        >
          <option value={value}>{choice}</option>
        </select>
      );
    }
    if (kind === "textarea") {
      if (editable) {
        return (
          <textarea
            name={fieldName}
            id={id}
            form={form}
            rows={1}
            value={value}
            onChange={(e) => onChange(fieldName, e.target.value)}
            placeholder={placeholder}
            aria-label={label}
            aria-invalid={invalid || undefined}
            autoComplete="off"
            className={`${className} resize-none [field-sizing:content]`}
          />
        );
      }
      return (
        <textarea
          readOnly
          rows={1}
          value={value}
          placeholder={placeholder}
          aria-label={label}
          autoComplete="off"
          className={`${className} resize-none [field-sizing:content]`}
        />
      );
    }
    if (kind === "date" && editable) {
      // The shared DatePicker: its text box sits in a span.dp-wrap with the calendar button (dp-icon). A complete ISO date
      // (typed or picked) reports "YYYY-MM-DD" and clearing reports ""; partial or non-ISO typing reports the raw typed text,
      // which the server validates (Task 11 ruling).
      return (
        <>
          <label htmlFor={id} className="sr-only">
            {label}
          </label>
          <DatePicker
            id={id}
            name={fieldName}
            form={form}
            value={value}
            className={className}
            invalid={invalid}
            placeholder={placeholder}
            onChange={(next) => onChange(fieldName, next)}
          />
        </>
      );
    }
    if (kind === "date") {
      // datepicker.js turns every date box into a text box in a span.dp-wrap, with its calendar button (dp-icon) inside.
      // Read-only here: the button draws the same icon and does nothing.
      return (
        <span className="dp-wrap">
          <input
            type="text"
            readOnly
            inputMode="numeric"
            maxLength={10}
            title="Жил-сар-өдөр"
            data-dp="1"
            value={value}
            placeholder={placeholder}
            aria-label={label}
            autoComplete="off"
            className={className}
          />
          <button type="button" tabIndex={-1} aria-label="Хуанли нээх" className="dp-icon">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
              <rect x="3" y="4.5" width="14" height="12" rx="2" />
              <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
            </svg>
          </button>
        </span>
      );
    }
    if (editable) {
      return (
        <input
          type={kind}
          name={fieldName}
          id={id}
          form={form}
          value={value}
          onChange={(e) => onChange(fieldName, e.target.value)}
          placeholder={placeholder}
          aria-label={label}
          aria-invalid={invalid || undefined}
          autoComplete="off"
          className={className}
        />
      );
    }
    return (
      <input
        type={kind}
        readOnly
        value={value}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        className={className}
      />
    );
  }

  const element = box();
  // An editable box is always inside the same wrapper, so toggling `changed` changes only the wrapper's class and the box
  // keeps its node and focus. A read-only box is wrapped only when changed, as before.
  const marked =
    editable || changed ? <span className={changed ? "f-changed contents" : "contents"}>{element}</span> : element;
  if (!invalid) return marked;
  return (
    <>
      {marked}
      {error?.map((message, i) => (
        <p key={i} className="mt-1 text-xs text-red-600">
          {message}
        </p>
      ))}
    </>
  );
}

// The Add line of a quick-add select (Select's canAdd): the user holds lists.manage_lists. No Soft box has a quick-add URL
// yet, so the flag alone changes nothing today; it is passed so the boxes match Select's rule when one is added.
export function useCanAddLists(): boolean {
  const meta = useMeta();
  return meta.data?.user?.perms.includes("lists.manage_lists") ?? false;
}

// A soft box of the page form (usePageField(name)). Once the page form has loaded and names the field, the box is editable:
// it carries the form's `form="emp-form"`, shows the edit or the stored value, its errors, and the clash choice under it when
// the stored value changed. Until then, and for a name the page form does not have, `fallback` draws (the read-only box of
// the API's value, as before). `label` is the form field's accessible name.
export function PageSoft({
  name,
  label,
  width,
  fallback,
}: {
  name: string;
  label: string;
  width?: string;
  fallback: ReactNode;
}) {
  const box = usePageField(name);
  const canAdd = useCanAddLists();
  if (!box.editable) return <>{fallback}</>;
  return (
    <>
      <Soft
        label={label}
        kind={box.kind as SoftKind}
        value={box.value}
        choice={box.choice}
        combo={box.combo}
        checked={box.value === "on"}
        width={width}
        name={box.name}
        form="emp-form"
        onChange={(_, next) => box.set(next)}
        error={box.error}
        changed={box.changed}
        choices={box.choices}
        canAdd={canAdd}
      />
      {box.conflict !== undefined ? (
        <ClashChoice name={box.name} theirs={box.conflict} value={box.resolve} onPick={box.setResolve} />
      ) : null}
    </>
  );
}
