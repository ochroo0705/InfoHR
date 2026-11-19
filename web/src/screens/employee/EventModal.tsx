import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { invalidateEmployee } from "../../api/employeeWrites";
import { useEventForm, useSubmitEvent, type EventFormOut, type EventWriteResultOut } from "../../api/events";
import type { ApiFailure } from "../../api/mutate";
import { useUnsavedFlag } from "../../lib/unsaved";
import { confirm } from "../../widgets/confirm";
import { BoxedControl, FormFields, initialValue, useFormValues, type FormField } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { OrderBlock } from "../../widgets/OrderBlock";
import { tryClose } from "../../widgets/modalLogic";
import { EFFECTIVE, useEventReloads, type Live } from "./eventModalReloads";
import { loadMessagesOf, splitRefusal, STALE_TEXT, useStaleRefresh, usePopupGuards } from "./popupGuards";

// The event pop-up («Ажил эрхлэлтийн үйл явдал бүртгэх» and its kin, `employees/_event_form.html`). The API draws the
// form: its title, kinds, boxes, order block, `when` note and summary line. This component draws them and keeps what the
// user typed; the reload behaviours are in eventModalReloads.ts. It decides no rule. The form is loaded when the pop-up
// opens and kept only while it is open.

const NO_FIELDS: FormField[] = [];
// The two boxes whose label and box span both columns (`md:col-span-2`), as the template draws them.
const SPANNING_NAMES = ["reason", "note"];

export type EventModalProps = {
  pk: number;
  // The event type (its URL segment), as the menu sends it.
  type: string;
  open: boolean;
  // Called once the close is allowed. The parent sets open to false.
  onClose: () => void;
  // Called after a kind pick has switched the pop-up to the other type. The parent may pass the new type back.
  onKindChange?: (type: string) => void;
};

// The summary line and the `when` note of the last answer that was not a form reload (a refusal or a summary refresh).
type Answered = { summary: string; when: string };

export function EventModal({ pk, type, open, onClose, onKindChange }: EventModalProps) {
  const queryClient = useQueryClient();
  const [live, setLive] = useState<Live>({ n: 0, loadType: type, activeType: type, reloaded: null });
  const [seenOpen, setSeenOpen] = useState(open);
  const [seenType, setSeenType] = useState(type);
  const form = useEventForm(pk, live.loadType, open);
  const shown: EventFormOut | null = live.reloaded ?? form.data ?? null;
  const boxes = shown?.fields ?? NO_FIELDS;
  const orderBoxes = shown?.order_fields ?? NO_FIELDS;
  const allFields = useMemo(() => [...boxes, ...orderBoxes], [boxes, orderBoxes]);
  const fields = useFormValues(allFields, `${pk}/${live.n}`);
  const submitEvent = useSubmitEvent(pk, live.activeType);
  const { formRef, isCurrent, isMounted, bumpErrorTick } = usePopupGuards(open);

  // The one dirty flag: typed at any time in this session. It drives «Болих», the Modal's ✕, Escape and outside click,
  // and the unsaved registry (the same rule as CorrectionModal).
  const [typed, setTyped] = useState(false);
  const dirty = typed;

  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  // The order block's own messages (the order-level ones of the current answer); never in formErrors.
  const [orderErrors, setOrderErrors] = useState<string[]>([]);
  const [answered, setAnswered] = useState<Answered | null>(null);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);

  // A new session (the pop-up opened, or the caller set another type): the form loads again and nothing typed carries
  // over. Done while rendering, as useFormValues does for its key. A kind pick the caller then passes back is no change.
  if (open !== seenOpen || type !== seenType) {
    setSeenOpen(open);
    setSeenType(type);
    if ((open && !seenOpen) || (type !== seenType && type !== live.activeType)) {
      setLive({ n: live.n + 1, loadType: type, activeType: type, reloaded: null });
      setTyped(false);
      setErrors({});
      setFormErrors([]);
      setOrderErrors([]);
      setAnswered(null);
    }
  }

  const reloads = useEventReloads({
    pk,
    queryClient,
    live,
    setLive,
    values: fields.values,
    allFields,
    shown,
    formRef,
    isCurrent,
    setField: fields.set,
    onKindChange,
    onReloadFailed: setFormErrors,
    onSummary: setAnswered,
    // A reload's answer brings its own errors and summary, unless a newer summary or save already stands.
    onFormApplied: (next, applied) => {
      if (!applied.keepErrors) {
        setErrors(next.errors);
        setFormErrors(next.form_errors);
        setOrderErrors(next.order_errors);
      }
      if (!applied.keepSummary) setAnswered(null);
    },
  });

  // A newly queried form starts clean: the server's own errors and messages, no answer from an earlier save or summary.
  // Keyed on the query, not on the shown form: a reload's answer is applied by onFormApplied.
  // (The "adjust state while rendering" pattern, as useFormValues does for its form key.)
  const queried = form.data ?? null;
  const [seenForm, setSeenForm] = useState<EventFormOut | null>(null);
  if (queried !== seenForm) {
    setSeenForm(queried);
    setErrors(queried?.errors ?? {});
    setFormErrors(queried?.form_errors ?? []);
    setOrderErrors(queried?.order_errors ?? []);
    setAnswered(null);
  }

  // The unsaved flag counts only while the pop-up is open, under the key of the type it is on.
  useUnsavedFlag("event:" + live.activeType, open && dirty);

  // A load that answers 404 means the page changed: refresh the employee's work and activity.
  const loadFailure = form.isError ? (form.error as Partial<ApiFailure> | null) : null;
  const loadIsStale = loadFailure?.status === 404;
  useStaleRefresh(loadIsStale, pk, queryClient, ["work", "activity"]);

  // A refused save: the field errors of this form's boxes go under those boxes; the rest, and the form errors, go to the
  // red box on top (splitRefusal, shared with HrPopup). The order-level messages go under the order block.
  const refuse = (fieldErrs: Record<string, string[]>, messages: string[], orderMessages: string[]) => {
    const split = splitRefusal(
      allFields.map((field) => field.name),
      fieldErrs,
      messages,
    );
    setErrors(split.boxErrors);
    setFormErrors(split.formMessages);
    setOrderErrors(orderMessages);
    bumpErrorTick();
  };

  // Every box change lands here. Typing drops that box's error; the next save decides it afresh. A committed change
  // reloads or refreshes (see eventModalReloads.ts).
  const onFieldChange = (name: string, value: string) => {
    fields.set(name, value);
    reloads.noteTyped(name, value);
    setTyped(true);
    setErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // Enter in a box, or «Хадгалах»: posts the held values with the hidden last real date inside `values`. A refusal keeps
  // the pop-up open with every value typed so far; a save while a reload is in flight sends the latest held values.
  const submit = async () => {
    if (inFlight.current || !shown) return;
    inFlight.current = true;
    setPending(true);
    setFormErrors([]);
    setOrderErrors([]);
    // A summary answer still in flight is older than this save and is ignored.
    reloads.noteSave();
    let closing = false;
    try {
      const answer: EventWriteResultOut = await submitEvent.mutateAsync({
        values: { ...reloads.sendValues(), prev_effective: reloads.base() },
      });
      if (!isCurrent()) return;
      if (answer.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
      reloads.setBase(answer.prev_effective);
      setAnswered({ summary: answer.summary, when: answer.when });
      refuse(answer.field_errors, answer.form_errors, answer.order_errors);
    } catch (error) {
      if (!isCurrent()) return;
      const failure = error as Partial<ApiFailure>;
      if (failure.status === 404) {
        // The event was applied or cancelled elsewhere: keep the typed values, refresh the page data.
        setErrors({});
        setFormErrors([STALE_TEXT]);
        setOrderErrors([]);
        void invalidateEmployee(queryClient, pk, ["work", "activity"]);
      } else {
        refuse(failure.fieldErrors ?? {}, failure.formErrors ?? [], []);
      }
    } finally {
      if (!closing) {
        inFlight.current = false;
        if (isMounted()) setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const shownOf = (field: FormField) => fields.values[field.name] ?? initialValue(field);
  const effectiveField = boxes.find((field) => field.name === EFFECTIVE);
  const restBoxes = boxes.filter((field) => field.name !== EFFECTIVE);
  const kinds = shown?.kinds ?? [];
  const kindValue = kinds.find((kind) => kind.selected)?.value ?? "";
  const when = answered?.when ?? shown?.when ?? "";
  const summary = answered?.summary ?? shown?.summary ?? "";
  const messages = loadFailure ? loadMessagesOf(loadFailure) : formErrors;
  const showing = open && (shown !== null || form.isError);

  return (
    <Modal open={showing} onClose={onClose} dirty={dirty} title={shown?.title} noAnim={shown?.reload === true}>
      {shown ? (
        <form
          ref={formRef}
          noValidate
          className="space-y-3"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            void submit();
          }}
        >
          {shown.death_unset ? (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
              «Нас барсан» шалтгааныг Жагсаалт → Утгатай бичлэг хэсэгт тохируулаагүй байна. Тохируулах хүртэл ажлаас
              гарсныг «нас барсан» гэж бүртгэхгүй.
            </p>
          ) : null}
          {messages.length > 0 ? <p className="rounded bg-red-50 p-2 text-sm text-red-700">{messages.join(" ")}</p> : null}
          {kinds.length > 0 ? (
            <label className="block text-sm">
              Төрөл *
              <select
                name="kind"
                value={kindValue}
                onChange={(event) => reloads.pickKind(event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {kinds.map((kind) => (
                  <option key={kind.value} value={kind.value}>
                    {kind.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <input type="hidden" name="prev_effective" value={reloads.base()} />
          {effectiveField ? (
            // The date box is a date box even when the server sends kind "text" (an unreal date keeps the typed text).
            <label className="block text-sm">
              {effectiveField.label} *
              <BoxedControl
                field={{ ...effectiveField, kind: "date" }}
                value={shownOf(effectiveField)}
                invalid={(errors[EFFECTIVE] ?? []).length > 0}
                onChange={onFieldChange}
              />
              {(errors[EFFECTIVE] ?? []).map((message, i) => (
                <span key={i} className="text-xs text-red-600">
                  {message}
                </span>
              ))}
            </label>
          ) : null}
          {when === "past" ? (
            <p className="rounded bg-amber-50 p-2 text-sm text-amber-800">Өнгөрсөн огноо — түүх засагдана</p>
          ) : when === "future" ? (
            <p className="rounded bg-sky-50 p-2 text-sm text-sky-800">Төлөвлөсөн</p>
          ) : null}
          <div className="space-y-3">
            {summary ? <p className="rounded bg-violet-50 p-2 text-sm text-violet-900">{summary}</p> : null}
            <FormFields
              variant="boxed"
              fields={restBoxes}
              values={fields.values}
              errors={errors}
              onChange={onFieldChange}
              spanNames={SPANNING_NAMES}
              errorInline
            />
          </div>
          {orderBoxes.length > 0 ? (
            <OrderBlock
              note={shown.order_note}
              formErrors={orderErrors}
              fields={orderBoxes}
              values={fields.values}
              errors={errors}
              onChange={onFieldChange}
            />
          ) : null}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={cancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
              Болих
            </button>
            <button
              type="submit"
              disabled={pending}
              aria-busy={pending || undefined}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-60"
            >
              Хадгалах
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="rounded bg-red-50 p-2 text-sm text-red-700">{messages.join(" ")}</div>
          <div className="flex justify-end pt-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
              Хаах
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
