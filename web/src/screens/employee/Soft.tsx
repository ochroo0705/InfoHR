// The soft box of a tab's field grid (`hr.SOFT` and the widget kinds of `hr.field`, UI_RULES §2e). Shared by the Work,
// Salary and Personal tabs. Read-only until step 3b: a select draws only its current option and stops mousedown and keydown, so it
// looks the same but does not open (disabled would change the look). `label` is the form field's accessible name
// (`aria_label` from the API), never the row's text. A multi-line box (textarea) is one line tall and grows with its text
// (`hr.field`: rows="1", resize-none, field-sizing content).

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
}) {
  if (kind === "checkbox") {
    return (
      <input
        type="checkbox"
        readOnly
        checked={checked}
        aria-label={label}
        autoComplete="off"
        className="h-4 w-4 accent-violet-600"
      />
    );
  }
  const className = `${width} ${SOFT}`;
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
  if (kind === "date") {
    // datepicker.js turns every date box into a text box in a span.dp-wrap, with its calendar button (dp-icon) inside.
    // Read-only here: the button draws the same icon and does nothing (the calendar is step 3b).
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
