import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useSaveApproval, type LeaveApprovalOut, type LeaveStringChoiceOut } from "../../api/leaveSetup";
import type { ApiFailure } from "../../api/mutate";
import { BOXED } from "../../widgets/FormFields";
import { Select } from "../../widgets/Select";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The approval steps of the settings page (port of the first form in app/leave/templates/leave/settings.html and
// ApprovalSettingsForm in app/leave/forms.py). Labels, help texts and classes are copied from the template. The second
// step shows only once the first is chosen, and it is emptied when the first is cleared (the server forces that too).
// A refused save shows the step's message under its box and the others in the red box at the top.
type Errors = Record<string, string[]>;
const STEP_NAMES = ["step1", "step2"];

export interface ApprovalFormProps {
  approval: LeaveApprovalOut;
  step1Choices: LeaveStringChoiceOut[];
  step2Choices: LeaveStringChoiceOut[];
}

export function ApprovalForm({ approval, step1Choices, step2Choices }: ApprovalFormProps) {
  const save = useSaveApproval();
  const [step1, setStep1] = useState(approval.step1);
  const [step2, setStep2] = useState(approval.step2);
  const [fieldErrors, setFieldErrors] = useState<Errors>({});
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const toOptions = (list: LeaveStringChoiceOut[]) => list.map((choice) => ({ value: choice.value, label: choice.label }));

  const pickStep1 = (value: string) => {
    setStep1(value);
    if (value === "") setStep2("");
    setSaved(false);
  };

  // A refused save: the step messages under their boxes, the stray ones and the form's own at the top.
  const refuse = (fe: Errors, messages: string[]) => {
    const stray = Object.entries(fe)
      .filter(([key]) => !STEP_NAMES.includes(key))
      .flatMap(([, list]) => list);
    const top = [...messages, ...stray];
    const anyFieldMessage = Object.values(fe).some((list) => list.length > 0);
    setFieldErrors(fe);
    setTopErrors(top.length > 0 ? top : anyFieldMessage ? [] : [SAVE_FAILED_TEXT]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      const result = await save.mutateAsync({ step1, step2: step1 === "" ? "" : step2 });
      if (result.ok) {
        setFieldErrors({});
        setTopErrors([]);
        setSaved(true);
      } else {
        setSaved(false);
        const messages = [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
        refuse(result.field_errors, messages);
      }
    } catch (error) {
      setSaved(false);
      const failure = error as Partial<ApiFailure>;
      refuse(failure.fieldErrors ?? {}, failure.formErrors ?? []);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  const errorsOf = (name: string): ReactNode =>
    (fieldErrors[name] ?? []).map((message, index) => (
      <span key={index} className="block text-xs text-red-600">
        {message}
      </span>
    ));

  return (
    <form noValidate onSubmit={submit} className="mt-8 max-w-2xl rounded-xl border border-slate-200 bg-surface p-6">
      <h2 className="font-medium">Чөлөөний хүсэлтийг хэн батлах вэ</h2>
      <p className="mt-1 text-sm text-slate-500">
        Батлахгүй гэж сонговол ажилтан хүсэлт гаргах боломжгүй, HR чөлөөг шууд бүртгэнэ. «Шууд удирдлага» гэж сонговол ажилтны
        шууд удирдлага батална. Роль сонговол тухайн ролийн хэрэглэгчид батална.
      </p>
      <p className="mt-1 text-sm text-slate-500">
        Сонгосон шатанд батлах хүн байхгүй бол (роль хоосон, удирдлагагүй гэх мэт) батлах эрхтэй хэрэглэгч батална. Тэр ч байхгүй
        бол Админ хэрэглэгчид очно.
      </p>

      {topErrors.length > 0 ? (
        <div className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {topErrors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      ) : null}

      <div className="mt-4">
        <label className="block text-sm">
          Чөлөө батлах
          <Select
            name="step1"
            value={step1}
            onChange={pickStep1}
            options={toOptions(step1Choices)}
            invalid={(fieldErrors.step1?.length ?? 0) > 0 || undefined}
            className={BOXED}
          />
          {errorsOf("step1")}
        </label>
        <p className="mt-1 text-xs text-slate-500">
          Нэг шаттай бол энд л сонгоно. Батлахгүй бол хоёрдугаар шат ч хүчингүй болно.
        </p>
      </div>

      {step1 !== "" ? (
        <div className="mt-4">
          <label className="block text-sm">
            Дараа нь батлах
            <Select
              name="step2"
              value={step2}
              onChange={(value) => {
                setStep2(value);
                setSaved(false);
              }}
              options={toOptions(step2Choices)}
              invalid={(fieldErrors.step2?.length ?? 0) > 0 || undefined}
              className={BOXED}
            />
            {errorsOf("step2")}
          </label>
          <p className="mt-1 text-xs text-slate-500">
            Заавал биш. Сонгосон бол эхний шатаар батлагдсаны дараа энэ шатаар батлагдана. Хоосон бол нэг шаттай.
          </p>
        </div>
      ) : null}

      <div className="mt-4 flex items-center justify-end gap-3">
        {saved ? <span className="text-sm text-slate-600">Хадгалагдлаа</span> : null}
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
        >
          Хадгалах
        </button>
      </div>
    </form>
  );
}
