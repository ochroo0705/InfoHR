import { useEffect, useState, type KeyboardEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { useSelfFormList, type SelfFormListRowOut } from "../../api/selfforms";
import { AppLink } from "../../lib/AppLink";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { Forbidden } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { SelfFormCreateForm, type PageNotice } from "./SelfFormCreateForm";

// Port of app/employees/templates/employees/selfform/list.html at /employees/self-forms/. The title, the classes, the
// responsive card/table layout and the words are copied from the template. The rows, the waiting count, the intro and
// the create form's description come from the API. A row opens its page (show_path); «Нээх» opens the hire page of a
// submitted form and does not open the row.
const TITLE = "Өөрөө бөглөх анкет";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page is full width (UI_RULES §4)
const EMPTY_TEXT = "Анкет бүртгэгдээгүй байна.";
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

// The date prefix of the «Хугацаа» cell, by the API's when_kind ("sent" = the submission time, "expires" = the expiry).
const WHEN_PREFIX: Record<string, string> = { sent: "Илгээсэн: ", expires: "Дуусах: " };

// The notice in router state ({ notice: { text, tone } }), or null.
function noticeIn(state: unknown): PageNotice | null {
  return (state as { notice?: PageNotice | null } | null)?.notice ?? null;
}

export function SelfFormListPage() {
  useMainWidth(MAIN_WIDTH);
  const query = useSelfFormList();
  const go = useTransitionNavigate();
  const location = useLocation();
  const navigate = useNavigate();
  // The notice is kept here after the router state is cleared, so a reload of the URL does not repeat it.
  const [notice, setNotice] = useState<PageNotice | null>(null);

  // Reads a notice from the router state once, then replaces the entry with the same URL and no state.
  useEffect(() => {
    const incoming = noticeIn(location.state);
    if (incoming === null) return;
    setNotice(incoming);
    navigate(location.pathname + location.search, { replace: true, state: null });
  }, [location.key, location.pathname, location.search, location.state, navigate]);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the manage right is refused on the first request: the forbidden screen, as the other pages.
  if (query.isError && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  const data = query.data;
  if (data === undefined) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED_TEXT}
      </p>
    ) : null;
  }

  // Enter on a focused row opens it, as a click does. Enter on the «Нээх» link keeps the link's own action.
  const openRow = (event: KeyboardEvent<HTMLTableRowElement>, row: SelfFormListRowOut) => {
    if (event.key !== "Enter" || event.target !== event.currentTarget) return;
    go(row.show_path);
  };

  return (
    <>
      <h1 className="text-xl font-semibold">{TITLE}</h1>
      <p className="mt-1 text-sm text-slate-500">{data.intro}</p>

      {notice ? (
        // The success box and the error box of list.html (its messages: green for success, red for error).
        <p
          role={notice.tone === "error" ? "alert" : "status"}
          className={
            notice.tone === "error"
              ? "mt-3 rounded bg-red-50 p-2 text-sm text-red-700"
              : "mt-3 rounded bg-emerald-50 p-2 text-sm text-emerald-800"
          }
        >
          {notice.text}
        </p>
      ) : null}
      {query.isError ? (
        <p role="alert" className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {LOAD_FAILED_TEXT}
        </p>
      ) : null}

      <SelfFormCreateForm form={data.form} />

      <p className="mt-4 text-sm font-medium text-slate-700">Хянах хүлээж буй: {data.waiting}</p>
      <div className="mt-2">
        <table className="w-full text-sm">
          <thead className="hidden text-left text-slate-500 md:table-header-group">
            <tr>
              <th className="py-2 font-normal">Нэр</th>
              <th className="font-normal">Салбар</th>
              <th className="font-normal">Төлөв</th>
              <th className="font-normal">Хугацаа</th>
              <th className="font-normal">
                <span className="sr-only md:not-sr-only">Үйлдэл</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr
                key={row.id}
                tabIndex={0}
                className="my-2 block cursor-pointer rounded-lg border border-slate-200 hover:bg-violet-50 md:my-0 md:table-row md:rounded-none md:border-0 md:border-t md:border-slate-200"
                onClick={() => go(row.show_path)}
                onKeyDown={(event) => openRow(event, row)}
              >
                <td className="block py-2 pl-3 pr-3 font-medium md:table-cell md:pl-0">{row.label}</td>
                <td className="block px-3 pb-1 text-slate-600 md:table-cell md:px-0 md:py-2">
                  <span className="text-xs text-slate-500 md:hidden">Салбар: </span>
                  {row.branch}
                </td>
                <td className="block px-3 pb-1 md:table-cell md:px-0 md:py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${row.badge}`}>{row.state}</span>
                </td>
                <td className="block px-3 pb-1 text-slate-600 md:table-cell md:px-0 md:py-2">
                  {row.when_label ? (
                    <>
                      <span className="text-xs text-slate-500 md:hidden">{WHEN_PREFIX[row.when_kind] ?? ""}</span>
                      {row.when_label}
                    </>
                  ) : null}
                </td>
                <td className="block px-3 pb-3 text-left md:table-cell md:px-0 md:py-2 md:text-right">
                  {row.hire_path ? (
                    <AppLink
                      to={row.hire_path}
                      onClick={(event) => event.stopPropagation()}
                      className="text-violet-700 hover:underline"
                    >
                      Нээх
                    </AppLink>
                  ) : null}
                </td>
              </tr>
            ))}
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-6 text-center text-slate-500">
                  {EMPTY_TEXT}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </>
  );
}
