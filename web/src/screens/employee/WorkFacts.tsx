import type { EmployeeWorkOut, WorkFieldOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { Soft } from "./Soft";

// Port of the job and contract facts of `_tab_work.html`: «Албан тушаал, байршил», the second row (хавсарсан, Алба,
// Хэсэг, Салбар), «Гэрээ», «Ажлын нөхцөл, цаг» and «Хуучин системээс (MACS)». The setup card (Task 11) comes before it,
// and the waiting and history tables (WorkJobs) after it. Classes, Mongolian text, element order and data-field hooks
// are copied from the template. React renders only the strings and flags the API sends: the widget for a soft box
// comes from `kind` (select, date, number). Every write opens the Django employee page (openLegacyEmployee, ruling D2).

type Work = EmployeeWorkOut;

const CHANGE_TITLE = "Өөрчлөлт бүртгэж солино (тушаалтай)";

// The API's soft field as a shared soft box: its accessible name is the form field's label (`aria_label`).
function SoftField({ field, width }: { field: WorkFieldOut; width?: string }) {
  return (
    <Soft
      label={field.aria_label}
      kind={field.kind as "select" | "date" | "number"}
      value={field.value}
      choice={field.choice}
      combo={field.combo}
      width={width}
    />
  );
}

// A field that is a soft box for a user who can manage the employee, and plain text otherwise (the template's branch).
function Editable({ manage, field, width }: { manage: boolean; field: WorkFieldOut; width?: string }) {
  return manage ? <SoftField field={field} width={width} /> : <>{field.text}</>;
}

// The «өөрчлөх» chip beside a field (`_change_chip.html`): a legacy pop-up, a full page load (ruling D2).
function ChangeChip({ pk }: { pk: number }) {
  return (
    <button
      type="button"
      onClick={() => openLegacyEmployee(pk)}
      title={CHANGE_TITLE}
      className="ml-1 inline-flex items-center gap-1 rounded-md border border-violet-200 px-1.5 py-0.5 align-middle text-xs text-violet-700 hover:border-violet-400 hover:bg-violet-50"
    >
      <svg
        viewBox="0 0 16 16"
        width="12"
        height="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 5.5h9.5L10 3M13 10.5H3.5L6 13" />
      </svg>
      өөрчлөх
    </button>
  );
}

export function WorkFacts({ work, pk }: { work: Work; pk: number }) {
  const manage = work.can_manage;
  return (
    <>
      <h3 className="sec-title mt-2 mb-3">Албан тушаал, байршил</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        <div data-field="position">
          <dt className="text-slate-500">Албан тушаал</dt>
          <dd>
            {work.position}
            {work.transfer_chip && <ChangeChip pk={pk} />}
          </dd>
        </div>
        <div data-field="department">
          <dt className="text-slate-500">Хэлтэс</dt>
          <dd>
            {work.department}
            {work.transfer_chip && <ChangeChip pk={pk} />}
          </dd>
        </div>
        <div data-field="manager">
          <dt className="text-slate-500">Шууд удирдлага</dt>
          <dd>
            {work.manager}
            {work.transfer_chip && <ChangeChip pk={pk} />}
          </dd>
        </div>
      </dl>
      <dl className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        <div>
          <dt className="text-slate-500">Албан тушаал (хавсарсан)</dt>
          <dd>
            <Editable manage={manage} field={work.second_position} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Алба</dt>
          <dd>
            <Editable manage={manage} field={work.office} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Хэсэг</dt>
          <dd>
            <Editable manage={manage} field={work.section} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Салбар</dt>
          <dd>
            <Editable manage={manage} field={work.branch} />
          </dd>
        </div>
      </dl>
      <h3 className="sec-title mt-10 mb-3">Гэрээ</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        <div data-field="employee_type">
          <dt className="text-slate-500">Ажилтны төрөл</dt>
          <dd>{work.employee_type}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Гэрээ</dt>
          <dd>
            <span data-field="contract_type">{work.contract_type}</span>{" "}
            <span data-field="contract_no">{work.contract_no}</span>
            {work.contract_chip && <ChangeChip pk={pk} />}
          </dd>
        </div>
        <div data-field="contract_start">
          <dt className="text-slate-500">Гэрээний хугацаа</dt>
          <dd>
            {work.contract_start} – <span data-field="contract_end">{work.contract_end}</span>
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Гэрээ дуусах</dt>
          <dd>{work.contract_end_label}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Туршилт дуусах</dt>
          <dd>
            <Editable manage={manage} field={work.probation_end} />
          </dd>
        </div>
        {work.first_hire_date && (
          <div>
            <dt className="text-slate-500">Анх ажилд орсон огноо</dt>
            <dd>
              <SoftField field={work.first_hire_date} />
            </dd>
          </div>
        )}
      </dl>
      <h3 className="sec-title mt-10 mb-3">Ажлын нөхцөл, цаг</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        <div>
          <dt className="text-slate-500">Ажлын төрөл</dt>
          <dd>
            <Editable manage={manage} field={work.job_type} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Ажлын хэлбэр</dt>
          <dd>
            <Editable manage={manage} field={work.job_figure} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Ажлын нөхцөл</dt>
          <dd>
            <Editable manage={manage} field={work.work_conditions} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Цагийн хуваарь</dt>
          <dd>
            <Editable manage={manage} field={work.work_schedule} />
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Салбарт ажилласан жил</dt>
          <dd>
            <Editable manage={manage} field={work.sector_years} width="w-20" />
          </dd>
        </div>
      </dl>
      <h3 className="sec-title mt-10 mb-3">Хуучин системээс (MACS)</h3>
      <p className="-mt-2 mb-3 text-sm text-slate-500">MACS-аас шилжүүлсэн мэдээлэл</p>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm md:grid-cols-3">
        <div>
          <dt className="text-slate-500">MACS гэрээний дугаар</dt>
          <dd>{work.macs_contract_no}</dd>
        </div>
        <div>
          <dt className="text-slate-500">MACS гэрээний хугацаа</dt>
          <dd>{work.macs_contract_period}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Урт амралттай</dt>
          <dd>{work.macs_taken_leave}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Амралтын төрөл</dt>
          <dd>{work.macs_leave_type}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Туршилтын сар (MACS)</dt>
          <dd>{work.macs_probation_months}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Сүүлийн тушаалын дугаар</dt>
          <dd>{work.macs_last_order_no}</dd>
        </div>
        <div className="md:col-span-2">
          <dt className="text-slate-500">Сүүлийн тушаалын агуулга</dt>
          <dd>{work.macs_last_order_text}</dd>
        </div>
      </dl>
    </>
  );
}
