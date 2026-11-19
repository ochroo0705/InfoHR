import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import type { FormValues } from "./FormFields";
import { OrderFields } from "./OrderFields";

// The order block (`employees/_order_fields.html`): the heading «Тушаал · <note>», the order-level messages in red, then the
// shared OrderFields. The hire page and the event pop-up both draw it. The caller picks the fields and their order, and
// passes the server's note; this block decides no rule and no text of its own.
// Callers must update their state with a functional updater (see OrderFields).

export type OrderBlockProps = {
  // The heading note, as the server words it (`order_note` of the form, or the section's note).
  note: string;
  // The order-level messages (Django's `order_form.non_field_errors`), drawn above the boxes.
  formErrors?: string[];
  // The boxes to draw, in order.
  fields: EmployeeFormFieldOut[];
  // The current text per field name.
  values: FormValues;
  // The messages per field name.
  errors: Record<string, string[]>;
  onChange: (name: string, value: string) => void;
};

export function OrderBlock({ note, formErrors = [], fields, values, errors, onChange }: OrderBlockProps) {
  return (
    <div className="space-y-2 md:col-span-2">
      <h3 className="border-b border-slate-200 pb-1 text-sm font-semibold text-slate-800">
        Тушаал <span className="font-normal text-slate-500">· {note}</span>
      </h3>
      {formErrors.map((message, i) => (
        <p key={i} className="rounded bg-red-50 p-2 text-sm text-red-700">
          {message}
        </p>
      ))}
      <OrderFields fields={fields} values={values} errors={errors} onChange={onChange} />
    </div>
  );
}
