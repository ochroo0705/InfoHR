import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useCreateLeave,
  useLeaveEdit,
  useLeaveOptions,
  useUpdateLeave,
  type LeaveLoaded,
  type LeaveUpdateIn,
  type LeaveWriteIn,
  type LeaveWriteResultOut,
} from "../../api/leave";
import type { ApiFailure } from "../../api/mutate";
import type { components } from "../../api/schema";
import { AppLink } from "../../lib/AppLink";
import { confirm } from "../../widgets/confirm";
import { DatePicker } from "../../widgets/DatePicker";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select, type SelectOption } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { LeaveCheck } from "./LeaveCheck";
import { STALE_REOPEN_TEXT, STALE_TEXT } from "./leaveTexts";

// The add and edit pop-up of one leave (port of app/leave/templates/leave/_form.html and app/leave/forms.py LeaveForm).
// Labels, the ` *` marks, the notes and the buttons are copied from the template. The pop-up takes no router or page
// state: the page passes the mode and onClose. A saved row closes the pop-up; the list refetches by the hook's
// invalidation. A refused save (ok false) keeps every typed value and shows the messages.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
type LeaveChoice = components["schemas"]["LeaveChoiceOut"];

// The fields of the form, in the order of _form.html. Every value is text; "" is an empty box.
export type LeaveFormValues = {
  employee: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  note: string;
  override_reason: string;
};
type FieldName = keyof LeaveFormValues;
const FIELD_NAMES: FieldName[] = ["employee", "leave_type", "start_date", "end_date", "note", "override_reason"];

// The add pop-up's prefill, from the list's query (the same names as the Django new/ address). `from` is "assistant"
// when the pop-up was opened from the assistant.
export type LeavePrefill = {
  employee?: number | null;
  type?: number | null;
  start?: string;
  end?: string;
  from?: string;
};

export type LeaveFormMode = ({ kind: "add" } & LeavePrefill) | { kind: "edit"; id: number };

export interface LeaveFormModalProps {
  mode: LeaveFormMode;
  // The list's can_settings: the not-configured notice links to the leave settings only then (_not_configured.html).
  canSettings?: boolean;
  onClose: () => void;
}

// Empty box: null (the server gives its own «required» text). A number box is read as a whole number.
const idOrNull = (text: string): number | null => (text.trim() === "" ? null : Number(text));
const textOrNull = (text: string): string | null => (text.trim() === "" ? null : text);
const choiceList = (list: LeaveChoice[]): SelectOption[] => [
  { value: "", label: "" },
  ...list.map((item) => ({ value: String(item.value), label: item.label })),
];
const textOf = (value: number | null | undefined): string => (value === null || value === undefined ? "" : String(value));

// A whole YYYY-MM-DD that is a real calendar date. A partial keystroke never is.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
function isWholeDate(text: string): boolean {
  if (!ISO_DATE.test(text)) return false;
  const [year, month, day] = text.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

// The values the live check reads are the same as the last commit's.
const sameChecked = (a: LeaveFormValues, b: LeaveFormValues): boolean => FIELD_NAMES.every((name) => a[name] === b[name]);

// The body of a write: every box as posted (React sends null for an empty one).
function writeBody(values: LeaveFormValues): LeaveWriteIn {
  return {
    employee: idOrNull(values.employee),
    leave_type: idOrNull(values.leave_type),
    start_date: textOrNull(values.start_date),
    end_date: textOrNull(values.end_date),
    note: values.note,
    override_reason: values.override_reason,
  };
}

// What the form shows and sends, the same for add and edit; the modes differ only in where the data comes from.
interface LeaveFormProps {
  title: string;
  // Edit mode: the leave's id (the check sends it). The row as loaded is sent back by the submit callback.
  leaveId?: number;
  initial: LeaveFormValues;
  employees: LeaveChoice[];
  types: LeaveChoice[];
  notConfigured: string;
  canSettings: boolean;
  assisted: { person_line: string; filled_line: string } | null;
  onClose: () => void;
  // Sends the form; resolves with the server's answer (ok true saves, ok false refuses) or rejects on a failed request.
  submit: (values: LeaveFormValues) => Promise<LeaveWriteResultOut>;
}

function LeaveForm({
  title,
  leaveId,
  initial,
  employees,
  types,
  notConfigured,
  canSettings,
  assisted,
  onClose,
  submit,
}: LeaveFormProps) {
  const isEdit = leaveId !== undefined;
  const [values, setValues] = useState<LeaveFormValues>(initial);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);
  const ids = useId();
  // The values the live check reads: set only on a commit (a select pick, a whole date, leaving the note or reason box).
  const [checked, setChecked] = useState<LeaveFormValues>(initial);

  const dirty = FIELD_NAMES.some((name) => values[name] !== initial[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: FieldName, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // A commit hands the form's values to the check; the same values again change nothing.
  const commit = (next: LeaveFormValues) => setChecked((prev) => (sameChecked(prev, next) ? prev : next));
  const pick = (name: "employee" | "leave_type", value: string) => {
    setField(name, value);
    commit({ ...values, [name]: value });
  };
  // A whole date, or an empty box (which clears the check), commits. A partial date only fills the box.
  const onDate = (name: "start_date" | "end_date", value: string) => {
    setField(name, value);
    if (value === "" || isWholeDate(value)) commit({ ...values, [name]: value });
  };

  // A refused save: the field messages under their boxes, the others (and the stray ones) in the red box at the top.
  // A refusal with no message at all gets the general save text.
  const refuse = ({ fieldErrors: fe, formErrors }: { fieldErrors: Record<string, string[]>; formErrors: string[] }) => {
    const stray = Object.entries(fe)
      .filter(([key]) => !FIELD_NAMES.includes(key as FieldName))
      .flatMap(([, list]) => list);
    const top = [...formErrors, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const result = await submit(values);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
        onClose();
        return;
      }
      const messages = [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
      refuse({ fieldErrors: result.field_errors, formErrors: messages });
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      refuse({ fieldErrors: failure.fieldErrors ?? {}, formErrors: failure.formErrors ?? [] });
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty: dirty || hasErrors, leaving: false, close: onClose }, (message) =>
      confirm(message, { ok: "Хаах" }),
    );
  };

  // A field's errors sit under its label box, outside the label, with an id the control names in aria-describedby.
  const errorId = (name: FieldName) => `${ids}-${name}-error`;
  const describedBy = (name: FieldName) => ((fieldErrors[name]?.length ?? 0) > 0 ? errorId(name) : undefined);
  const errorsOf = (name: FieldName): ReactNode =>
    (fieldErrors[name]?.length ?? 0) > 0 ? (
      <div id={errorId(name)}>
        {(fieldErrors[name] ?? []).map((message, index) => (
          <span key={index} className="block text-xs text-red-600">
            {message}
          </span>
        ))}
      </div>
    ) : null;
  const invalid = (name: FieldName) => (fieldErrors[name]?.length ?? 0) > 0 || undefined;

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={hasErrors ? serverErrors : null}
      title={title}
      // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell, as SlotFormModal).
      noAnim
    >
      <form noValidate className="space-y-3" onSubmit={save}>
        {notConfigured ? (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
            {notConfigured}
            {canSettings ? (
              <>
                {" "}
                <AppLink to="/leave/settings/" className="underline">
                  Тохируулах
                </AppLink>
              </>
            ) : null}
          </p>
        ) : null}
        {assisted ? (
          <p className="rounded-lg bg-slate-50 p-2 text-sm text-slate-700">
            <span className="font-medium">{assisted.person_line}</span>
            <br />
            <span className="text-xs text-slate-500">{assisted.filled_line}</span>
          </p>
        ) : null}
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
            {isEdit && topErrors.includes(STALE_TEXT) ? <p>{STALE_REOPEN_TEXT}</p> : null}
          </div>
        ) : null}
        <div className="grid gap-3 md:grid-cols-2">
          <div className="block text-sm">
            <label className="block">
              Ажилтан *
              <Select
                name="employee"
                value={values.employee}
                onChange={(value) => pick("employee", value)}
                options={choiceList(employees)}
                search
                required
                disabled={isEdit}
                className={BOXED}
                invalid={invalid("employee")}
                describedBy={describedBy("employee")}
              />
            </label>
            {errorsOf("employee")}
          </div>
          <div className="block text-sm">
            <label className="block">
              Төрөл *
              <Select
                name="leave_type"
                value={values.leave_type}
                onChange={(value) => pick("leave_type", value)}
                options={choiceList(types)}
                search={false}
                required
                className={BOXED}
                invalid={invalid("leave_type")}
                describedBy={describedBy("leave_type")}
              />
            </label>
            {errorsOf("leave_type")}
          </div>
          <div className="block text-sm">
            <label className="block">
              Эхлэх *
              <DatePicker
                name="start_date"
                value={values.start_date}
                onChange={(value) => onDate("start_date", value)}
                required
                className={BOXED}
                invalid={invalid("start_date")}
                describedBy={describedBy("start_date")}
              />
            </label>
            {errorsOf("start_date")}
          </div>
          <div className="block text-sm">
            <label className="block">
              Дуусах *
              <DatePicker
                name="end_date"
                value={values.end_date}
                onChange={(value) => onDate("end_date", value)}
                required
                className={BOXED}
                invalid={invalid("end_date")}
                describedBy={describedBy("end_date")}
              />
            </label>
            {errorsOf("end_date")}
          </div>
          <div className="block text-sm md:col-span-2">
            <label className="block">
              Тайлбар
              <textarea
                name="note"
                rows={2}
                value={values.note}
                onChange={(event) => setField("note", event.target.value)}
                onBlur={() => commit(values)}
                aria-invalid={invalid("note")}
                aria-describedby={describedBy("note")}
                className={BOXED}
              />
            </label>
            {errorsOf("note")}
          </div>
          <div className="block text-sm md:col-span-2">
            <label className="block">
              Үлдэгдэл хүрэлцэхгүй бол шалтгаан
              <input
                type="text"
                name="override_reason"
                value={values.override_reason}
                onChange={(event) => setField("override_reason", event.target.value)}
                onBlur={() => commit(values)}
                aria-invalid={invalid("override_reason")}
                aria-describedby={describedBy("override_reason")}
                className={BOXED}
              />
            </label>
            {errorsOf("override_reason")}
          </div>
        </div>
        <LeaveCheck values={checked} leaveId={leaveId ?? null} />
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={cancel}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
          >
            Болих
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Хадгалах
          </button>
        </div>
      </form>
    </Modal>
  );
}

// The add pop-up: the choices and the first values come from the server, prefilled by the list's query.
function AddLeave({ prefill, canSettings, onClose }: { prefill: LeavePrefill; canSettings: boolean; onClose: () => void }) {
  const options = useLeaveOptions({
    employee: textOf(prefill.employee),
    type: textOf(prefill.type),
    start: prefill.start,
    end: prefill.end,
    from: prefill.from,
  });
  const create = useCreateLeave();
  const data = options.data;
  if (data === undefined) return <LoadingModal title="Чөлөө бүртгэх" failed={options.isError} onClose={onClose} />;
  return (
    <LeaveForm
      title="Чөлөө бүртгэх"
      initial={{
        employee: textOf(data.initial.employee),
        leave_type: textOf(data.initial.leave_type),
        start_date: data.initial.start_date,
        end_date: data.initial.end_date,
        note: "",
        override_reason: "",
      }}
      employees={data.employees}
      types={data.types}
      notConfigured={data.not_configured}
      canSettings={canSettings}
      assisted={data.assisted}
      onClose={onClose}
      submit={(values) => create.mutateAsync(writeBody(values))}
    />
  );
}

// The edit pop-up: the leave's own values, and its row as loaded, which goes back with the save. The employee is
// shown but cannot change (the Django edit posts the leave's own employee).
function EditLeave({ id, canSettings, onClose }: { id: number; canSettings: boolean; onClose: () => void }) {
  const edit = useLeaveEdit(id);
  const update = useUpdateLeave(id);
  const data = edit.data;
  if (data === undefined) return <LoadingModal title="Чөлөө засах" failed={edit.isError} onClose={onClose} />;
  const loaded: LeaveLoaded = data.loaded;
  return (
    <LeaveForm
      title="Чөлөө засах"
      leaveId={data.id}
      initial={{
        employee: textOf(data.initial.employee),
        leave_type: textOf(data.initial.leave_type),
        start_date: data.initial.start_date,
        end_date: data.initial.end_date,
        note: data.initial.note,
        override_reason: data.initial.override_reason,
      }}
      employees={data.employees}
      types={data.types}
      notConfigured={data.not_configured}
      canSettings={canSettings}
      assisted={null}
      onClose={onClose}
      submit={(values) => {
        const body: LeaveUpdateIn = { ...writeBody(values), loaded };
        return update.mutateAsync(body);
      }}
    />
  );
}

// While the first values load (or when they fail): the same pop-up shell with a short text.
function LoadingModal({ title, failed, onClose }: { title: string; failed: boolean; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={title} noAnim>
      {failed ? (
        <p role="alert" className="text-sm text-red-600">
          {LOAD_FAILED_TEXT}
        </p>
      ) : null}
    </Modal>
  );
}

// The leave pop-up: add (with the list's prefill) or edit (by the leave's id).
export function LeaveFormModal({ mode, canSettings = false, onClose }: LeaveFormModalProps) {
  if (mode.kind === "edit") return <EditLeave id={mode.id} canSettings={canSettings} onClose={onClose} />;
  const prefill: LeavePrefill = mode;
  return <AddLeave prefill={prefill} canSettings={canSettings} onClose={onClose} />;
}
