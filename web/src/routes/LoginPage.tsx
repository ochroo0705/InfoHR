import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, nav, setCsrf, type ErrorBody } from "../api/client";
import { Button } from "../components/ui/button";

// Same text as app/templates/registration/login.html line 8.
const WRONG_CREDENTIALS = "Нэвтрэх нэр эсвэл нууц үг буруу байна.";
const NETWORK_ERROR = "Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.";

// Only in-app paths: "/x" is allowed; "//host", backslashes and absolute URLs fall back to "/".
function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return "/";
  }
  return next;
}

export default function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [csrfReady, setCsrfReady] = useState(false);
  const [pending, setPending] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .GET("/api/v1/meta")
      .then(({ data }) => {
        if (cancelled) return;
        if (data) {
          setCsrf(data.csrf);
          setCsrfReady(true);
        } else {
          setFormError(NETWORK_ERROR);
        }
      })
      .catch(() => {
        if (!cancelled) setFormError(NETWORK_ERROR);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csrfReady || pending) return;
    setPending(true);
    setFormError(null);

    try {
      const { data, error, response } = await api.POST("/api/v1/auth/login", {
        body: { username, password },
      });
      if (response.status === 200 && data) {
        // login() rotates the CSRF token: store the new one before any further request.
        setCsrf(data.csrf);
        if (data.must_change_password) {
          nav.assign("/password/change");
        } else {
          navigate(safeNext(params.get("next")));
        }
        return;
      }

      setPending(false);
      if (response.status === 400) {
        const body = error as ErrorBody | undefined;
        setFormError(body?.form_errors?.[0] ?? WRONG_CREDENTIALS);
        // Same as Django's re-rendered page: the password is cleared and focus returns to the username.
        setPassword("");
        usernameRef.current?.focus();
      } else {
        setFormError(NETWORK_ERROR);
      }
    } catch {
      setPending(false);
      setFormError(NETWORK_ERROR);
    }
  }

  // Same wrapper as app/templates/base.html: <div id="page"><main class="mx-auto max-w-6xl px-4 py-6">.
  return (
    <div id="page">
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="mx-auto mt-16 max-w-sm rounded-xl bg-surface p-8 shadow-sm border border-slate-200">
          <h1 className="text-xl font-semibold mb-6">MACS Human Capital — Нэвтрэх</h1>
          <form onSubmit={onSubmit} className="space-y-4">
            {formError && <p className="text-sm text-red-600">{formError}</p>}
            <label className="block text-sm" htmlFor="id_username">
              Нэвтрэх нэр
              <input
                id="id_username"
                ref={usernameRef}
                name="username"
                autoFocus
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm" htmlFor="id_password">
              Нууц үг
              <input
                id="id_password"
                type="password"
                name="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
            <Button type="submit" className="w-full" disabled={!csrfReady || pending}>
              Нэвтрэх
            </Button>
          </form>
        </div>
      </main>
    </div>
  );
}
