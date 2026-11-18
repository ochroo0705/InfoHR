import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { invalidateEmployee, useCreateLogin } from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { BOXED } from "../../widgets/FormFields";
import { Modal } from "../../widgets/Modal";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The «Нэвтрэх эрх үүсгэх» pop-up. Step 1 is the create-login form of `employees/_modal.html` (one box, «Нэвтрэх нэр»,
// «Болих» and «Хадгалах»). Step 2 is the one-time password pop-up of `employees/_password_shown.html`: the password is
// shown once and kept only in this component's state (never in the query cache, a log or the URL). Its «Хаах» refetches
// the header (the login now exists) and closes. Step 2 is not closable: no ✕, Escape and an outside click do nothing
// (UI_RULES §6a).

export type LoginModalProps = {
  pk: number;
  open: boolean;
  // Called once the pop-up may close. The parent sets open to false.
  onClose: () => void;
};

type Shown = { username: string; password: string };

const MAX_USERNAME = 150;

export function LoginModal({ pk, open, onClose }: LoginModalProps) {
  const queryClient = useQueryClient();
  const createLogin = useCreateLogin(pk);
  const [username, setUsername] = useState("");
  const [fieldErrors, setFieldErrors] = useState<string[]>([]);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  // A ref, not state: a second Enter or click in the same tick sends nothing.
  const inFlight = useRef(false);
  const errorId = useId();

  const submit = async () => {
    if (inFlight.current || shown !== null) return;
    inFlight.current = true;
    setPending(true);
    setFieldErrors([]);
    setFormErrors([]);
    try {
      const result = await createLogin.mutateAsync(username.trim());
      // The mutation keeps its last answer, which holds the password. Drop it, so only the state below has it.
      createLogin.reset();
      setShown({ username: result.username, password: result.password });
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      const names = failure.fieldErrors?.username ?? [];
      const messages = failure.formErrors ?? [];
      setFieldErrors(names);
      // A refusal that names the box shows its message there; anything else gets the red box.
      setFormErrors(messages.length > 0 || names.length > 0 ? messages : [SAVE_FAILED_TEXT]);
      // A refusal with a form message (the employee already has a login, say): the header is refetched, so the stale
      // «Нэвтрэх эрх үүсгэх» button goes. The pop-up stays with its message.
      if (messages.length > 0) void invalidateEmployee(queryClient, pk);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  // «Хаах» of the password step: the header refetches (the login now shows there), the pop-up closes, the password goes.
  const finish = () => {
    void invalidateEmployee(queryClient, pk);
    onClose();
    setShown(null);
    setUsername("");
  };

  if (shown !== null) {
    // A separate Modal (keyed), so the typed-input mark of step 1 does not follow into step 2. Its close is only «Хаах».
    return (
      <Modal key="password" open={open} onClose={onClose} closable={false} noAnim width="max-w-md" title="Түр нууц үг">
        <p className="text-sm text-slate-600">Нэвтрэх нэр</p>
        <p className="mb-3 font-mono text-base">{shown.username}</p>
        <p className="text-sm text-slate-600">Түр нууц үг</p>
        <p className="mb-3 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-lg tracking-wider select-all">
          {shown.password}
        </p>
        <p className="text-sm text-red-700">Энэ нууц үгийг зөвхөн одоо нэг удаа харуулна. Ажилтанд өгөөд хадгалахгүй байгаарай.</p>
        <p className="mt-2 text-xs text-slate-500">Ажилтан анх нэвтрэхдээ нууц үгээ өөрөө солино.</p>
        <div className="flex justify-end pt-4">
          <button
            type="button"
            onClick={finish}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Хаах
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal key="form" open={open} onClose={onClose} title="Нэвтрэх эрх үүсгэх">
      <form
        noValidate
        className="space-y-3"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void submit();
        }}
      >
        {formErrors.length > 0 ? (
          <div className="rounded bg-red-50 p-2 text-sm text-red-700">
            {formErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        <label className="block text-sm">
          Нэвтрэх нэр *
          <input
            name="username"
            type="text"
            maxLength={MAX_USERNAME}
            value={username}
            autoComplete="off"
            aria-invalid={fieldErrors.length > 0 || undefined}
            aria-describedby={fieldErrors.length > 0 ? errorId : undefined}
            onChange={(event) => {
              setUsername(event.target.value);
              setFieldErrors([]);
            }}
            className={BOXED}
          />
          {fieldErrors.length > 0 ? (
            <span id={errorId} className="block text-xs text-red-600">
              {fieldErrors.map((message, index) => (
                <span key={index} className="block">
                  {message}
                </span>
              ))}
            </span>
          ) : null}
        </label>
        <p className="text-xs text-slate-500">Нууц үг автоматаар үүснэ. Гарсны дараа ажилтанд өгнө; анх нэвтрэхдээ солино.</p>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
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
    </Modal>
  );
}
