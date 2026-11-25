import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useSaveVacancy,
  useSlotLine,
  useVacancyForm,
  useVacancyOptions,
  type RecruitVacancyFormOut,
  type RecruitVacancyIn,
  type RecruitVacancyOptionsOut,
  type RecruitVacancyUpdateIn,
  type RecruitWriteResultOut,
} from "../../api/recruitment";
import type { ApiFailure } from "../../api/mutate";
import { cn } from "../../lib/utils";
import { confirm } from "../../widgets/confirm";
import { DatePicker } from "../../widgets/DatePicker";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select, type SelectOption } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { SlotLine } from "./SlotLine";

// The add and edit pop-up of a vacancy (port of app/recruitment/templates/recruitment/vacancy_form.html and VacancyForm in
// app/recruitment/forms.py). Labels, help texts and the buttons are copied from the template and the form; the fields come
// in the form's order. A saved vacancy reports its id and closes; a refused save keeps every typed value and shows the
// messages (the service's text on top, a field's message under its box).
//
// Add starts from empty boxes. Edit starts from the vacancy's saved values (GET .../form) and its choices (options with the
// vacancy); the status select is shown only when editing. «Болих» and Escape ask the discard question only when a box
// differs from what the pop-up loaded (the loaded values, or empty for a new vacancy).
//
// The budget line is asked only once a position is chosen, and again after a pause when the position, branch, start or
// headcount changes (300 ms, the latest answer wins: the query key is the settled values).

const TITLE_ADD = "Ажлын байр нээх";
const TITLE_EDIT = "Ажлын байр засах";
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const FORBIDDEN_TEXT = "Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу.";
const NOT_FOUND_TITLE = "Хуудас олдсонгүй";
const NOT_FOUND_TEXT = "Хаяг буруу байна эсвэл хуудас өөр газар шилжсэн байж магадгүй.";
const SETTLE_MS = 300;
// Django's textarea (employees StyledForm: rows 10 becomes 2): one line tall, grows with the text, not resizable.
const AUTO_TEXTAREA = `${BOXED} resize-none [field-sizing:content] min-h-[2.5rem]`;
const HELP_BRANCH = "Орон тооны төлөвлөгөөг салбараар шалгана.";
const HELP_MANAGER = "Ажил хүсэгчийг харж, сэтгэгдэл бичих удирдлага.";
const HELP_START = "Шинэ ажилтан ажилд орохыг хүсэж буй өдөр.";

// The form's values as the boxes hold them. Every value is text; "" is an empty box.
export interface VacancyValues {
  title: string;
  position: string;
  department: string;
  branch: string;
  headcount: string;
  hiring_manager: string;
  deadline: string;
  desired_start: string;
  status: string;
  description: string;
}
type FieldName = keyof VacancyValues;
const FIELD_NAMES: FieldName[] = [
  "title",
  "position",
  "department",
  "branch",
  "headcount",
  "hiring_manager",
  "deadline",
  "desired_start",
  "status",
  "description",
];

// A new vacancy: one headcount, every other box empty (the model's default). Its status is not posted.
export const ADD_VALUES: VacancyValues = {
  title: "",
  position: "",
  department: "",
  branch: "",
  headcount: "1",
  hiring_manager: "",
  deadline: "",
  desired_start: "",
  status: "",
  description: "",
};

// An empty box is null for an id or a number (the server gives its own «required» text).
const idOrNull = (text: string): number | null => {
  if (text.trim() === "") return null;
  const number = Number(text);
  return Number.isNaN(number) ? null : number;
};

// The body of a write: ids as numbers (null when blank), dates as text ("" when blank), as the API takes them.
function bodyOf(values: VacancyValues, edit: boolean): RecruitVacancyIn | RecruitVacancyUpdateIn {
  const body: RecruitVacancyIn = {
    title: values.title,
    position: idOrNull(values.position),
    department: idOrNull(values.department),
    branch: idOrNull(values.branch),
    headcount: idOrNull(values.headcount),
    hiring_manager: idOrNull(values.hiring_manager),
    deadline: values.deadline,
    desired_start: values.desired_start,
    description: values.description,
  };
  return edit ? { ...body, status: values.status } : body;
}

// The saved vacancy's values as the boxes hold them.
export function valuesOf(form: RecruitVacancyFormOut): VacancyValues {
  return {
    title: form.title,
    position: String(form.position),
    department: String(form.department),
    branch: form.branch === null ? "" : String(form.branch),
    headcount: String(form.headcount),
    hiring_manager: form.hiring_manager === null ? "" : String(form.hiring_manager),
    deadline: form.deadline ?? "",
    desired_start: form.desired_start ?? "",
    status: form.status,
    description: form.description,
  };
}

// The messages of a refused answer: the service's own text first, then the form errors.
function messagesOf(result: RecruitWriteResultOut): string[] {
  return [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
}

function choiceList(list: { id: number; label: string }[]): SelectOption[] {
  return [{ value: "", label: "" }, ...list.map((item) => ({ value: String(item.id), label: item.label }))];
}

// The value after a pause: the budget line is asked with it, so a run of keystrokes asks once.
function useSettled(value: string): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [value]);
  return settled;
}

type Errors = Record<string, string[]>;

export interface VacancyModalProps {
  // null: the add pop-up. An id: the edit pop-up of that vacancy.
  vacancyId: number | null;
  onClose: () => void;
  onSaved?: (id: number) => void;
}

interface VacancyFormProps {
  // null: add. An id: edit (the save posts to that vacancy, and the budget line leaves it out of its own count).
  editId: number | null;
  initial: VacancyValues;
  options: RecruitVacancyOptionsOut;
  onClose: () => void;
  onSaved?: (id: number) => void;
}

// The loaded form. Its typed values live here, so a refused save keeps them.
function VacancyForm({ editId, initial, options, onClose, onSaved }: VacancyFormProps) {
  const edit = editId !== null;
  const save = useSaveVacancy(editId);
  const ids = useId();
  const [values, setValues] = useState<VacancyValues>(initial);
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  // Dirty means: a box differs from what the pop-up loaded (empty for a new vacancy).
  const dirty = FIELD_NAMES.some((name) => values[name] !== initial[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: FieldName, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) =>
      name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev,
    );
  };

  // The budget line: asked once a position is chosen, for the settled values.
  const slotPosition = useSettled(values.position);
  const slotBranch = useSettled(values.branch);
  const slotStart = useSettled(values.desired_start);
  const slotHeadcount = useSettled(values.headcount);
  const slot = useSlotLine({
    position: slotPosition,
    branch: slotBranch,
    desired_start: slotStart,
    headcount: slotHeadcount,
    vacancy: editId === null ? undefined : String(editId),
  });

  // A refused save: the field messages under their boxes; the form's own and any stray field message at the top. A
  // refusal with no message at all gets the general save text.
  const refuse = (fe: Errors, messages: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => !FIELD_NAMES.includes(key as FieldName))
      .flatMap(([, list]) => list);
    const top = [...messages, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const result = await save.mutateAsync(bodyOf(values, edit));
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
        const savedId = "id" in result && typeof result.id === "number" ? result.id : editId;
        if (savedId !== null) onSaved?.(savedId);
        onClose();
        return;
      }
      refuse(result.field_errors, messagesOf(result));
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
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

  const errorId = (name: FieldName) => `${ids}-${name}-error`;
  const describedBy = (name: FieldName) => ((fieldErrors[name]?.length ?? 0) > 0 ? errorId(name) : undefined);
  const invalid = (name: FieldName) => (fieldErrors[name]?.length ?? 0) > 0 || undefined;
  const errorsOf = (name: FieldName): ReactNode =>
    (fieldErrors[name]?.length ?? 0) > 0 ? (
      <span id={errorId(name)} className="block">
        {(fieldErrors[name] ?? []).map((message, index) => (
          <span key={index} className="block text-xs text-red-600">
            {message}
          </span>
        ))}
      </span>
    ) : null;

  // The label block of one field: the label text, the control, the help text and the field's errors (in the label, as
  // the template draws them).
  const field = (name: FieldName, label: string, required: boolean, control: ReactNode, help?: string, wide = false) => (
    <div key={name} className={cn("block text-sm", wide && "md:col-span-2")}>
      <label className="block">
        {label}
        {required ? " *" : null}
        {control}
        {help ? <span className="block text-xs text-slate-500">{help}</span> : null}
        {errorsOf(name)}
      </label>
    </div>
  );

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={hasErrors ? serverErrors : null}
      title={edit ? TITLE_EDIT : TITLE_ADD}
      // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell).
      noAnim
    >
      <form noValidate className="space-y-3" onSubmit={submit}>
        {topErrors.length > 0 ? (
          <div role="alert" className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <div className="grid gap-3 md:grid-cols-2">
          {field(
            "title",
            "Ажлын байрны нэр",
            true,
            <input
              type="text"
              name="title"
              required
              maxLength={200}
              value={values.title}
              aria-invalid={invalid("title")}
              aria-describedby={describedBy("title")}
              onChange={(event) => setField("title", event.target.value)}
              className={BOXED}
            />,
            undefined,
            true,
          )}
          {field(
            "position",
            "Албан тушаал",
            true,
            <Select
              name="position"
              value={values.position}
              onChange={(value) => setField("position", value)}
              options={choiceList(options.positions)}
              search
              required
              className={BOXED}
              invalid={invalid("position")}
              describedBy={describedBy("position")}
            />,
          )}
          {field(
            "department",
            "Хэлтэс",
            true,
            <Select
              name="department"
              value={values.department}
              onChange={(value) => setField("department", value)}
              options={choiceList(options.departments)}
              search
              required
              className={BOXED}
              invalid={invalid("department")}
              describedBy={describedBy("department")}
            />,
          )}
          {field(
            "branch",
            "Салбар",
            false,
            <Select
              name="branch"
              value={values.branch}
              onChange={(value) => setField("branch", value)}
              options={choiceList(options.branches)}
              search
              className={BOXED}
              invalid={invalid("branch")}
              describedBy={describedBy("branch")}
            />,
            HELP_BRANCH,
          )}
          {field(
            "headcount",
            "Авах хүний тоо",
            true,
            <input
              type="number"
              name="headcount"
              required
              min={1}
              max={32767}
              value={values.headcount}
              aria-invalid={invalid("headcount")}
              aria-describedby={describedBy("headcount")}
              onChange={(event) => setField("headcount", event.target.value)}
              className={BOXED}
            />,
          )}
          {field(
            "hiring_manager",
            "Ажилд авах удирдлага",
            false,
            <Select
              name="hiring_manager"
              value={values.hiring_manager}
              onChange={(value) => setField("hiring_manager", value)}
              options={choiceList(options.managers)}
              className={BOXED}
              invalid={invalid("hiring_manager")}
              describedBy={describedBy("hiring_manager")}
            />,
            HELP_MANAGER,
          )}
          {field(
            "deadline",
            "Авах эцсийн хугацаа",
            false,
            <DatePicker
              name="deadline"
              value={values.deadline}
              onChange={(value) => setField("deadline", value)}
              className={BOXED}
              invalid={invalid("deadline")}
              describedBy={describedBy("deadline")}
            />,
          )}
          {field(
            "desired_start",
            "Ажил эхлэх огноо",
            false,
            <DatePicker
              name="desired_start"
              value={values.desired_start}
              onChange={(value) => setField("desired_start", value)}
              className={BOXED}
              invalid={invalid("desired_start")}
              describedBy={describedBy("desired_start")}
            />,
            HELP_START,
          )}
          {edit
            ? field(
                "status",
                "Төлөв",
                true,
                <Select
                  name="status"
                  value={values.status}
                  onChange={(value) => setField("status", value)}
                  options={options.statuses.map((item) => ({ value: item.value, label: item.label }))}
                  search={false}
                  required
                  className={BOXED}
                  invalid={invalid("status")}
                  describedBy={describedBy("status")}
                />,
              )
            : null}
          {field(
            "description",
            "Тайлбар",
            false,
            <textarea
              name="description"
              rows={1}
              value={values.description}
              aria-invalid={invalid("description")}
              aria-describedby={describedBy("description")}
              onChange={(event) => setField("description", event.target.value)}
              className={AUTO_TEXTAREA}
            />,
            undefined,
            true,
          )}
        </div>
        <SlotLine line={slot.data ?? null} />
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            disabled={pending}
            onClick={cancel}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm disabled:opacity-50"
          >
            Болих
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {edit ? "Хадгалах" : "Нээх"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// A pop-up shell with one short message (while the data loads, or when it fails).
function MessageModal({ title, message, onClose }: { title: string; message?: ReactNode; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={title} noAnim>
      {message ? (
        <div role="alert" className="text-sm text-red-600">
          {message}
        </div>
      ) : null}
    </Modal>
  );
}

// The text of a failed load: a 404 is the not-found state, a 403 the forbidden state, anything else the load failure.
function failureOf(error: unknown): ReactNode {
  const status = (error as { status?: number } | null)?.status;
  if (status === 404) {
    return (
      <>
        <span className="block font-medium">{NOT_FOUND_TITLE}</span>
        <span className="block">{NOT_FOUND_TEXT}</span>
      </>
    );
  }
  if (status === 403) return FORBIDDEN_TEXT;
  return LOAD_FAILED_TEXT;
}

// The add pop-up loads the choices first (read fresh on every open).
function AddVacancy({ onClose, onSaved }: { onClose: () => void; onSaved?: (id: number) => void }) {
  const options = useVacancyOptions(null, true);
  if (options.data === undefined) {
    return options.isError ? (
      <MessageModal title={TITLE_ADD} message={failureOf(options.error)} onClose={onClose} />
    ) : (
      <MessageModal title={TITLE_ADD} onClose={onClose} />
    );
  }
  return <VacancyForm editId={null} initial={ADD_VALUES} options={options.data} onClose={onClose} onSaved={onSaved} />;
}

// The edit pop-up loads the vacancy's saved values and its choices (the options with the vacancy, so its manager is among
// them). Both are read fresh on every open; the form shows once both have arrived.
function EditVacancy({ id, onClose, onSaved }: { id: number; onClose: () => void; onSaved?: (id: number) => void }) {
  const form = useVacancyForm(id);
  const options = useVacancyOptions(id, true);
  if (form.isError || options.isError) {
    return <MessageModal title={TITLE_EDIT} message={failureOf(form.error ?? options.error)} onClose={onClose} />;
  }
  if (form.data === undefined || options.data === undefined) {
    return <MessageModal title={TITLE_EDIT} onClose={onClose} />;
  }
  return (
    <VacancyForm
      editId={id}
      initial={valuesOf(form.data)}
      options={options.data}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}

// The vacancy pop-up: add (vacancyId null) or edit (an id).
export function VacancyModal({ vacancyId, onClose, onSaved }: VacancyModalProps) {
  if (vacancyId === null) return <AddVacancy onClose={onClose} onSaved={onSaved} />;
  return <EditVacancy id={vacancyId} onClose={onClose} onSaved={onSaved} />;
}
