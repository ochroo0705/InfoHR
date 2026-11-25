import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api } from "../../../api/client";
import {
  useSaveView,
  useUpdateView,
  useViewForm,
  type ReportViewFormOut,
  type ReportViewIn,
  type ReportViewResultOut,
  type ViewFormTarget,
} from "../../../api/reports";
import { postWithCsrfRetry, type ApiFailure } from "../../../api/mutate";
import { Modal } from "../../../widgets/Modal";
import { SAVE_FAILED_TEXT } from "../../employee/PageForm";
import { INPUT } from "./popupStyles";
import { VIEW_TEXT } from "./popupTexts";

// The «Харагдац хадгалах» and «Харагдац засах» pop-up (port of app/reports/templates/reports/_view_modal.html). The form
// (name, visibility, default, and for «new» the address in `query`) comes from the API; a refused save keeps the pop-up
// open with its errors. Labels, classes and buttons are copied from the template. Saved ok with a redirect → navigate
// there; edit ok → close (the mutation hooks refresh the report); delete ok → navigate to the bare report.
// «Болих» closes at once; ✕, Escape and an outside click ask first after typing (Modal's own rule).

// Failure texts for the form load. The 404 and 403 texts are copied from the recruitment vacancy pop-up
// (VacancyModal.tsx), where the same two states are shown; no view-specific text exists in the Django templates.
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const NOT_FOUND_TITLE = "Хуудас олдсонгүй";
const NOT_FOUND_TEXT = "Хаяг буруу байна эсвэл хуудас өөр газар шилжсэн байж магадгүй.";
const FORBIDDEN_TEXT = "Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу.";

type Visibility = "shared" | "private";
type Errors = Record<string, string[]>;

// The target of the pop-up: «new» saves the address `query` of report `key`; «edit» renames view `pk`.
export type SavedViewTarget = { mode: "new"; query: string } | { mode: "edit"; pk: number };

export interface SavedViewModalProps {
  reportKey: string;
  target: SavedViewTarget;
  onClose: () => void;
}

// The target the form is read by (the «new» form reads the address, the edit form the view id).
function formTargetOf(reportKey: string, target: SavedViewTarget): ViewFormTarget {
  return target.mode === "new" ? { key: reportKey, query: target.query } : { pk: target.pk };
}

// The messages of a refused answer: its form_errors, then its `error` text when it has one.
function messagesOf(result: ReportViewResultOut): string[] {
  return [...result.form_errors, result.error].filter((message) => message !== "");
}

// The text of a failed load: a 404 is the not-found state, a 403 the forbidden state, anything else the load failure.
function failureText(error: unknown): ReactNode {
  const status = (error as Partial<ApiFailure> | null)?.status;
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

export function SavedViewModal({ reportKey, target, onClose }: SavedViewModalProps) {
  const query = useViewForm(formTargetOf(reportKey, target), true);
  const title = target.mode === "new" ? VIEW_TEXT.newTitle : VIEW_TEXT.editTitle;

  if (query.data === undefined) {
    return (
      <Modal open onClose={onClose} title={title} width="max-w-md">
        {query.isError ? (
          <div className="space-y-4">
            <div role="alert" className="text-sm text-red-600">
              {failureText(query.error)}
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
              >
                {VIEW_TEXT.cancel}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    );
  }
  return <ViewForm reportKey={reportKey} target={target} form={query.data} onClose={onClose} />;
}

interface ViewFormProps {
  reportKey: string;
  target: SavedViewTarget;
  form: ReportViewFormOut;
  onClose: () => void;
}

function ViewForm({ reportKey, target, form, onClose }: ViewFormProps) {
  const navigate = useNavigate();
  const nameId = useId();
  const isEdit = target.mode === "edit";
  // Only the edit pop-up uses the view hooks; the «new» pop-up passes pk 0 and never calls them.
  const pk = target.mode === "edit" ? target.pk : 0;
  const queryClient = useQueryClient();
  const saveView = useSaveView();
  const updateView = useUpdateView(pk);

  // A blank visibility from the server means shared.
  const baseVisibility: Visibility = form.visibility === "private" ? "private" : "shared";
  const [name, setName] = useState(form.name);
  const [visibility, setVisibility] = useState<Visibility>(baseVisibility);
  const [isDefault, setIsDefault] = useState(form.is_default);
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);

  const dirty = name !== form.name || visibility !== baseVisibility || isDefault !== form.is_default;
  const serverErrors = { field_errors: fieldErrors, form_errors: formErrors };

  // Typing in a box, or picking another value there, drops that box's error; the next save decides it afresh.
  const clearFieldError = (field: string) => {
    setFieldErrors((prev) =>
      field in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== field)) : prev,
    );
  };
  const changeName = (value: string) => {
    setName(value);
    clearFieldError("name");
  };
  const changeVisibility = (value: Visibility) => {
    setVisibility(value);
    clearFieldError("visibility");
  };
  const changeDefault = (value: boolean) => {
    setIsDefault(value);
    clearFieldError("is_default");
  };

  // A refused write: its field errors under their fields, its messages in the red box. A refusal with neither gets the
  // general save message.
  const refuse = (fe: Errors, messages: string[]) => {
    setFieldErrors(fe);
    setFormErrors(messages.length > 0 ? messages : Object.keys(fe).length > 0 ? [] : [SAVE_FAILED_TEXT]);
  };

  const errorsOf = (field: string): ReactNode =>
    (fieldErrors[field] ?? []).map((message, index) => (
      <span key={index} className="block text-xs text-red-600">
        {message}
      </span>
    ));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark is set before the request, so a second Enter or click in the same tick sends nothing.
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      // A private view is never the default: the box is hidden then, so nothing contradictory is sent.
      // The edit form sends its three boxes; the server ignores the address in an edit, so `query` is sent empty.
      const body: ReportViewIn = {
        name,
        visibility,
        is_default: visibility === "shared" && isDefault,
        query: isEdit ? "" : form.query,
      };
      const result = isEdit
        ? await updateView.mutateAsync(body)
        : await saveView.mutateAsync({ key: reportKey, body });
      if (result.ok) {
        // The guard stays set: the pop-up is closing, and a second Enter must not send again.
        closing = true;
        // A new view opens at its address; an edited view only closes (the hook refreshes the page).
        if (!isEdit && result.redirect) navigate(result.redirect);
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

  // «Устгах» (the second step, after the question) deletes the view; the bare report is the redirect. The pop-up
  // closes as soon as the delete answers: the report refresh runs in the background, not before the close.
  const remove = async () => {
    if (inFlight.current || target.mode !== "edit") return;
    inFlight.current = true;
    setPending(true);
    let closing = false;
    try {
      const result = await postWithCsrfRetry<ReportViewResultOut>(queryClient, () =>
        api.POST("/api/v1/reports/views/{pk}/delete", { params: { path: { pk: target.pk } } }),
      );
      if (result.ok) {
        closing = true;
        // The view is gone: drop its form query first, so the refresh below does not request it again (a 404).
        queryClient.removeQueries({ queryKey: ["reports", "view-form", "pk", target.pk] });
        void queryClient.invalidateQueries({ queryKey: ["reports"] });
        if (result.redirect) navigate(result.redirect);
        onClose();
        return;
      }
      setFormErrors(messagesOf(result).length > 0 ? messagesOf(result) : [SAVE_FAILED_TEXT]);
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

  return (
    <Modal
      open
      onClose={onClose}
      dirty={dirty}
      serverErrors={serverErrors}
      title={form.title}
      width="max-w-md"
    >
      <form noValidate className="space-y-3" onSubmit={submit}>
        {formErrors.length > 0 ? (
          <p className="rounded bg-red-50 p-2 text-sm text-red-700">{formErrors.join(" ")}</p>
        ) : null}
        <label htmlFor={nameId} className="block text-sm">
          {VIEW_TEXT.name} *
          <input
            id={nameId}
            type="text"
            name="name"
            required
            maxLength={60}
            value={name}
            aria-invalid={(fieldErrors.name?.length ?? 0) > 0 || undefined}
            onChange={(event) => changeName(event.target.value)}
            className={`w-full ${INPUT}`}
          />
          {errorsOf("name")}
        </label>
        <fieldset className="text-sm">
          <legend className="mb-1">{VIEW_TEXT.visibility}</legend>
          <div className="flex flex-wrap gap-4">
            {(["shared", "private"] as const).map((value) => (
              <label key={value} className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  name="visibility"
                  value={value}
                  checked={visibility === value}
                  onChange={() => changeVisibility(value)}
                  className="accent-violet-600"
                />
                {value === "shared" ? VIEW_TEXT.shared : VIEW_TEXT.private}
              </label>
            ))}
          </div>
          {errorsOf("visibility")}
        </fieldset>
        {/* A private view cannot open first, so the «үндсэн» box shows only while «Хамтын» is chosen. */}
        {visibility === "shared" ? (
          <div className="text-sm">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                name="is_default"
                checked={isDefault}
                onChange={(event) => changeDefault(event.target.checked)}
                className="rounded border-slate-300 accent-[var(--color-pick-edge)]"
              />
              {VIEW_TEXT.isDefault}
            </label>
            {errorsOf("is_default")}
          </div>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
          >
            {VIEW_TEXT.cancel}
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            {VIEW_TEXT.save}
          </button>
        </div>
      </form>
      {isEdit ? (
        // Delete is at the bottom left, away from the primary button. Its own question asks first (UI_RULES §6).
        <div className="mt-4 border-t border-slate-100 pt-3 text-sm">
          {confirming ? (
            <div className="flex items-center gap-3">
              <span className="text-slate-700">{VIEW_TEXT.deleteConfirm}</span>
              <button
                type="button"
                disabled={pending}
                onClick={() => void remove()}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
              >
                {VIEW_TEXT.delete}
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={pending}
              onClick={() => setConfirming(true)}
              className="rounded px-2 py-1 text-red-600 hover:bg-red-50"
            >
              {VIEW_TEXT.delete}
            </button>
          )}
        </div>
      ) : null}
    </Modal>
  );
}
