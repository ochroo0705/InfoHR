import { useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "react-router";
import { nav } from "../../api/client";
import type { ApiFailure } from "../../api/mutate";
import {
  useCandidate,
  useConvertCandidate,
  useMoveCandidate,
  useReopenCandidate,
  type RecruitCandidateOut,
} from "../../api/recruitment";
import { AppLink } from "../../lib/AppLink";
import { isPorted } from "../../lib/ported";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";
import { Comments } from "./Comments";
import { Files } from "./Files";
import { RejectModal } from "./RejectModal";
import { StageChip } from "./stageChip";
import { StageRow } from "./StageRow";

// Port of app/recruitment/templates/recruitment/candidate_detail.html at /recruitment/candidates/<id>/ (max-w-4xl). Classes,
// Mongolian texts and the element order are copied from the template. The stage row is hidden for a rejected or withdrawn
// candidate; the chip beside the name shows only then. Refusals of «Ажилд авах» and «Дахин нээх» show in the red box under
// the buttons, as Django's `notice` did.

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const CLOSED = ["rejected", "withdrawn"];
// candidate_detail.html: {% block main_width %}max-w-4xl px-4{% endblock %}. The shell <main> carries the width and the
// side padding (the page wrapper adds none, or the gutter doubles to 32px at phone width).
const MAIN_WIDTH = "max-w-4xl px-4";

function httpStatus(error: unknown): number | undefined {
  return (error as { status?: number } | null)?.status;
}

// The candidate page for the id in the address. An id that is not a positive whole number is the not-found page.
export function CandidatePage() {
  const { id: raw } = useParams();
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) return <NotFound />;
  return <CandidateView id={id} />;
}

function CandidateView({ id }: { id: number }) {
  useMainWidth(MAIN_WIDTH);
  const query = useCandidate(id);
  const move = useMoveCandidate(id);
  const convert = useConvertCandidate(id);
  const reopen = useReopenCandidate(id);
  const goTo = useTransitionNavigate();
  const [rejectOpen, setRejectOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const data = query.data ?? null;
  const title = data?.name ?? "";

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on this page.
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = title + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [title]);

  // The first load failed: the not-found page, the forbidden page, or the load failure.
  if (query.isError && data === null) {
    const status = httpStatus(query.error);
    if (status === 404) return <NotFound />;
    if (status === 403) return <Forbidden />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    );
  }
  if (data === null) return null;

  const closed = CLOSED.includes(data.stage);

  // The move the stage row asks for. A refusal throws its text, which the row shows under itself.
  // A request that failed (403, 500, network) carries the API client's English text, so it is replaced here.
  const onMove = async (to: string) => {
    let result;
    try {
      result = await move.mutateAsync({ to, note: "" });
    } catch {
      throw new Error(SAVE_FAILED_TEXT);
    }
    if (!result.ok) throw new Error(result.error || SAVE_FAILED_TEXT);
  };

  // «Ажилд авах»: the hire form's address comes back; a path the React app serves goes through the router, any other
  // path is a full page load. A refusal shows its text in the red box.
  const onConvert = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setNotice("");
    // The page stays locked after a good answer: it is leaving.
    let leaving = false;
    try {
      const result = await convert.mutateAsync();
      if (result.ok) {
        leaving = true;
        if (isPorted(result.path)) goTo(result.path);
        else nav.assign(result.path);
        return;
      }
      setNotice(result.error || SAVE_FAILED_TEXT);
    } catch (error) {
      setNotice(messageOf(error));
    } finally {
      if (!leaving) {
        inFlight.current = false;
        setBusy(false);
      }
    }
  };

  // «Дахин нээх»: a refusal shows its text in the red box.
  const onReopen = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setNotice("");
    try {
      const result = await reopen.mutateAsync();
      if (!result.ok) setNotice(result.error || SAVE_FAILED_TEXT);
    } catch (error) {
      setNotice(messageOf(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="text-sm">
        <AppLink to={`/recruitment/vacancies/${data.vacancy_id}/`} className="text-violet-700 hover:underline">
          ← {data.vacancy_title}
        </AppLink>
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{data.name}</h1>
        {closed ? <StageChip stage={data.stage} label={data.stage_label} /> : null}
        <span className="ml-auto flex flex-wrap items-center justify-end gap-2 text-sm">
          {data.can_reject ? (
            <button
              type="button"
              onClick={() => setRejectOpen(true)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-red-600 hover:bg-red-50"
            >
              Татгалзах
            </button>
          ) : null}
          {data.can_convert ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onConvert()}
              className="rounded-lg bg-violet-600 px-4 py-2 text-white hover:bg-violet-700 disabled:opacity-50"
            >
              Ажилд авах
            </button>
          ) : null}
          {data.can_reopen ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReopen()}
              className="rounded-lg bg-violet-600 px-4 py-2 text-white hover:bg-violet-700 disabled:opacity-50"
            >
              Дахин нээх
            </button>
          ) : null}
        </span>
      </div>

      {notice ? (
        <p role="alert" className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {notice}
        </p>
      ) : null}

      {closed ? null : (
        <StageRow progress={data.progress} moveTo={data.move_to} moveConfirm={data.move_confirm} onMove={onMove} />
      )}

      <Facts data={data} />

      <section className="mt-5">
        <h2 className="sec-title mb-2">Файл</h2>
        <Files
          candidate={data.id}
          files={data.files}
          canManage={data.can_manage}
          extensions={data.extensions}
          maxMb={data.max_mb}
        />
      </section>

      <section className="mt-5">
        <h2 className="sec-title mb-2">Сэтгэгдэл</h2>
        <Comments candidate={data.id} comments={data.comments} />
      </section>

      <section className="mt-5">
        <h2 className="sec-title mb-2">Шатны түүх</h2>
        <History data={data} />
      </section>

      {rejectOpen ? (
        <RejectModal
          candidate={{ id: data.id, name: data.name }}
          onClose={() => setRejectOpen(false)}
          onDone={() => setRejectOpen(false)}
        />
      ) : null}
    </div>
  );
}

// The facts grid: the vacancy, the source, the phone and mail links, the notes and the rejection reason when set, and the
// employee link for a manager who may see that person.
function Facts({ data }: { data: RecruitCandidateOut }) {
  return (
    <div className="card-soft mt-3 grid gap-x-6 gap-y-2 p-4 text-sm sm:grid-cols-2">
      <Fact label="Ажлын байр">
        <AppLink to={`/recruitment/vacancies/${data.vacancy_id}/`} className="text-violet-700 hover:underline">
          {data.vacancy_title}
        </AppLink>
      </Fact>
      <Fact label="Эх сурвалж">{data.source || "—"}</Fact>
      <Fact label="Утас">
        {data.phone ? (
          <a href={`tel:${data.phone}`} className="text-violet-700 hover:underline">
            {data.phone}
          </a>
        ) : (
          "—"
        )}
      </Fact>
      <Fact label="И-мэйл">
        {data.email ? (
          <a href={`mailto:${data.email}`} className="text-violet-700 hover:underline">
            {data.email}
          </a>
        ) : (
          "—"
        )}
      </Fact>
      {data.notes ? (
        <div className="sm:col-span-2">
          <div className="text-xs text-slate-500">Тэмдэглэл</div>
          <p className="whitespace-pre-line">{data.notes}</p>
        </div>
      ) : null}
      {data.reject_reason ? (
        <div className="sm:col-span-2">
          <div className="text-xs text-slate-500">Татгалзсан шалтгаан</div>
          <p className="whitespace-pre-line">{data.reject_reason}</p>
        </div>
      ) : null}
      {data.employee_id !== null ? (
        <div className="sm:col-span-2">
          <div className="text-xs text-slate-500">Ажилтан</div>
          <AppLink to={`/employees/${data.employee_id}/`} className="text-violet-700 hover:underline">
            Ажилтны хуудас нээх
          </AppLink>
        </div>
      ) : null}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      {children}
    </div>
  );
}

// The stage history, oldest first. Below md the note and the person fold under the date and the stage, as the Django
// table did (hidden md:table-cell for the two columns).
function History({ data }: { data: RecruitCandidateOut }) {
  return (
    <div className="ptable">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="text-left">Огноо</th>
            <th className="text-left">Шат</th>
            <th className="hidden text-left md:table-cell">Тайлбар</th>
            <th className="hidden text-left md:table-cell">Хэн</th>
          </tr>
        </thead>
        <tbody>
          {data.events.map((event, index) => (
            <tr key={index}>
              <td className="whitespace-nowrap">
                {event.at}
                <div className="text-xs text-slate-500 md:hidden">{event.by}</div>
              </td>
              <td>
                {event.from_label ? `${event.from_label} → ` : ""}
                {event.to_label}
                {event.note ? <div className="text-slate-600 md:hidden">{event.note}</div> : null}
              </td>
              <td className="hidden text-slate-600 md:table-cell">{event.note || "—"}</td>
              <td className="hidden text-slate-500 md:table-cell">{event.by}</td>
            </tr>
          ))}
          {data.events.length === 0 ? (
            <tr>
              <td colSpan={4} className="py-6 text-center text-slate-500">
                Түүх бүртгэгдээгүй
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

// The text of a failed request: its form messages when it has them, else the general save text.
function messageOf(error: unknown): string {
  const failure = error as Partial<ApiFailure>;
  return failure.formErrors?.[0] || SAVE_FAILED_TEXT;
}
