import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { useEmployee, type EmployeeHeadOut } from "../../api/employee";
import { AppLink } from "../../lib/AppLink";
import { useUnsavedGuard } from "../../lib/unsaved";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { ActivityDrawer } from "./ActivityDrawer";
import { readActivityOpen, writeActivityOpen } from "./activityStore";
import { EmployeePopups } from "./EmployeePopups";
import { Header } from "./Header";
import { OneTimeLogin } from "./OneTimeLogin";
import { PageFormElement, PageFormProvider } from "./PageForm";
import { PersonalSection } from "./PersonalSection";
import { Rail } from "./Rail";
import { SalarySection } from "./SalarySection";
import { SaveBar } from "./SaveBar";
import { WorkSection } from "./WorkSection";
import { showSection, TAB_ON_CLASS, useScrollSpy } from "./scrollSpy";

// Port of app/employees/templates/employees/detail.html: the employee page at /employees/<pk>/. Classes, Mongolian
// text, ids and the section order are copied from the template. The page only renders what the API sends.
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
// detail.html: {% block main_width %}max-w-none px-6{% endblock %}
const MAIN_WIDTH = "max-w-none px-6";
// The personal group key the address names, as in #personal-edu (the group <details> with data-pgroup="edu").
const PERSONAL_HASH = "#personal-";

// The reader's first use of the page, which ends the load-time hash scroll.
const USER_EVENTS: string[] = ["wheel", "touchstart", "keydown", "pointerdown"];

type OneTimeLoginOut = NonNullable<EmployeeHeadOut["one_time_login"]>;

// Loads the employee. A non-numeric pk is the 404 screen before any request is made.
export function EmployeePage() {
  const { pk } = useParams();
  if (!pk || !/^\d+$/.test(pk)) return <NotFound />;
  // key: a different employee is a new view, so no edit or registry flag of the last one carries over.
  return <EmployeeView key={pk} pk={Number(pk)} />;
}

function EmployeeView({ pk }: { pk: number }) {
  // Closing or reloading the tab asks while anything on the page is unsaved (unsaved.ts). In-app leaving is guarded by
  // useTransitionNavigate.
  useUnsavedGuard();
  const employee = useEmployee(pk);
  const head = employee.data;

  // The data check comes first: a failed background refetch keeps the page on screen (see the alert in the body).
  if (!head) {
    if (employee.error) {
      const status = (employee.error as { status?: number }).status;
      if (status === 403) return <Forbidden />;
      if (status === 404) return <NotFound />;
      return <p className="text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p>;
    }
    // Loading shows nothing here: the shell's loading bar is the only feedback, as on the Django page.
    return null;
  }

  // The pop-ups of the events and orders live here: the header's event menu and the work and salary rows open them.
  return (
    <EmployeePopups pk={pk}>
      <EmployeeBody pk={pk} head={head} failed={!!employee.error} />
    </EmployeePopups>
  );
}

function EmployeeBody({ pk, head, failed }: { pk: number; head: EmployeeHeadOut; failed: boolean }) {
  useMainWidth(MAIN_WIDTH);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  const fullName = head.full_name;
  useEffect(() => {
    const previous = document.title;
    document.title = fullName + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [fullName]);

  // The one-time login is kept in this page's state once it has arrived: a refetch that returns null must not remove
  // the card. Only its «Ойлголоо, хаах» button removes it (OneTimeLogin keeps its own hidden state).
  const [latched, setLatched] = useState<OneTimeLoginOut | null>(head.one_time_login ?? null);
  useEffect(() => {
    if (head.one_time_login) setLatched(head.one_time_login);
  }, [head.one_time_login]);
  const login = latched ?? head.one_time_login ?? null;

  // The sections on the page follow the rights in `can`. The scroll-spy marks the one in view.
  const names = ["work"];
  if (head.can.view_salary) names.push("salary");
  if (head.can.view_personal) names.push("personal");
  const namesKey = names.join("|");
  const [active, markSection] = useScrollSpy(names);

  // Load-time hash: an address like #salary (or #personal-edu) scrolls to that section at once and marks it, as
  // detail.html does (setActive after the scroll). This effect is declared after useScrollSpy, so it runs after the
  // spy's first mark and its mark is the one that stays. The personal group key is read once and handed to PersonalSection.
  const [openGroup] = useState<string | undefined>(() => {
    const hash = window.location.hash;
    return hash.startsWith(PERSONAL_HASH) ? hash.slice(PERSONAL_HASH.length) : undefined;
  });
  // The section's body loads in its own query, after the head, so its height changes later: the scroll is re-applied on
  // each size change of that section, until the reader first scrolls, wheels, touches, presses a key or clicks.
  // The reader's first use ends it for the page view (hashDone survives the effect re-running).
  const hashDone = useRef(false);
  useEffect(() => {
    if (hashDone.current) return;
    const name = window.location.hash.slice(1).split("-")[0];
    if (!namesKey.split("|").includes(name)) return;
    const el = document.getElementById("tab-" + name);
    const apply = () => {
      showSection(name, true);
      markSection(name);
    };
    let resizer: ResizeObserver | null = null;
    const detach = () => {
      resizer?.disconnect();
      for (const ev of USER_EVENTS) window.removeEventListener(ev, onUser);
    };
    const onUser = () => {
      hashDone.current = true;
      detach();
    };
    for (const ev of USER_EVENTS) window.addEventListener(ev, onUser, { passive: true });
    apply();
    if (el && typeof ResizeObserver !== "undefined") {
      resizer = new ResizeObserver(apply);
      resizer.observe(el);
    }
    return detach;
  }, [namesKey, markSection]);

  // The «Түүх» drawer: the state is kept across pages on wide screens (ActivityDrawer's storage helpers).
  const [drawerOpen, setDrawerOpen] = useState(readActivityOpen);
  const openActivity = () => {
    setDrawerOpen(true);
    writeActivityOpen(true);
  };
  const closeActivity = () => {
    setDrawerOpen(false);
    writeActivityOpen(false);
  };

  const tabClass = (name: string) => (active === name ? `tab ${TAB_ON_CLASS}` : "tab");
  const tabAria = (name: string) => (active === name ? "page" : undefined);

  // The page form (the header, work, bank and salary boxes) is for managers and salary managers only. Its provider wraps
  // the header and the sections, and the save bar sits after the tabs card, as #save-bar does in detail.html.
  const pageFormOn = head.can.manage || head.can.manage_salary;

  return (
    <PageFormProvider pk={pk} enabled={pageFormOn} section={active}>
      <PageFormElement />
      {failed ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      <AppLink to="/employees/" className="text-sm text-slate-500 hover:text-violet-700 lg:hidden">
        ← Ажилтнууд
      </AppLink>
      {login ? <OneTimeLogin login={login} /> : null}
      <div className="mt-2 lg:flex lg:items-start lg:gap-8">
        <Rail head={head} active={active} />
        <div className="min-w-0 flex-1">
          <Header head={head} onOpenActivity={openActivity} />
          <div className="mt-6 rounded-xl border border-slate-200 bg-surface">
            <nav
              className="flex gap-6 sticky top-14 z-20 bg-surface border-b lg:hidden border-slate-200 px-6"
              aria-label="Ажилтны хэсгүүд"
            >
              <a href="#work" className={tabClass("work")} aria-current={tabAria("work")}>
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="3" y="6" width="14" height="10" rx="2" />
                  <path d="M7.5 6V4.5A1.5 1.5 0 0 1 9 3h2a1.5 1.5 0 0 1 1.5 1.5V6M3 10.5h14" />
                </svg>
                Ажил
              </a>
              {head.can.view_salary ? (
                <a href="#salary" className={tabClass("salary")} aria-current={tabAria("salary")}>
                  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="2.5" y="5" width="15" height="10" rx="2" />
                    <circle cx="10" cy="10" r="2.2" />
                    <path d="M5.5 8v4M14.5 8v4" />
                  </svg>
                  Цалин, даатгал
                </a>
              ) : null}
              {head.can.view_personal ? (
                <a href="#personal" className={tabClass("personal")} aria-current={tabAria("personal")}>
                  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="10" cy="7" r="3" />
                    <path d="M4 17a6 6 0 0 1 12 0" />
                  </svg>
                  Хувийн
                </a>
              ) : null}
            </nav>
            <section id="tab-work" className="scroll-mt-28 lg:scroll-mt-20 p-6">
              <h2 className="mb-4 text-lg font-semibold text-slate-900">Ажил</h2>
              <WorkSection pk={pk} setup={head.setup} />
            </section>
            {head.can.view_salary ? (
              <section id="tab-salary" className="scroll-mt-28 lg:scroll-mt-20 border-t border-slate-200 p-6">
                <h2 className="mb-4 text-lg font-semibold text-slate-900">Цалин, даатгал</h2>
                <SalarySection pk={pk} />
              </section>
            ) : null}
            {head.can.view_personal ? (
              <section id="tab-personal" className="scroll-mt-28 lg:scroll-mt-20 border-t border-slate-200 p-6">
                <h2 className="mb-4 text-lg font-semibold text-slate-900">Хувийн</h2>
                <PersonalSection pk={pk} openGroup={openGroup} />
              </section>
            ) : null}
          </div>
          {pageFormOn ? <SaveBar /> : null}
        </div>
      </div>
      {/* The drawer sits outside the page form (its own note form posts nothing to the page). */}
      <ActivityDrawer
        pk={pk}
        count={head.activity_count}
        canManage={head.can.manage}
        open={drawerOpen}
        onClose={closeActivity}
      />
    </PageFormProvider>
  );
}
