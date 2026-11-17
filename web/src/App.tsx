import { lazy, Suspense, useEffect } from "react";
import { Route, Routes } from "react-router";
import { AppShell } from "./shell/AppShell";
import { RequireAuth } from "./shell/RequireAuth";
import LoginPage from "./routes/LoginPage";
import PasswordChangePage from "./routes/PasswordChangePage";
import { NotFound } from "./routes/ErrorPage";
import { ConfirmProvider } from "./widgets/confirm";

// Development only: /__widgets shows the pop-up shell and the confirm dialog. In a production build this is null,
// and the lazy import is dropped with it.
const WidgetsPage = import.meta.env.DEV ? lazy(() => import("./routes/WidgetsPage")) : null;

export default function App() {
  useEffect(() => {
    document.documentElement.lang = "mn";
  }, []);

  return (
    <ConfirmProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<p>Нэвтэрсэн</p>} />
          {/* Any other path inside the signed-in shell. */}
          <Route path="*" element={<NotFound />} />
        </Route>
        {/* A forced user (must_change_password) is sent here by RequireAuth, so this route allows it. */}
        <Route
          element={
            <RequireAuth allowForced>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/password/change" element={<PasswordChangePage />} />
        </Route>
        {WidgetsPage ? (
          <Route
            path="/__widgets"
            element={
              <Suspense fallback={null}>
                <WidgetsPage />
              </Suspense>
            }
          />
        ) : null}
      </Routes>
    </ConfirmProvider>
  );
}
