import type { ReactNode, RefObject } from "react";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import { BOXED, BoxedControl } from "../../widgets/FormFields";

// One field of the add-employee page, drawn as `employees/_add_field.html` draws it. The server describes the field
// (`field`, see app/employees/services/form_schema.py); React draws the look and the controls only, it decides nothing.
// - A checkbox: `label.flex` with the box and the label text, the errors inside the label (no star, no help).
// - Any other kind: `label.block` with the text, " *" when required, the control, the help line when there is one, and
//   the errors under it.
// - Kind "file" (the photo): a real file input with `accept="image/*"`; the chosen File goes to `onFile`.
// - `afterControl` is drawn right after the control, inside the label (the register check line sits there in Django).
// Values are strings as a browser posts them (see FormFields).

export type HireFieldProps = {
  field: EmployeeFormFieldOut;
  // The current text of the field ("on" or "" for a checkbox).
  value: string;
  // Called with each change of a value-kind control.
  onChange: (value: string) => void;
  // Called with the chosen file of a "file" field (null when the choice is cleared). Not used for other kinds.
  onFile?: (file: File | null) => void;
  // Django's messages for this field.
  errors?: string[];
  // Drawn right after the control, inside the label.
  afterControl?: ReactNode;
  // Receives the control's native element (the input, textarea, plain select or the file input of a "file" field), so
  // the caller can focus the first error. Not set for Select, DatePicker and MoneyInput, which keep their own element.
  controlRef?: RefObject<HTMLElement | null> | ((el: HTMLElement | null) => void);
};

// The photo box: the Django ImageField widget with the page's BOXED class.
function FileControl({
  name,
  onFile,
  inputRef,
}: {
  name: string;
  onFile?: (file: File | null) => void;
  inputRef?: (el: HTMLElement | null) => void;
}) {
  return (
    <input
      ref={inputRef}
      type="file"
      name={name}
      accept="image/*"
      className={BOXED}
      onChange={(e) => onFile?.(e.target.files?.[0] ?? null)}
    />
  );
}

// A ref object or a callback, as the native control expects it.
function assignRef(target: HireFieldProps["controlRef"]) {
  return (el: HTMLElement | null) => {
    if (typeof target === "function") target(el);
    else if (target) target.current = el;
  };
}

export function HireField({ field, value, onChange, onFile, errors = [], afterControl, controlRef }: HireFieldProps) {
  const ref = controlRef ? assignRef(controlRef) : undefined;

  if (field.kind === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <BoxedControl
          field={field}
          value={value}
          invalid={errors.length > 0}
          onChange={(_name, next) => onChange(next)}
          firstRef={ref}
        />
        {field.label}
        {afterControl}
        {errors.map((message, i) => (
          <span key={i} className="field-error text-xs text-red-600">
            {message}
          </span>
        ))}
      </label>
    );
  }

  return (
    <label className="block text-sm">
      {field.label}
      {field.required ? " *" : null}
      {field.kind === "file" ? (
        <FileControl name={field.name} onFile={onFile} inputRef={ref} />
      ) : (
        <BoxedControl
          field={field}
          value={value}
          invalid={errors.length > 0}
          onChange={(_name, next) => onChange(next)}
          firstRef={ref}
        />
      )}
      {afterControl}
      {field.help ? <span className="block text-xs text-slate-500">{field.help}</span> : null}
      {errors.map((message, i) => (
        <span key={i} className="field-error text-xs text-red-600">
          {message}
        </span>
      ))}
    </label>
  );
}
