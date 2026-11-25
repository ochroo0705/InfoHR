import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useAddCandidate, type RecruitCandidateIn, type RecruitWriteResultOut } from "../../api/recruitment";
import type { ApiFailure } from "../../api/mutate";
import { cn } from "../../lib/utils";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The add-candidate pop-up (port of app/recruitment/templates/recruitment/candidate_form.html and CandidateForm in
// app/recruitment/forms.py). Labels and buttons are copied from the template and the form. A saved candidate closes the
// pop-up; a refused one keeps every typed value and shows the messages (the service's text on top, a field's message
// under its box). When the vacancy was closed meanwhile (the refusal text NOT_OPEN) the form is replaced by the amber
// text and a «Хаах» button, as the Django pop-up does.

const TITLE = "Ажил хүсэгч нэмэх";
// The text the server gives for a vacancy that is not open (app/recruitment/services/vacancy_page.py NOT_OPEN).
const NOT_OPEN = "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. Эхлээд ажлын байрыг нээнэ үү.";
// The five suggestions of the source box (app/recruitment/forms.py SOURCE_SUGGESTIONS).
const SOURCE_SUGGESTIONS = ["Танилын санал", "Вэбсайт", "Ажлын зар", "Биечлэн ирсэн", "Бусад"];

export interface CandidateValues {
  surname: string;
  given_name: string;
  phone: string;
  email: string;
  source: string;
  notes: string;
}
type FieldName = keyof CandidateValues;
const FIELD_NAMES: FieldName[] = ["surname", "given_name", "phone", "email", "source", "notes"];

// Django's textarea (employees StyledForm: rows 10 becomes 2): one line tall, grows with the text, not resizable.
const AUTO_TEXTAREA = `${BOXED} resize-none [field-sizing:content] min-h-[2.5rem]`;

const EMPTY: CandidateValues = { surname: "", given_name: "", phone: "", email: "", source: "", notes: "" };

type Errors = Record<string, string[]>;

export interface CandidateModalProps {
  vacancy: { id: number; title: string };
  onClose: () => void;
  onSaved: () => void;
}

// The pop-up. Its typed values live here, so a refused save keeps them.
export function CandidateModal({ vacancy, onClose, onSaved }: CandidateModalProps) {
  const save = useAddCandidate(vacancy.id);
  const ids = useId();
  const sourceListId = `${ids}-sources`;
  const [values, setValues] = useState<CandidateValues>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [notOpen, setNotOpen] = useState(false);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = FIELD_NAMES.some((name) => values[name] !== EMPTY[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: FieldName, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) =>
      name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev,
    );
  };

  // A refused save: the vacancy-closed text swaps the form for the amber note; otherwise the field messages go under
  // their boxes, and the service's text and the form's own messages go on top. A refusal with no message at all gets
  // the general save text.
  const refuse = (result: RecruitWriteResultOut) => {
    if (result.error === NOT_OPEN) {
      setNotOpen(true);
      return;
    }
    const stray = Object.entries(result.field_errors)
      .filter(([key]) => !FIELD_NAMES.includes(key as FieldName))
      .flatMap(([, list]) => list);
    const top = [result.error, ...result.form_errors, ...stray].filter((text): text is string => Boolean(text));
    const anyFieldMessage = Object.values(result.field_errors).some((list) => list.length > 0);
    setFieldErrors(result.field_errors);
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
      const body: RecruitCandidateIn = { ...values };
      const result = await save.mutateAsync(body);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
        onSaved();
        onClose();
        return;
      }
      refuse(result);
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      refuse({
        ok: false,
        error: "",
        field_errors: failure.fieldErrors ?? {},
        form_errors: failure.formErrors ?? [],
      });
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

  // One labelled box: the label holds the control, its errors (as the template draws them).
  const field = (name: FieldName, label: string, required: boolean, control: ReactNode, wide = false) => (
    <label key={name} className={cn("block text-sm", wide && "md:col-span-2")}>
      {label}
      {required ? " *" : null}
      {control}
      {errorsOf(name)}
    </label>
  );

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty && !notOpen}
      serverErrors={hasErrors ? serverErrors : null}
      title={TITLE}
      titleClass="mb-1 text-lg font-semibold"
      noAnim
    >
      <p className="mb-4 text-sm text-slate-500">{vacancy.title}</p>
      {notOpen ? (
        <>
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{NOT_OPEN}</p>
          <div className="flex justify-end pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
            >
              Хаах
            </button>
          </div>
        </>
      ) : (
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
              "surname",
              "Овог",
              true,
              <input
                type="text"
                name="surname"
                required
                maxLength={100}
                value={values.surname}
                aria-invalid={invalid("surname")}
                aria-describedby={describedBy("surname")}
                onChange={(event) => setField("surname", event.target.value)}
                className={BOXED}
              />,
            )}
            {field(
              "given_name",
              "Нэр",
              true,
              <input
                type="text"
                name="given_name"
                required
                maxLength={100}
                value={values.given_name}
                aria-invalid={invalid("given_name")}
                aria-describedby={describedBy("given_name")}
                onChange={(event) => setField("given_name", event.target.value)}
                className={BOXED}
              />,
            )}
            {field(
              "phone",
              "Утас",
              false,
              <input
                type="text"
                name="phone"
                maxLength={50}
                value={values.phone}
                aria-invalid={invalid("phone")}
                aria-describedby={describedBy("phone")}
                onChange={(event) => setField("phone", event.target.value)}
                className={BOXED}
              />,
            )}
            {field(
              "email",
              "И-мэйл",
              false,
              <input
                type="email"
                name="email"
                value={values.email}
                aria-invalid={invalid("email")}
                aria-describedby={describedBy("email")}
                onChange={(event) => setField("email", event.target.value)}
                className={BOXED}
              />,
            )}
            {field(
              "source",
              "Эх сурвалж",
              false,
              <input
                type="text"
                name="source"
                list={sourceListId}
                autoComplete="off"
                maxLength={100}
                value={values.source}
                aria-invalid={invalid("source")}
                aria-describedby={describedBy("source")}
                onChange={(event) => setField("source", event.target.value)}
                className={BOXED}
              />,
            )}
            {field(
              "notes",
              "Тэмдэглэл",
              false,
              <textarea
                name="notes"
                rows={1}
                value={values.notes}
                aria-invalid={invalid("notes")}
                aria-describedby={describedBy("notes")}
                onChange={(event) => setField("notes", event.target.value)}
                className={AUTO_TEXTAREA}
              />,
              true,
            )}
          </div>
          <datalist id={sourceListId}>
            {SOURCE_SUGGESTIONS.map((suggestion) => (
              <option key={suggestion} value={suggestion} />
            ))}
          </datalist>
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
              Хадгалах
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
