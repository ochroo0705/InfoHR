import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useCreateLeaveRequest,
  useLeaveRequestOptions,
  type LeaveRequestFormIn,
  type LeaveWriteResultOut,
} from "../../api/leaveRequests";
import type { ApiFailure } from "../../api/mutate";
import type { components } from "../../api/schema";
import { confirm } from "../../widgets/confirm";
import { DatePicker } from "../../widgets/DatePicker";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select, type SelectOption } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { LeaveCheck } from "../leave/LeaveCheck";

// The staff request pop-up: a person asks for leave for their own record (port of
// app/leave/templates/leave/_request_form.html and app/leave/forms.py's request form). The labels, the ` *` marks, the
// grey sentence and the buttons are copied from the template. The pop-up takes only onClose: the list refetches by the
// hook's invalidation. A refused save (ok false) keeps every typed value and shows the messages.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const TITLE = "Чөлөө хүсэх";
const WAIT_TEXT = "Хүсэлт батлагдах хүртэл хүлээгдэнэ. Бүх шат батлагдсаны дараа чөлөө бүртгэгдэнэ.";
type LeaveChoice = components["schemas"]["LeaveChoiceOut"];

// The fields of the form, in the order of the template. Every value is text; "" is an empty box.
export type LeaveRequestValues = {
  leave_type: string;
  start_date: string;
  end_date: string;
  note: string;
};
type FieldName = keyof LeaveRequestValues;
const FIELD_NAMES: FieldName[] = ["leave_type", "start_date", "end_date", "note"];

export interface LeaveRequestModalProps {
  onClose: () => void;
}

// Empty box: null (the server gives its own «required» text). A number box is read as a whole number.
const idOrNull = (text: string): number | null => (text.trim() === "" ? null : Number(text));
const textOrNull = (text: string): string | null => (text.trim() === "" ? null : text);
const choiceList = (list: LeaveChoice[]): SelectOption[] => [
  { value: "", label: "" },
  ...list.map((item) => ({ value: String(item.value), label: item.label })),
];

// A whole YYYY-MM-DD that is a real calendar date. A partial keystroke never is.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
function isWholeDate(text: string): boolean {
  if (!ISO_DATE.test(text)) return false;
  const [year, month, day] = text.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

// The values the live check reads are the same as the last commit's.
const sameChecked = (a: LeaveRequestValues, b: LeaveRequestValues): boolean =>
  FIELD_NAMES.every((name) => a[name] === b[name]);

// The body of a request: the four boxes as posted. There is no employee: the server uses the user's own record.
function requestBody(values: LeaveRequestValues): LeaveRequestFormIn {
  return {
    leave_type: idOrNull(values.leave_type),
    start_date: textOrNull(values.start_date),
    end_date: textOrNull(values.end_date),
    note: values.note,
  };
}

// The pop-up's first values come from the server's options: the form starts empty, the types are loaded first.
export function LeaveRequestModal({ onClose }: LeaveRequestModalProps) {
  const options = useLeaveRequestOptions();
  const data = options.data;
  if (data === undefined) {
    return (
      <Modal open onClose={onClose} title={TITLE} noAnim width="max-w-lg">
        {options.isError ? (
          <p role="alert" className="text-sm text-red-600">
            {LOAD_FAILED_TEXT}
          </p>
        ) : null}
      </Modal>
    );
  }
  return <RequestForm types={data.types} onClose={onClose} />;
}

function RequestForm({ types, onClose }: { types: LeaveChoice[]; onClose: () => void }) {
  const create = useCreateLeaveRequest();
  const initial: LeaveRequestValues = { leave_type: "", start_date: "", end_date: "", note: "" };
  const [values, setValues] = useState<LeaveRequestValues>(initial);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);
  const ids = useId();
  // The values the live check reads: set only on a commit (a select pick, a whole date, leaving the note box).
  const [checked, setChecked] = useState<LeaveRequestValues>(initial);

  const dirty = FIELD_NAMES.some((name) => values[name] !== initial[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: FieldName, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // A commit hands the form's values to the check; the same values again change nothing.
  const commit = (next: LeaveRequestValues) => setChecked((prev) => (sameChecked(prev, next) ? prev : next));
  const pick = (name: "leave_type", value: string) => {
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
      const result: LeaveWriteResultOut = await create.mutateAsync(requestBody(values));
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
      title={TITLE}
      // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell, as LeaveFormModal).
      noAnim
      width="max-w-lg"
    >
      <p className="mb-3 text-xs text-slate-500">{WAIT_TEXT}</p>
      <form noValidate className="space-y-3" onSubmit={save}>
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
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
        <div className="block text-sm">
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
        <LeaveCheck
          values={{
            employee: "",
            leave_type: checked.leave_type,
            start_date: checked.start_date,
            end_date: checked.end_date,
            note: checked.note,
          }}
          mode="request"
        />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            Болих
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Хүсэлт илгээх
          </button>
        </div>
      </form>
    </Modal>
  );
}
