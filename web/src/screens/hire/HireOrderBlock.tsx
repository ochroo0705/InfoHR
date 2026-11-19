import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import type { HireSectionOut } from "../../api/hire";
import { OrderBlock } from "../../widgets/OrderBlock";
import type { FormValues } from "../../widgets/FormFields";

// The order block of the add-employee page (`employees/_order_fields.html`). The server names the boxes and their order
// (`section.names`) and the heading note (`section.note`); the shared OrderBlock draws the heading, the form's non-field
// messages and the boxes.
// Callers must update their state with a functional updater (see OrderFields).

export type HireOrderBlockProps = {
  section: HireSectionOut;
  // Every described field of the form; the block picks the ones named in `section.names`, in that order.
  fields: EmployeeFormFieldOut[];
  // The current text per field name.
  values: FormValues;
  // Django's messages per field name.
  errors: Record<string, string[]>;
  onChange: (name: string, value: string) => void;
  // The form's non-field messages (Django's `order_form.non_field_errors`), drawn above the boxes.
  formErrors?: string[];
};

export function HireOrderBlock({ section, fields, values, errors, onChange, formErrors = [] }: HireOrderBlockProps) {
  const picked = section.names
    .map((name) => fields.find((field) => field.name === name))
    .filter((field): field is EmployeeFormFieldOut => field !== undefined);

  return (
    <OrderBlock
      note={section.note}
      formErrors={formErrors}
      fields={picked}
      values={values}
      errors={errors}
      onChange={onChange}
    />
  );
}
