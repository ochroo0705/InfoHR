import { useEmployeeSalary } from "../../api/employee";
import type { components } from "../../api/schema";
import { PageSoft, Soft } from "./Soft";
import { ScrollFloat } from "../../widgets/Scrollbar";
import { useCorrectionPopup } from "./CorrectionModal";
import { useEmployeePopups } from "./EmployeePopups";

// Port of `employees/_tab_salary.html`: the pay heading with «Цалин тогтоох», the current pay, the pay history table and
// the «Банк, даатгал» block. Classes, Mongolian text, element order and ids are copied from the template. React renders
// only the strings and flags the API sends (current, missing_label, set_label, period_text, scheduled_label, action_label,
// action_class, and each bank box's kind and value). «Цалин тогтоох» and a row's «Засвар» open the correction pop-up
// (CorrectionModal, Task 16a). A row's «Цуцлах» opens the event cancel pop-up (the provider's openEventCancel, with the
// row's event id from the API).

type Salary = components["schemas"]["EmployeeSalaryOut"];
type BankField = components["schemas"]["EmployeeBankFieldOut"];

// One soft box of the bank block, as the widget `kind` gives it (`Soft`). Read-only: the API's value and text.
function BankSoft({ field }: { field: BankField }) {
  return (
    <Soft
      label={field.aria_label}
      kind={field.kind}
      value={field.value}
      choice={field.choice}
      checked={field.checked}
    />
  );
}

// A box of the bank block for a user who may edit it: bound to the page form by its name (PageSoft; the select takes its
// options from the page form, the checkbox is "on" or ""). Until the page form has loaded, it is the read-only box above.
function BankBox({ field }: { field: BankField }) {
  return <PageSoft name={field.name} label={field.aria_label} fallback={<BankSoft field={field} />} />;
}

function SalaryBody({ salary, pk }: { salary: Salary; pk: number }) {
  const { openCorrection, correctionModal } = useCorrectionPopup(pk);
  const { openEventCancel } = useEmployeePopups();
  return (
    <>
      <div className="flex items-baseline gap-3">
        <h3 className="sec-title">
          Үндсэн цалин
          {salary.missing_label && (
            <>
              {" "}
              <span className="ml-1 text-sm font-normal text-slate-400">{salary.missing_label}</span>
            </>
          )}
        </h3>
        {salary.set_label && (
          <button
            type="button"
            onClick={() => openCorrection("salary/set")}
            className="ml-auto rounded px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-50"
          >
            {salary.set_label}
          </button>
        )}
      </div>
      {salary.current && (
        <div className="mt-2 flex items-baseline gap-3">
          <p className="text-sm text-slate-500">Одоогийн</p>
          <p className="text-2xl font-semibold">{salary.current}</p>
        </div>
      )}
      {salary.has_rows && (
        <ScrollFloat className="ptable">
          <table>
            <thead>
              <tr>
                <th>Хугацаа</th>
                <th>Цалин</th>
                <th>Төрөл</th>
                <th className="w-px"></th>
              </tr>
            </thead>
            <tbody>
              {salary.rows.map((row) => (
                <tr key={row.pk}>
                  <td>{row.period_text}</td>
                  <td>{row.amount}</td>
                  <td>
                    {row.label}
                    {row.scheduled_label && (
                      <>
                        {" "}
                        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800">
                          {row.scheduled_label}
                        </span>
                      </>
                    )}
                  </td>
                  <td className="text-right whitespace-nowrap">
                    {row.action_label && (
                      <button
                        type="button"
                        onClick={() => {
                          // «Засвар» (correctable) opens the correction pop-up; «Цуцлах» (cancellable) opens the event
                          // cancel pop-up, and only with the event id the API sends.
                          if (row.correctable) openCorrection(`salary/${row.pk}/correct`);
                          else if (row.cancellable && row.event_id != null) openEventCancel(row.event_id);
                        }}
                        className={row.action_class}
                      >
                        {row.action_label}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollFloat>
      )}
      <h3 className="sec-title mt-10 mb-3">Банк, даатгал</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        {salary.bank_fields.map((field) => (
          <div key={field.label}>
            <dt className="text-slate-500">{field.label}</dt>
            <dd>{salary.editable ? <BankBox field={field} /> : field.text}</dd>
          </div>
        ))}
      </dl>
      {correctionModal}
    </>
  );
}

// Port of the Salary tab body. Nothing draws before the salary data arrives. A failed request shows the section's error
// line, as the other step-2 screens do. The section is mounted only when the header says the user may view salary.
export function SalarySection({ pk }: { pk: number }) {
  const query = useEmployeeSalary(pk);
  const salary = query.data;
  return (
    <>
      {query.error ? <p className="mb-3 text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p> : null}
      {salary ? <SalaryBody salary={salary} pk={pk} /> : null}
    </>
  );
}
