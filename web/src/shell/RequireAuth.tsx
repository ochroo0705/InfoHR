import { useEffect, type ReactNode } from "react";
import { Navigate } from "react-router";
import { redirectToLogin } from "../api/client";
import { useMeta } from "./useMeta";

// Guards every signed-in route. While the meta answer is pending, or when nobody is signed in, it renders only the
// bare shell background (never an empty bar). A signed-in user who must change the password goes to
// /password/change, unless the route itself is that page (allowForced, used by Task 10). Everyone else gets the
// children.
export function RequireAuth({ children, allowForced = false }: { children: ReactNode; allowForced?: boolean }) {
  const { data, error } = useMeta();
  const anonymous = data !== undefined && data.user === null;
  // No answer (network failure) or a server error: say so in the shell area instead of a blank screen (spec 12a.5).
  const status = (error as (Error & { status?: number }) | null)?.status;
  // Only when there is no answer at all. A failed background refetch keeps the data, so the shell stays rendered.
  const unreachable = !data && !!error && (status === undefined || status >= 500);

  useEffect(() => {
    if (anonymous) redirectToLogin();
  }, [anonymous]);

  if (unreachable) {
    return (
      <div className="min-h-dvh">
        <p className="mx-auto max-w-6xl px-4 py-6 text-sm text-red-600">
          Компанийн сервертэй холбогдож чадсангүй. Дахин оролдож байна…
        </p>
      </div>
    );
  }
  if (!data || !data.user) return <div className="min-h-dvh" />;
  if (data.user.must_change_password && !allowForced) {
    return <Navigate to="/password/change" replace />;
  }
  return <>{children}</>;
}
