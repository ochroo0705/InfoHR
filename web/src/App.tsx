import { lazy, Suspense, useEffect } from "react";
import { Route, Routes } from "react-router";
import { AppShell } from "./shell/AppShell";
import { RequireAuth } from "./shell/RequireAuth";
import LoginPage from "./routes/LoginPage";
import PasswordChangePage from "./routes/PasswordChangePage";
import { NotFound } from "./routes/ErrorPage";
import { MePage } from "./screens/me/MePage";
import { TodayPage } from "./screens/today/TodayPage";
import { EmployeePage } from "./screens/employee/EmployeePage";
import { CompanyPage } from "./screens/company/CompanyPage";
import { OrdersPage } from "./screens/orders/OrdersPage";
import { OrdersPrintPage } from "./screens/orders/OrdersPrintPage";
import { HirePage } from "./screens/hire/HirePage";
import { SlotsPage } from "./screens/slots/SlotsPage";
import { LeavePage } from "./screens/leave/LeavePage";
import { LeaveRequestsPage } from "./screens/leaveRequests/LeaveRequestsPage";
import { ListsIndexPage } from "./screens/lists/ListsIndexPage";
import { ListPage } from "./screens/lists/ListPage";
import { MeaningPage } from "./screens/lists/MeaningPage";
import { SelfFormListPage } from "./screens/selfforms/SelfFormListPage";
import { SelfFormShowPage } from "./screens/selfforms/SelfFormShowPage";
import { EmployeeLogPage } from "./screens/logs/EmployeeLogPage";
import { MinePage } from "./screens/checklists/MinePage";
import { SystemLogPage } from "./screens/logs/SystemLogPage";
import { Landing } from "./routes/Landing";
import { WelcomeRoute } from "./routes/WelcomeRoute";
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
        {/* Public landing page: outside RequireAuth and AppShell. It shows only while the welcome_enabled flag is on. */}
        <Route path="/welcome" element={<WelcomeRoute />} />
        {/* Standalone like Django's print page: no AppShell, but signed in. */}
        <Route
          path="/employees/orders/print/"
          element={
            <RequireAuth>
              <OrdersPrintPage />
            </RequireAuth>
          }
        />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Landing />} />
          <Route path="/employees/today/" element={<TodayPage />} />
          <Route path="/me/" element={<MePage />} />
          <Route path="/employees/company/" element={<CompanyPage />} />
          <Route path="/employees/new/" element={<HirePage />} />
          <Route path="/employees/orders/" element={<OrdersPage />} />
          <Route path="/employees/slots/" element={<SlotsPage />} />
          <Route path="/leave/" element={<LeavePage />} />
          <Route path="/leave/requests/" element={<LeaveRequestsPage />} />
          <Route path="/employees/self-forms/" element={<SelfFormListPage />} />
          <Route path="/employees/self-forms/:pk/" element={<SelfFormShowPage />} />
          <Route path="/employees/:pk/" element={<EmployeePage />} />
          <Route path="/logs/" element={<EmployeeLogPage />} />
          <Route path="/logs/system/" element={<SystemLogPage />} />
          <Route path="/lists/" element={<ListsIndexPage />} />
          <Route path="/lists/meaning/" element={<MeaningPage />} />
          <Route path="/lists/:slug/" element={<ListPage />} />
          <Route path="/checklists/mine/" element={<MinePage />} />
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
