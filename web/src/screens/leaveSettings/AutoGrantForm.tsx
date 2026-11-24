import { useRef, useState, type FormEvent } from "react";
import { useSaveAutoGrant } from "../../api/leaveSetup";
import type { ApiFailure } from "../../api/mutate";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// The automatic annual grant switch of the settings page (port of the second form in
// app/leave/templates/leave/settings.html). Classes and texts are copied from the template. Its save is its own: it posts the
// flag alone and shows «Хадгалагдлаа» on ok. A refused save shows its messages in the red box at the top.
export interface AutoGrantFormProps {
  auto: boolean;
}

export function AutoGrantForm({ auto }: AutoGrantFormProps) {
  const save = useSaveAutoGrant();
  const [checked, setChecked] = useState(auto);
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    try {
      const result = await save.mutateAsync({ auto_annual_grant: checked });
      if (result.ok) {
        setTopErrors([]);
        setSaved(true);
      } else {
        setSaved(false);
        const messages = [result.error, ...result.form_errors].filter((text): text is string => Boolean(text));
        setTopErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
      }
    } catch (error) {
      setSaved(false);
      const messages = (error as Partial<ApiFailure>).formErrors ?? [];
      setTopErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  return (
    <form noValidate onSubmit={submit} className="mt-8 max-w-2xl rounded-xl border border-slate-200 bg-surface p-6">
      <h2 className="font-medium">Ээлжийн амралтын эрхийг автоматаар нэмэх</h2>
      <p className="mt-1 text-sm text-slate-500">
        Асаалттай үед ажлын жил бүрт хуулийн дагуух эрх автоматаар бичигдэнэ. Унтраалттай үед эрхийг гараар нэмнэ. Унтраасан
        нь бичигдсэн эрхийг устгахгүй.
      </p>
      {topErrors.length > 0 ? (
        <div className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {topErrors.map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      ) : null}
      <label className="mt-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          name="auto_annual_grant"
          checked={checked}
          onChange={(event) => {
            setChecked(event.target.checked);
            setSaved(false);
          }}
          className="rounded border-slate-300"
        />
        Ээлжийн амралтын эрхийг автоматаар нэмэх
      </label>
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
