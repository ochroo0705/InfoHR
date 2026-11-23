import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { createSelfForm, type SelfFormCreateFormOut, type SelfFormCreateIn } from "../../api/selfforms";
import type { ApiFailure } from "../../api/mutate";
import { BOXED } from "../../widgets/FormFields";
import { Select, type SelectOption } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The «Холбоос үүсгэх» form of the self-form list (port of app/employees/templates/employees/selfform/list.html and
// employees/selfform/forms.py SelfFormInvitationForm). Labels, the ` *` marks, the help texts and the classes are the
// template's; the words come from the API (form.labels, form.help). The three boxes are sent as typed: an empty branch
// or hours box goes as null, and the server answers with its own «required» texts under the box (field_errors), so the
// client never invents a message. A created link navigates to its page with the notice in router state.

type FieldName = "label" | "branch" | "hours";
const MAX_LABEL_LENGTH = 100; // the model's max_length of the label box (employees/selfform/forms.py)

// An empty number box is sent as null.
function numberOrNull(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

// The notice a page passes on in router state: the success box (green) or the error box (red), by tone.
export type PageNotice = { text: string; tone: "success" | "error" };

export interface SelfFormCreateFormProps {
  form: SelfFormCreateFormOut;
}

export function SelfFormCreateForm({ form }: SelfFormCreateFormProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [label, setLabel] = useState("");
  const [branch, setBranch] = useState("");
  const [hours, setHours] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  // The branch choices. Always starts with the empty entry (no text, as UI_RULES §2d and forms._blank_empty_label):
  // Django's ModelChoiceField keeps its empty choice even when the field is required.
  const branchOptions: SelectOption[] = [
    { value: "", label: "" },
    ...form.branches.map((item) => ({ value: String(item.value), label: item.label })),
  ];

  // Typing in a box drops that box's error; the next send decides it afresh.
  const clearError = (name: FieldName) =>
    setFieldErrors((prev) =>
      name in prev ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== name)) : prev,
    );

  // A refused create: its field errors under their boxes, its form errors in the red box at the top. A refusal with
  // neither gets the general save message.
  const refuse = (fe: Record<string, string[]>, messages: string[]) => {
    setFieldErrors(fe);
    setFormErrors(messages.length > 0 ? messages : Object.keys(fe).length > 0 ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    // The in-flight mark stays set after a success: the page is leaving, so a second click sends nothing.
    inFlight.current = true;
    setPending(true);
    let leaving = false;
    try {
      const body: SelfFormCreateIn = {
        label,
        branch: numberOrNull(branch),
        hours: numberOrNull(hours),
      };
      const result = await createSelfForm(queryClient, body);
      if (result.ok) {
        leaving = true;
        // The notice contract (Task 10 reads it): router state { notice: { text, tone } }, shown once by the page it lands on.
        const notice: PageNotice | null = result.notice ? { text: result.notice.text, tone: "success" } : null;
        navigate(result.show_path, { state: { notice } });
        return;
      }
      refuse(result.field_errors, result.form_errors);
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
    } finally {
      if (!leaving) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  const errorsOf = (name: FieldName): ReactNode =>
    (fieldErrors[name] ?? []).map((message, index) => (
      <p key={index} className="mt-1 text-xs text-red-600">
        {message}
      </p>
    ));
  const invalid = (name: FieldName) => (fieldErrors[name]?.length ?? 0) > 0 || undefined;

  return (
    <form noValidate onSubmit={submit} className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
      {formErrors.length > 0 ? (
        <div className="mb-2 rounded bg-red-50 p-2 text-sm text-red-700">
          {formErrors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-start">
        <div>
          <label htmlFor="selfform-label" className="mb-1 block text-sm text-slate-700">
            {`${form.labels.label} *`}
          </label>
          <input
            id="selfform-label"
            name="label"
            type="text"
            maxLength={MAX_LABEL_LENGTH}
            value={label}
            aria-invalid={invalid("label")}
            className={BOXED}
            onChange={(event) => {
              setLabel(event.target.value);
              clearError("label");
            }}
          />
          <p className="mt-1 text-xs text-slate-500">{form.help.label}</p>
          {errorsOf("label")}
        </div>
        <div>
          <label htmlFor="selfform-branch" className="mb-1 block text-sm text-slate-700">
            {form.branch_required ? `${form.labels.branch} *` : form.labels.branch}
          </label>
          <Select
            id="selfform-branch"
            name="branch"
            value={branch}
            onChange={(value) => {
              setBranch(value);
              clearError("branch");
            }}
            options={branchOptions}
            required={form.branch_required}
            invalid={invalid("branch")}
            className={BOXED}
          />
          {errorsOf("branch")}
        </div>
        <div>
          <label htmlFor="selfform-hours" className="mb-1 block text-sm text-slate-700">
            {form.labels.hours}
          </label>
          <input
            id="selfform-hours"
            name="hours"
            type="number"
            min={1}
            max={form.max_hours}
            step={1}
            value={hours}
            aria-invalid={invalid("hours")}
            className={BOXED}
            onChange={(event) => {
              setHours(event.target.value);
              clearError("hours");
            }}
          />
          <p className="mt-1 text-xs text-slate-500">{form.help.hours}</p>
          {errorsOf("hours")}
        </div>
        <div className="sm:pt-6">
          {/* pt-6 = the label row (1.25rem line + 0.25rem gap) so the button sits level with the boxes */}
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Холбоос үүсгэх
          </button>
        </div>
      </div>
    </form>
  );
}
