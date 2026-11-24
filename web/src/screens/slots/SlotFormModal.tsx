import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  deleteSlot,
  saveSlot,
  useSlotOptions,
  type SlotOptionsOut,
  type SlotRowOut,
  type SlotWriteIn,
} from "../../api/slots";
import type { ApiFailure } from "../../api/mutate";
import { confirm } from "../../widgets/confirm";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { hasServerErrors, tryClose } from "../../widgets/modalLogic";
import { Select } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { useQuickAdd, type QuickAddAdd } from "../lists/QuickAddHost";

// The add and edit pop-up of one position-slot row (port of app/employees/templates/employees/_slot_form.html and
// app/employees/views_slots.py SlotForm). Labels, the ` *` marks, the hint, the buttons and their classes are copied
// from the template. It takes no router or page state: the page passes the row (edit) or nothing (add), the year on
// screen and onClose. A saved or deleted row closes the pop-up; the list refetches through the saveSlot/deleteSlot helpers.

const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const DELETE_TEXT = "Энэ орон тооны мөрийг устгах уу?";
// The kind a new row starts with (app/employees/slot_kind.py MAIN).
const MAIN_KIND = "Main";

type FieldName = "position" | "branch" | "kind" | "year" | "qty";
type Values = Record<FieldName, string>;
const FIELD_NAMES: FieldName[] = ["position", "branch", "kind", "year", "qty"];

// An empty numeric box is sent as null and an empty kind as "": the server answers with Django's own «required» text
// under that box (field_errors), so the client never invents a message.
function numberOrNull(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

export interface SlotFormModalProps {
  // The row to edit. Undefined: the add pop-up.
  row?: SlotRowOut;
  // The year on screen: the year of a new row and of the choices.
  year: number;
  onClose: () => void;
}

// The choice lists the row's own ids are missing from (a row whose position or branch is not in the options) get the
// row's id and name, so the visible label is right and the save posts the same id.
function withRowOption(
  list: { value: number; label: string }[],
  id: number | undefined,
  label: string | undefined,
): { value: number; label: string }[] {
  if (id === undefined || list.some((item) => item.value === id)) return list;
  return [...list, { value: id, label: label ?? String(id) }];
}

// The choices of a select: the server's list, the row's own entry when the list is missing it, then the entries added
// through a pop-up in this session (a modal add is not in the list the server sent before it existed).
function selectOptions(
  list: { value: number; label: string }[],
  id: number | undefined,
  label: string | undefined,
  extra: { value: string; label: string }[],
): { value: string; label: string }[] {
  const mapped = withRowOption(list, id, label).map((item) => ({ value: String(item.value), label: item.label }));
  return [...mapped, ...extra.filter((item) => !mapped.some((option) => option.value === item.value))];
}

function initialOf(row: SlotRowOut | undefined, year: number): Values {
  if (row === undefined) return { position: "", branch: "", kind: MAIN_KIND, year: String(year), qty: "" };
  return {
    position: String(row.position_id),
    branch: String(row.branch_id),
    kind: row.kind,
    year: String(year),
    qty: String(row.posts),
  };
}

export function SlotFormModal({ row, year, onClose }: SlotFormModalProps) {
  const queryClient = useQueryClient();
  const quick = useQuickAdd();
  const options = useSlotOptions(year);
  const baseline = initialOf(row, year);
  const [values, setValues] = useState<Values>(baseline);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  // The entries added through the quick-add pop-up (see selectOptions); a plain add stays in Select's own list.
  const [extraPositions, setExtraPositions] = useState<{ value: string; label: string }[]>([]);
  const [extraBranches, setExtraBranches] = useState<{ value: string; label: string }[]>([]);

  const isEdit = row !== undefined;
  const dirty = FIELD_NAMES.some((name) => values[name] !== baseline[name]);
  const serverErrors = { field_errors: fieldErrors, form_errors: formErrors };
  const dirtyNow = dirty || hasServerErrors(serverErrors);

  // Typing in a box drops that box's error; the next save decides it afresh.
  const setField = (name: FieldName, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setFieldErrors((prev) => (name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev));
  };

  // A refused write: its field errors under their boxes, its form errors in the red box at the top. A refusal with
  // neither gets the general save message.
  const refuse = (fe: Record<string, string[]>, messages: string[]) => {
    setFieldErrors(fe);
    setFormErrors(messages.length > 0 ? messages : Object.keys(fe).length > 0 ? [] : [SAVE_FAILED_TEXT]);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || options.data === undefined) return;
    // The in-flight mark is set before the request, so a second Enter or click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      // Empty boxes go as null (kind as ""): the server's own «required» texts come back under those boxes.
      const body: SlotWriteIn = {
        position: numberOrNull(values.position),
        branch: numberOrNull(values.branch),
        kind: values.kind,
        year: numberOrNull(values.year),
        qty: numberOrNull(values.qty),
      };
      const result = await saveSlot(queryClient, row?.id ?? null, body);
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        onClose();
        return;
      }
      refuse(result.field_errors, result.form_errors);
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

  // «Устгах» asks first; a refused delete keeps the pop-up open with the message.
  const remove = async () => {
    if (inFlight.current || row === undefined) return;
    // The in-flight mark is set before the question, so a second click while it is open asks nothing more.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      if (!(await confirm(DELETE_TEXT))) return;
      const result = await deleteSlot(queryClient, row.id);
      if (result.ok) {
        closing = true;
        onClose();
        return;
      }
      setFormErrors(result.form_errors.length > 0 ? result.form_errors : [SAVE_FAILED_TEXT]);
    } catch (error) {
      const messages = (error as Partial<ApiFailure>).formErrors ?? [];
      setFormErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
    } finally {
      if (!closing) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  // «Болих» closes through the same dirty check as ✕ and Escape.
  const cancel = () => {
    void tryClose({ dirty: dirtyNow, leaving: false, close: onClose }, (message) => confirm(message, { ok: "Хаах" }));
  };

  const errorsOf = (name: FieldName): ReactNode =>
    (fieldErrors[name] ?? []).map((message, index) => (
      <span key={index} className="block text-xs text-red-600">
        {message}
      </span>
    ));
  const invalid = (name: FieldName) => (fieldErrors[name]?.length ?? 0) > 0 || undefined;

  const opts = options.data;

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={dirtyNow ? serverErrors : null}
      title={isEdit ? "Орон тоо засах" : "Орон тоо нэмэх"}
      // No enter or exit animation: the Django pop-up closes at once too (the legacy no-anim shell, as EventModal).
      noAnim
    >
      {opts === undefined ? (
        options.isError ? (
          <p role="alert" className="text-sm text-red-600">
            {LOAD_FAILED_TEXT}
          </p>
        ) : null
      ) : (
        <form noValidate className="space-y-3" onSubmit={save}>
          {formErrors.length > 0 ? (
            <div className="rounded bg-red-50 p-2 text-sm text-red-700">
              {formErrors.map((message, index) => (
                <p key={index}>{message}</p>
              ))}
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block text-sm md:col-span-2">
              Албан тушаал *
              <Select
                name="position"
                value={values.position}
                onChange={(value) => setField("position", value)}
                options={selectOptions(opts.positions, row?.position_id, row?.position, extraPositions)}
                {...quick.selectProps(opts.add_position, (picked, label) => {
                  setExtraPositions((prev) =>
                    prev.some((o) => o.value === picked) ? prev : [...prev, { value: picked, label }],
                  );
                  setField("position", picked);
                })}
                className={BOXED}
                invalid={invalid("position")}
              />
              {errorsOf("position")}
            </label>
            <label className="block text-sm">
              Салбар *
              <Select
                name="branch"
                value={values.branch}
                onChange={(value) => setField("branch", value)}
                options={selectOptions(opts.branches, row?.branch_id, row?.branch, extraBranches)}
                {...quick.selectProps(opts.add_branch, (picked, label) => {
                  setExtraBranches((prev) =>
                    prev.some((o) => o.value === picked) ? prev : [...prev, { value: picked, label }],
                  );
                  setField("branch", picked);
                })}
                className={BOXED}
                invalid={invalid("branch")}
              />
              {errorsOf("branch")}
            </label>
            <label className="block text-sm">
              Төрөл *
              <Select
                name="kind"
                value={values.kind}
                onChange={(value) => setField("kind", value)}
                options={opts.kinds.map((item) => ({ value: item.value, label: item.label }))}
                className={BOXED}
                invalid={invalid("kind")}
              />
              {errorsOf("kind")}
            </label>
            <label className="block text-sm">
              Он *
              <input
                type="number"
                name="year"
                min={opts.min_year}
                max={opts.max_year}
                value={values.year}
                aria-invalid={invalid("year")}
                onChange={(event) => setField("year", event.target.value)}
                className={BOXED}
              />
              {errorsOf("year")}
            </label>
            <label className="block text-sm">
              Орон тоо *
              <input
                type="number"
                name="qty"
                min={0}
                max={100000}
                value={values.qty}
                aria-invalid={invalid("qty")}
                onChange={(event) => setField("qty", event.target.value)}
                className={BOXED}
              />
              {errorsOf("qty")}
            </label>
          </div>
          <p className="text-xs text-slate-500">{opts.hint}</p>
          <div className="flex items-center gap-2 pt-2">
            {isEdit ? (
              <button
                type="button"
                disabled={pending}
                onClick={() => void remove()}
                className="mr-auto rounded px-2 py-1 text-red-600 hover:bg-red-50"
              >
                Устгах
              </button>
            ) : null}
            <button
              type="button"
              onClick={cancel}
              className={
                isEdit
                  ? "rounded-lg border border-slate-300 px-4 py-2 text-sm"
                  : "ml-auto rounded-lg border border-slate-300 px-4 py-2 text-sm"
              }
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
      )}
    </Modal>
  );
}
