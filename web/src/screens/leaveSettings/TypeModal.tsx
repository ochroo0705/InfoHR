import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  useDeleteLeaveType,
  useLeaveType,
  useSaveLeaveType,
  type LeaveTypeIn,
  type LeaveTypeOut,
  type LeaveWriteResultOut,
} from "../../api/leaveSetup";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The add and edit pop-up of one leave type (port of app/leave/templates/leave/_type_form.html and LeaveTypeForm in
// app/leave/forms.py). Labels, help texts and classes are copied from the template and the form. The fields come in the
// form's order. A new type starts active, may be requested by staff, and sorts at 0. Delete is at the bottom left of the
// content, behind the confirm question, as the other pop-ups do it. A refused write keeps the pop-up open with its messages.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const TITLE_ADD = "Чөлөөний төрөл нэмэх";
const TITLE_EDIT = "Чөлөөний төрөл засах";
const DELETE_TEXT = "Энэ төрлийг устгах уу?";
const ORDER_REQUIRED_TEXT = "Энэ талбарыг бөглөнө үү.";
const FIELD_NAMES = ["name", "is_paid", "uses_annual_balance", "is_active", "order", "staff_may_request"];

// The form's values as the boxes hold them. The order is text while it is typed.
export interface TypeValues {
  name: string;
  is_paid: boolean;
  uses_annual_balance: boolean;
  is_active: boolean;
  order: string;
  staff_may_request: boolean;
}

const ADD_VALUES: TypeValues = {
  name: "",
  is_paid: false,
  uses_annual_balance: false,
  is_active: true,
  order: "0",
  staff_may_request: true,
};

function valuesOf(type: LeaveTypeOut): TypeValues {
  return {
    name: type.name,
    is_paid: type.is_paid,
    uses_annual_balance: type.uses_annual_balance,
    is_active: type.is_active,
    order: String(type.order),
    staff_may_request: type.staff_may_request,
  };
}

// The body of a write. The order is a number here: submit blocks an empty order before any request is sent.
function bodyOf(values: TypeValues): LeaveTypeIn {
  return {
    name: values.name,
    is_paid: values.is_paid,
    uses_annual_balance: values.uses_annual_balance,
    is_active: values.is_active,
    order: Number(values.order),
    staff_may_request: values.staff_may_request,
  };
}

// The messages of a refused answer: the service's own text first, then the form errors.
function messagesOf(result: LeaveWriteResultOut): string[] {
  return [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
}

type Errors = Record<string, string[]>;

export interface TypeModalProps {
  // The type's id; null is the add pop-up.
  id: number | null;
  onClose: () => void;
}

// The loaded form. Its typed values live here, so a refused save keeps them.
function TypeForm({ id, initial, onClose }: { id: number | null; initial: TypeValues; onClose: () => void }) {
  const save = useSaveLeaveType(id);
  const remove = useDeleteLeaveType(id ?? 0);
  const ids = useId();
  const [values, setValues] = useState<TypeValues>(initial);
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = FIELD_NAMES.some((name) => values[name as keyof TypeValues] !== initial[name as keyof TypeValues]);
  const serverErrors = { field_errors: fieldErrors, form_errors: topErrors };
  const hasErrors = hasServerErrors(serverErrors);
  const title = id === null ? TITLE_ADD : TITLE_EDIT;

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = <K extends keyof TypeValues>(name: K, value: TypeValues[K]) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) =>
      name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev,
    );
  };

  // A refused write: the field messages under their boxes; the form's own and any stray field message at the top. A
  // refusal with no message at all gets the general save text.
  const refuse = (fe: Errors, messages: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => !FIELD_NAMES.includes(key))
      .flatMap(([, list]) => list);
    const top = [...messages, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // An empty order is refused here, under its box, and nothing is sent.
    if (values.order.trim() === "") {
      setFieldErrors({ ...fieldErrors, order: [ORDER_REQUIRED_TEXT] });
      return;
    }
    // The in-flight mark is set before the request, so a second click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const result = await save.mutateAsync(bodyOf(values));
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and nothing may send again.
        closing = true;
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

  // «Устгах» asks first; a type in use is refused and the pop-up stays open with the message.
  const removeType = async () => {
    if (inFlight.current || id === null) return;
    // The in-flight mark is set before the question, so a second click while it is open asks nothing more.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      if (!(await confirm(DELETE_TEXT))) return;
      const result = await remove.mutateAsync();
      if (result.ok) {
        closing = true;
        onClose();
        return;
      }
      const messages = messagesOf(result);
      setTopErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
    } catch (error) {
      const messages = (error as Partial<ApiFailure>).formErrors ?? [];
      setTopErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
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

  const errorsOf = (name: string): ReactNode =>
    (fieldErrors[name] ?? []).map((message, index) => (
      <span key={index} className="block text-xs text-red-600">
        {message}
      </span>
    ));

  const invalid = (name: string): true | undefined => (fieldErrors[name]?.length ?? 0) > 0 || undefined;
  const helpOf = (text: string): ReactNode => <span className="block text-xs text-slate-500">{text}</span>;

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={hasErrors ? serverErrors : null}
      title={title}
      width="max-w-md"
      // No enter or exit animation: the Django pop-up appears and goes at once too (the legacy no-anim shell).
      noAnim
    >
      <form noValidate className="space-y-3" onSubmit={submit}>
        {topErrors.length > 0 ? (
          <div className="rounded bg-red-50 p-2 text-sm text-red-700">
            {topErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <label className="block text-sm">
          Нэр *
          <input
            type="text"
            name="name"
            required
            maxLength={200}
            value={values.name}
            aria-invalid={invalid("name")}
            onChange={(event) => setField("name", event.target.value)}
            className={BOXED}
          />
          {errorsOf("name")}
        </label>
        <label className="block text-sm">
          Цалинтай
          <span className="ml-2 inline-flex align-middle">
            <input
              type="checkbox"
              name="is_paid"
              checked={values.is_paid}
              onChange={(event) => setField("is_paid", event.target.checked)}
              className="rounded border-slate-300"
            />
          </span>
          {helpOf("Тэмдэглэгээ: энэ төрлийн чөлөө цалинтай эсэхийг харуулна.")}
          {errorsOf("is_paid")}
        </label>
        <label className="block text-sm">
          Ээлжийн амралтаас хасна
          <span className="ml-2 inline-flex align-middle">
            <input
              type="checkbox"
              name="uses_annual_balance"
              checked={values.uses_annual_balance}
              onChange={(event) => setField("uses_annual_balance", event.target.checked)}
              className="rounded border-slate-300"
            />
          </span>
          {helpOf("Авсан хоног ээлжийн амралтын эрх, үлдэгдлээс хасагдана.")}
          {errorsOf("uses_annual_balance")}
        </label>
        <label className="block text-sm">
          Идэвхтэй
          <span className="ml-2 inline-flex align-middle">
            <input
              type="checkbox"
              name="is_active"
              checked={values.is_active}
              onChange={(event) => setField("is_active", event.target.checked)}
              className="rounded border-slate-300"
            />
          </span>
          {helpOf("Унтраавал чөлөө бүртгэх жагсаалтад энэ төрөл харагдахгүй. Өмнөх бүртгэл хэвээр үлдэнэ.")}
          {errorsOf("is_active")}
        </label>
        <label className="block text-sm" htmlFor={`${ids}-order`}>
          Жагсаалтад гарах дараалал *
          <input
            id={`${ids}-order`}
            type="number"
            name="order"
            required
            min={0}
            max={32767}
            value={values.order}
            aria-invalid={invalid("order")}
            onChange={(event) => setField("order", event.target.value)}
            className={BOXED}
          />
          {errorsOf("order")}
        </label>
        <label className="block text-sm">
          Ажилтан хүсэлт гаргана
          <span className="ml-2 inline-flex align-middle">
            <input
              type="checkbox"
              name="staff_may_request"
              checked={values.staff_may_request}
              onChange={(event) => setField("staff_may_request", event.target.checked)}
              className="rounded border-slate-300"
            />
          </span>
          {helpOf("Унтраавал ажилтан өөрөө хүсэлт гаргаж чадахгүй; шууд бүртгэнэ.")}
          {errorsOf("staff_may_request")}
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            disabled={pending}
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
      {id !== null ? (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <button
            type="button"
            disabled={pending}
            onClick={() => void removeType()}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
          >
            Устгах
          </button>
        </div>
      ) : null}
    </Modal>
  );
}

// While the type loads (or when it fails, e.g. a 404 for a type that is gone): the same pop-up shell.
function LoadingType({ failed, onClose }: { failed: boolean; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} title={TITLE_EDIT} width="max-w-md" noAnim>
      {failed ? (
        <p role="alert" className="text-sm text-red-600">
          {LOAD_FAILED_TEXT}
        </p>
      ) : null}
    </Modal>
  );
}

// The add pop-up starts at once; the edit pop-up loads its type first and reads it fresh on every open.
export function TypeModal({ id, onClose }: TypeModalProps) {
  const query = useLeaveType(id);
  if (id === null) return <TypeForm id={null} initial={ADD_VALUES} onClose={onClose} />;
  if (query.data === undefined) return <LoadingType failed={query.isError} onClose={onClose} />;
  return <TypeForm id={id} initial={valuesOf(query.data)} onClose={onClose} />;
}
