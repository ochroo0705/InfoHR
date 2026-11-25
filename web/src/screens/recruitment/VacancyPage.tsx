import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";
import { useVacancy, type RecruitCandidateRowOut, type RecruitVacancyOut } from "../../api/recruitment";
import { AppLink } from "../../lib/AppLink";
import { useMoreSentinel } from "../../lib/useMoreSentinel";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { cn } from "../../lib/utils";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { CandidateModal } from "./CandidateModal";
import { SlotLine } from "./SlotLine";
import { StageBar } from "./StageBar";
import { StageChip, VacancyStatusChip } from "./stageChip";
import { VacancyModal } from "./VacancyModal";

// Port of app/recruitment/templates/recruitment/vacancy_detail.html (with _stage_bar.html and _candidate_rows.html) at
// /recruitment/vacancies/<id>/. Classes, Mongolian texts and the element order are copied from the template. The stage
// choice lives in the address as ?stage= (the open stage is left out, the change replaces the address). The facts come
// from the first batch; the candidates of every loaded batch are listed together.
//
// Keyboard (UI_RULES §4, the list rule): every candidate row is a tab stop, Enter or Space on the row opens the candidate
// through the router; keys from the name link are ignored. The row has no role="button".

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const NOT_OPEN_PAGE =
  "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. «Засах» дарж төлөвийг «Нээлттэй» болгоно уу.";
const COLUMNS = 5;

// The stage filter. Open (the active stages) is the default and is left out of the address. The raw ?stage= value goes to
// the server unchanged; the server answers the stage it used (stage_key), so an unknown value reads as open there.
const DEFAULT_STAGE = "open";

function httpStatus(error: unknown): number | undefined {
  return (error as { status?: number } | null)?.status;
}

// The vacancy page for the id in the address. An id that is not a positive whole number is the not-found page.
export function VacancyPage() {
  const { id: raw } = useParams();
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) return <NotFound />;
  return <VacancyView id={id} />;
}

function VacancyView({ id }: { id: number }) {
  const [search, setSearch] = useSearchParams();
  const query = useVacancy(id, search.get("stage") ?? "");
  const [editOpen, setEditOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const goTo = useTransitionNavigate();

  // The batches of the stage on screen. While a new stage loads there are none: the batches of the last settled stage
  // stay on screen, inert, until the new first batch arrives (as the list page does).
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<RecruitVacancyOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const body = shown?.[0] ?? null;
  const title = body?.title ?? "";

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
  if (query.isError && !settled) {
    const status = httpStatus(query.error);
    if (status === 404) return <NotFound />;
    if (status === 403) return <Forbidden />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    );
  }
  if (body === null || shown === null) return null;

  // Picking a stage writes it to the address (open is left out); the address change replaces the history entry.
  const pickStage = (key: string) => {
    const next = new URLSearchParams(search);
    if (key === DEFAULT_STAGE) next.delete("stage");
    else next.set("stage", key);
    setSearch(next, { replace: true });
  };

  const rows = shown.flatMap((page) => page.candidates);
  const hasMore = settled && query.hasNextPage;

  return (
    <div>
      <p className="text-sm">
        <AppLink to="/recruitment/" className="text-violet-700 hover:underline">
          ← Ажилд авах
        </AppLink>
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{body.title}</h1>
        <VacancyStatusChip status={body.status} label={body.status_label} />
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {body.can_manage ? (
            <button
              type="button"
              onClick={() => setEditOpen(true)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
            >
              Засах
            </button>
          ) : null}
          {body.can_manage && body.is_open ? (
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
            >
              Ажил хүсэгч нэмэх
            </button>
          ) : null}
        </div>
      </div>

      <div className="card-soft mt-3 grid gap-x-6 gap-y-2 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="Албан тушаал">{body.position}</Fact>
        <Fact label="Хэлтэс">{body.department}</Fact>
        <Fact label="Салбар">{body.branch || "—"}</Fact>
        <Fact label="Авах хүний тоо">{body.headcount}</Fact>
        <Fact label="Авах эцсийн хугацаа">{body.deadline ?? "—"}</Fact>
        <Fact label="Ажил эхлэх огноо">{body.desired_start ?? "—"}</Fact>
        {body.description ? (
          <div className="sm:col-span-2 lg:col-span-4">
            <div className="text-xs text-slate-500">Тайлбар</div>
            <p className="whitespace-pre-line">{body.description}</p>
          </div>
        ) : null}
      </div>
      {body.can_manage && body.is_open && body.slot_line ? (
        <div className="mt-3">
          <SlotLine line={body.slot_line} />
        </div>
      ) : null}
      {body.can_manage && !body.is_open ? (
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{NOT_OPEN_PAGE}</p>
      ) : null}

      <section id="cand-list" className="mt-5">
        <h2 className="sec-title mb-2">Ажил хүсэгчид</h2>
        <p className="mb-1 text-xs text-slate-500">Шатаар шүүх</p>
        <StageBar items={body.stage_bar} active={body.stage_key} onPick={pickStage} />
        <details className="mt-1 text-xs text-slate-500">
          <summary className="cursor-pointer">Шатуудын тайлбар</summary>
          <ul className="mt-1 space-y-0.5">
            <li>
              <b className="font-medium text-slate-600">Шинэ</b> — анкет орж ирсэн, хараахан үзээгүй.
            </li>
            <li>
              <b className="font-medium text-slate-600">Шалгаруулалт</b> — анкет, CV-г үнэлж байна.
            </li>
            <li>
              <b className="font-medium text-slate-600">Ярилцлага</b> — ярилцлагад урьсан эсвэл ярилцаж байна.
            </li>
            <li>
              <b className="font-medium text-slate-600">Санал</b> — ажлын санал тавьсан.
            </li>
            <li>
              <b className="font-medium text-slate-600">Ажилд авсан</b> — ажилтан болгож бүртгэсэн.
            </li>
          </ul>
        </details>
        <CandidateTable
          rows={rows}
          hasMore={hasMore}
          loadingMore={settled && query.isFetchingNextPage}
          onMore={() => {
            if (settled) void query.fetchNextPage();
          }}
          onOpen={(candidateId) => goTo(`/recruitment/candidates/${candidateId}/`)}
          settling={!settled}
        />
      </section>

      {editOpen ? <VacancyModal vacancyId={id} onClose={() => setEditOpen(false)} /> : null}
      {addOpen ? (
        <CandidateModal
          vacancy={{ id, title: body.title }}
          onClose={() => setAddOpen(false)}
          onSaved={() => setAddOpen(false)}
        />
      ) : null}
    </div>
  );
}

// One fact of the grid: a small grey caption over the value.
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      {children}
    </div>
  );
}

interface CandidateTableProps {
  rows: RecruitCandidateRowOut[];
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
  onOpen: (id: number) => void;
  // True while the rows on screen are the last settled ones of an older stage: inert, and no empty-row text is drawn.
  settling: boolean;
}

function CandidateTable({ rows, hasMore, loadingMore, onMore, onOpen, settling }: CandidateTableProps) {
  const moreRef = useRef<HTMLButtonElement>(null);
  useMoreSentinel(moreRef, onMore, hasMore && !loadingMore && !settling);

  function onRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, id: number) {
    // Keys from an inner control (the name link) are not the row's.
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onOpen(id);
  }

  return (
    <div
      className={cn("card-soft mt-2 overflow-x-auto px-3 pb-2 md:px-4", settling && "pointer-events-none opacity-60")}
      aria-busy={settling ? "true" : undefined}
      inert={settling ? true : undefined}
    >
      <table className="w-full text-sm">
        <thead className="sr-only text-left text-slate-500 md:not-sr-only md:table-header-group">
          <tr>
            <th className="py-2">Нэр</th>
            <th>Шат</th>
            <th>Утас</th>
            <th>Эх сурвалж</th>
            <th>Нэмсэн</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              tabIndex={0}
              className="block my-2 cursor-pointer rounded-lg border border-slate-200 px-3 py-2 hover:bg-violet-50 md:table-row md:my-0 md:rounded-none md:border-0 md:border-t md:border-slate-100 md:px-0 md:py-0 focus-visible:bg-violet-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-500"
              onClick={() => onOpen(row.id)}
              onKeyDown={(event) => onRowKeyDown(event, row.id)}
            >
              <td className="block py-1 md:table-cell md:py-2">
                <AppLink
                  to={`/recruitment/candidates/${row.id}/`}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium hover:text-violet-700 hover:underline"
                >
                  {row.name}
                </AppLink>
              </td>
              <td className="block py-0.5 md:table-cell">
                <StageChip stage={row.stage} label={row.stage_label} />
              </td>
              <td className="block py-0.5 text-slate-600 md:table-cell">
                {row.phone ? (
                  <>
                    <span className="text-slate-500 md:hidden">Утас: </span>
                    {row.phone}
                  </>
                ) : (
                  <span className="hidden md:inline">—</span>
                )}
              </td>
              <td className="block py-0.5 text-slate-600 md:table-cell">
                {row.source ? (
                  <>
                    <span className="text-slate-500 md:hidden">Эх сурвалж: </span>
                    {row.source}
                  </>
                ) : (
                  <span className="hidden md:inline">—</span>
                )}
              </td>
              <td className="block whitespace-nowrap py-0.5 text-slate-500 md:table-cell">
                <span className="md:hidden">Нэмсэн: </span>
                {row.created}
              </td>
            </tr>
          ))}
          {/* Empty state: the page passes no rows once the stage has settled and none came back. */}
          {rows.length === 0 && !hasMore && !settling && (
            <tr>
              <td colSpan={COLUMNS} className="py-6 text-center text-slate-500">
                Ажил хүсэгч олдсонгүй
              </td>
            </tr>
          )}
          {hasMore && (
            <tr data-more-row>
              <td colSpan={COLUMNS} className="px-4 py-3 text-center">
                <button
                  ref={moreRef}
                  type="button"
                  data-more-batch
                  onClick={() => {
                    if (!loadingMore) onMore();
                  }}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-surface px-4 py-1.5 text-sm text-slate-600 hover:border-violet-300 hover:text-violet-700"
                >
                  <svg
                    aria-hidden="true"
                    className={cn("htmx-indicator h-4 w-4 animate-spin", loadingMore && "htmx-request")}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
                  </svg>
                  Цааш харуулах
                </button>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
