import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router";
import {
  extendSelfForm,
  revokeSelfForm,
  useSelfFormShow,
  type SelfFormActionOut,
} from "../../api/selfforms";
import { AppLink } from "../../lib/AppLink";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { CopyLink } from "./CopyLink";
import type { PageNotice } from "./SelfFormCreateForm";

// Port of app/employees/templates/employees/selfform/show.html at /employees/self-forms/<pk>/. The title, the classes,
// the section order and the words are copied from the template. Sections come only from the API's flags: can_extend,
// can_revoke, purged, hire_path, decision and qr_svg. Every action result's show replaces the page data.
const PAGE_TITLE = "Өөрөө бөглөх анкет";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LIST_PATH = "/employees/self-forms/";
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
const LINK_BOX_ID = "selfform-link";
const QR_FALLBACK = "QR код харуулах боломжгүй байна. Холбоосыг дээрээс хуулж илгээнэ үү.";
const MAX_HOURS = 8760;

// The notice in router state ({ notice: { text, tone } }), or null.
function noticeIn(state: unknown): PageNotice | null {
  return (state as { notice?: PageNotice | null } | null)?.notice ?? null;
}

// The page for one form. The view is keyed by pk, so another form starts with no notice or typed hours of this one.
export function SelfFormShowPage() {
  const { pk } = useParams();
  if (!pk || !/^\d+$/.test(pk)) return <NotFound />;
  return <SelfFormShowView key={pk} pk={Number(pk)} />;
}

function SelfFormShowView({ pk }: { pk: number }) {
  const query = useSelfFormShow(pk);
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  // The notice of the last action, or the one that came in router state. Kept here after the state is cleared.
  const [notice, setNotice] = useState<PageNotice | null>(null);
  const [hours, setHours] = useState("");
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  // Reads a notice from the router state once, then replaces the entry with the same URL and no state.
  useEffect(() => {
    const incoming = noticeIn(location.state);
    if (incoming === null) return;
    setNotice(incoming);
    navigate(location.pathname + location.search, { replace: true, state: null });
  }, [location.key, location.pathname, location.search, location.state, navigate]);

  const label = query.data?.label;
  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    if (label === undefined) return;
    const previous = document.title;
    document.title = `${label} · ${PAGE_TITLE}${PAGE_TITLE_SUFFIX}`;
    return () => {
      document.title = previous;
    };
  }, [label]);

  const data = query.data;
  if (data === undefined) {
    if (!query.isError) return null;
    const status = (query.error as { status?: number } | null)?.status;
    if (status === 403) return <Forbidden />;
    if (status === 404) return <NotFound />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED_TEXT}
      </p>
    );
  }

  // One action at a time. Its result's notice shows in the box of its tone, written or refused alike.
  const runAction = async (action: () => Promise<SelfFormActionOut>): Promise<SelfFormActionOut | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    setPending(true);
    try {
      const result = await action();
      setNotice({ text: result.notice.text, tone: result.notice.tone });
      return result;
    } catch {
      setNotice({ text: SAVE_FAILED_TEXT, tone: "error" });
      return null;
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  // An empty box is sent as null: the company default hours.
  const onExtend = async (event: FormEvent) => {
    event.preventDefault();
    const typed = hours.trim();
    const result = await runAction(() => extendSelfForm(queryClient, pk, typed === "" ? null : typed));
    if (result?.ok) setHours("");
  };

  const onRevoke = async (event: FormEvent) => {
    event.preventDefault();
    await runAction(() => revokeSelfForm(queryClient, pk));
  };

  const decision = data.decision;

  return (
    <>
      <p className="text-sm">
        <AppLink to={LIST_PATH} className="text-violet-700 hover:underline">
          ← Бүх анкет
        </AppLink>
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{data.label}</h1>
        <span className={`rounded-full px-2 py-0.5 text-xs ${data.badge}`}>{data.state}</span>
      </div>

      {notice ? (
        // The success box and the error box of show.html (its messages: green for success, red for error).
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

      <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-6">
        <dt className="text-slate-500">Салбар</dt>
        <dd>{data.branch}</dd>
        <dt className="text-slate-500">Үүсгэсэн</dt>
        <dd>{data.created_label}</dd>
        {data.when_title ? (
          <>
            <dt className="text-slate-500">{data.when_title}</dt>
            <dd>{data.when_label}</dd>
          </>
        ) : null}
      </dl>

      <section className="mt-6">
        <h2 className="text-base font-semibold">Холбоос</h2>
        <p className="mt-1 text-sm text-slate-500">
          Энэ холбоосыг ажилтанд илгээнэ, эсвэл доорх QR кодыг утсаараа уншуулна. Ажилтан холбоосоор өөрөө бөглөнө;
          нэвтрэх шаардлагагүй.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            id={LINK_BOX_ID}
            type="text"
            readOnly
            value={data.link}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
          />
          <CopyLink targetId={LINK_BOX_ID} />
        </div>
        {data.qr_svg ? (
          // The server draws the QR code from path data only (no markup from the user is in it), so the SVG is inserted
          // as markup. Do not put any user-typed text into this value.
          <div
            role="img"
            aria-label="QR код"
            className="mt-4 inline-block rounded-lg border border-slate-200 bg-white p-3"
            dangerouslySetInnerHTML={{ __html: data.qr_svg }}
          />
        ) : (
          <p className="mt-4 text-sm text-slate-500">{QR_FALLBACK}</p>
        )}
      </section>

      {data.purged ? (
        <section className="mt-6 border-t border-slate-200 pt-4">
          <p className="text-sm text-slate-700">
            Хариулт устгагдсан. Хадгалах хугацаа дууссан тул ажилтны бөглөсөн хариулт, зураг байхгүй.
          </p>
        </section>
      ) : null}

      {data.can_extend ? (
        <section className="mt-6 border-t border-slate-200 pt-4">
          <h2 className="text-base font-semibold">Хугацаа сунгах</h2>
          <form onSubmit={onExtend} className="mt-2 flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="extend-hours" className="mb-1 block text-sm text-slate-700">
                Хүчинтэй хугацаа (цаг)
              </label>
              <input
                id="extend-hours"
                type="number"
                name="hours"
                min={1}
                max={MAX_HOURS}
                placeholder={String(data.default_hours)}
                value={hours}
                onChange={(event) => setHours(event.target.value)}
                className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-slate-500">Хоосон бол {data.default_hours} цаг нэмнэ.</p>
            </div>
            <button
              type="submit"
              disabled={pending}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Сунгах
            </button>
          </form>

          {data.can_revoke ? (
            // The confirm without a pop-up (UI_RULES §3): the question sits next to the summary; no window.confirm.
            <details className="mt-6">
              <summary className="select-none cursor-pointer rounded px-2 py-1 text-red-600 hover:bg-red-50">
                Холбоос цуцлах
              </summary>
              <form onSubmit={onRevoke} className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-sm text-slate-700">
                  Холбоосыг цуцалсны дараа ажилтан энэ холбоосоор бөглөх боломжгүй болно. Цуцлах уу?
                </p>
                <button
                  type="submit"
                  disabled={pending}
                  className="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Тийм, цуцлах
                </button>
              </form>
            </details>
          ) : null}
        </section>
      ) : null}

      {data.hire_path ? (
        <section className="mt-6 border-t border-slate-200 pt-4">
          <p className="text-sm text-slate-700">Ажилтан маягтаа бөглөж илгээсэн. Хянаад ажилтны бүртгэлд нэмнэ.</p>
          <AppLink
            to={data.hire_path}
            className="mt-3 inline-block rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
          >
            Нээх
          </AppLink>
        </section>
      ) : null}

      {decision ? (
        <section className="mt-6 border-t border-slate-200 pt-4">
          <h2 className="text-base font-semibold">Шийдвэр</h2>
          <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-6">
            {decision.reviewed_label ? (
              <>
                <dt className="text-slate-500">Шийдвэрлэсэн</dt>
                <dd>
                  {decision.reviewed_label}
                  {decision.reviewed_by ? `, ${decision.reviewed_by}` : ""}
                </dd>
              </>
            ) : null}
            {data.state_key === "rejected" ? (
              <>
                <dt className="text-slate-500">Татгалзсан шалтгаан</dt>
                <dd className="whitespace-pre-line">{decision.reject_reason}</dd>
              </>
            ) : null}
            {decision.hr_note ? (
              <>
                <dt className="text-slate-500">HR тэмдэглэл</dt>
                <dd className="whitespace-pre-line">{decision.hr_note}</dd>
              </>
            ) : null}
          </dl>
          {data.state_key === "confirmed" && decision.employee_path ? (
            <p className="mt-3 text-sm">
              <AppLink to={decision.employee_path} className="text-violet-700 hover:underline">
                Ажилтны бүртгэл рүү
              </AppLink>
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
