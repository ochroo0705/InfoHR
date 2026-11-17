import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, type ErrorBody } from "../api/client";
import { Button } from "../components/ui/button";
import { useMeta } from "../shell/useMeta";

// The password change page (app/templates/registration/password_change.html). A forced user (must_change_password)
// sees the hint and no old-password field: the same rule as accounts/password_change.py form_class_for.
const NETWORK_ERROR = "Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.";
const FORCED_HINT = "Түр нууц үгээ өөрийн шинэ нууц үгээр солино уу.";
// Same text as accounts/forms.py RULES_HINT.
const RULES_HINT = "Дор хаяж 8 тэмдэгт; том, жижиг үсэг, тоо тус бүр нэгээс доошгүй.";

type FieldName = "old_password" | "new_password1" | "new_password2";
type Values = Record<FieldName, string>;

const EMPTY: Values = { old_password: "", new_password1: "", new_password2: "" };

export default function PasswordChangePage() {
  const { data: meta } = useMeta();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [values, setValues] = useState<Values>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldName, string[]>>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);

  const user = meta?.user;
  if (!user) return null;
  const forced = user.must_change_password;

  const fields: { name: FieldName; label: string; hint: string; autoComplete: string }[] = [
    ...(forced ? [] : [{ name: "old_password" as const, label: "Хуучин нууц үг", hint: "", autoComplete: "current-password" }]),
    { name: "new_password1", label: "Шинэ нууц үг", hint: RULES_HINT, autoComplete: "new-password" },
    { name: "new_password2", label: "Шинэ нууц үг дахин", hint: "", autoComplete: "new-password" },
  ];

  function setValue(name: FieldName, value: string) {
    setValues((v) => ({ ...v, [name]: value }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setFormErrors([]);
    setFieldErrors({});
    // A forced user has no old-password box; the server ignores old_password for a temporary password, so it is sent empty.
    const body = forced ? { ...values, old_password: "" } : values;

    try {
      const { error, response } = await api.POST("/api/v1/auth/password", { body });
      if (response.status === 204) {
        // Wait for the fresh meta answer, so the next page does not see must_change_password and bounce back here.
        await queryClient.invalidateQueries({ queryKey: ["meta"] });
        navigate("/");
        return;
      }
      setPending(false);
      if (response.status === 400) {
        const errors = error as ErrorBody | undefined;
        setFieldErrors(errors?.field_errors ?? {});
        setFormErrors(errors?.form_errors ?? []);
        // Same as Django's re-rendered form: the password boxes come back empty.
        setValues(EMPTY);
      } else {
        setFormErrors([NETWORK_ERROR]);
      }
    } catch {
      setPending(false);
      setFormErrors([NETWORK_ERROR]);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-xl bg-surface p-8 shadow-sm border border-slate-200">
      <h1 className="text-xl font-semibold mb-2">Нууц үг солих</h1>
      {forced ? <p className="mb-6 text-sm text-slate-600">{FORCED_HINT}</p> : null}
      <form onSubmit={onSubmit} className="space-y-4">
        {formErrors.length > 0 ? (
          <p className="rounded bg-red-50 p-2 text-sm text-red-700">{formErrors.join(" ")}</p>
        ) : null}
        {fields.map((field, index) => {
          const errors = fieldErrors[field.name];
          return (
            <label key={field.name} className="block text-sm">
              {field.label}
              <input
                type="password"
                name={field.name}
                autoFocus={index === 0}
                required
                autoComplete={field.autoComplete}
                value={values[field.name]}
                onChange={(e) => setValue(field.name, e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
              {errors && errors.length > 0 ? (
                errors.map((message) => (
                  <span key={message} className="block text-xs text-red-600">
                    {message}
                  </span>
                ))
              ) : field.hint ? (
                <span className="mt-1 block text-xs text-slate-500">{field.hint}</span>
              ) : null}
            </label>
          );
        })}
        <Button type="submit" className="w-full" disabled={pending}>
          Хадгалах
        </Button>
      </form>
    </div>
  );
}
