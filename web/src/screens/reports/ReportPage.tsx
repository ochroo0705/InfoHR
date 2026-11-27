import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import { useReportPage, type ReportPageOut } from "../../api/reports";
import { TLink, useTransitionNavigate } from "../../lib/viewTransition";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { clearOffset } from "./filterAddress";
import { FilterBar } from "./FilterBar";
import { LayoutBar } from "./layouts/LayoutBar";
import { LayoutBody, hasLayoutBody } from "./layouts/LayoutBody";
import { ReportHeader } from "./ReportHeader";
import { ReportTable } from "./ReportTable";
import { StickyStrip } from "./StickyStrip";
import { ReportPopUp, ToolRibbon, legacyReportAddress, type OpenPopUp } from "./ToolRibbon";
import { useReportMemory } from "./useReportMemory";

// Port of app/reports/templates/reports/report.html at /reports/<key>/. The frame: the header, the tool ribbon, the filter
// bar, the rules line, the note, then the table (the table layout) or the layout bar and the layout body (the other five
// layouts), and the count. A layout the page does not know, or without its payload, is a link to the Django origin. The
// settings and saved-view pop-ups are React (5b, in ToolRibbon); the sticky strip is StickyStrip. The page answer (head,
// bar, table or layout_page) comes from the API. A bare address with a default saved view answers `redirect`, which the
// page follows once. The body under the header is inert while a new address loads (the 3d-3 register rule).

const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const LEGACY_TITLE = "Хуучин хуудсанд нээгдэнэ, тэндээс товчийг дахин дарна уу";

// The last settled page answer, kept for display while a different address loads: its own address and version, so the
// rows never mix two addresses.
interface Settled {
  key: string;
  search: string;
  dataUpdatedAt: number;
  page: ReportPageOut;
}

function httpStatus(error: unknown): number | undefined {
  return (error as { status?: number } | null)?.status;
}

export function ReportPage() {
  const { key = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const goTo = useTransitionNavigate();
  const search = location.search;
  // The one pop-up open on the page (the ribbon and the rules line open it). The settings pop-ups get the latest requested
  // address without its batch position.
  const [openPop, setOpenPop] = useState<OpenPopUp>(null);
  const popQuery = clearOffset(search.replace(/^\?/, ""));
  useMainWidth(MAIN_WIDTH);

  const query = useReportPage(key, search);
  const page = query.data;
  const redirect = page?.redirect ?? "";
  // The remembered setup is applied only once the answer has come with no redirect: the server's default view wins.
  // While a restore is pending, the bare address's own answer is not drawn (nor kept as the settled answer): the
  // unfiltered rows would flash before the remembered address replaces it.
  const restorePending = useReportMemory(key, page !== undefined && redirect === "", redirect !== "");
  const answerHeld = restorePending;

  // The settled answer: remembered after each fresh answer, shown inert while another address loads.
  const [settled, setSettled] = useState<Settled | null>(null);
  if (page && redirect === "" && !answerHeld && page !== settled?.page) {
    setSettled({ key, search, dataUpdatedAt: query.dataUpdatedAt, page });
  }

  // A bare address with a default saved view is answered with the address to go to. It is followed once per address;
  // the redirect guard is cleared when an answer carries no redirect, so going back to the bare address works again.
  const redirectedFrom = useRef<string | null>(null);
  useEffect(() => {
    if (redirect === "") {
      redirectedFrom.current = null;
      return;
    }
    if (redirectedFrom.current === search || redirect === location.pathname + search) return;
    redirectedFrom.current = search;
    navigate(redirect, { replace: true });
  }, [redirect, search, location.pathname, navigate]);

  // The answer on screen: the fresh one, or while another address loads, the settled one of this report.
  const fresh = page && redirect === "" && !answerHeld ? { page, search, dataUpdatedAt: query.dataUpdatedAt } : null;
  const stale = fresh === null && !query.isError && settled !== null && settled.key === key ? settled : null;
  const view = fresh ?? stale;
  const settling = stale !== null;
  const head = view?.page.head ?? null;
  const title = head?.title ?? "";

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    if (title === "") return;
    const previous = document.title;
    document.title = title + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [title]);

  // A redirect is drawn as nothing while it is followed.
  if (redirect !== "") return null;

  if (view === null || head === null) {
    if (!query.isError) return null;
    const status = httpStatus(query.error);
    if (status === 403) return <Forbidden />;
    if (status === 404) return <NotFound />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    );
  }

  const answer = view.page;
  const bar = answer.bar;
  const table = answer.table;
  const layoutPage = answer.layout_page;
  // The filter bar's changes are pushed to the history, as the Django page's hx-push-url does.
  const onFilterChange = (nextQuery: string) => {
    const clean = nextQuery.startsWith("?") ? nextQuery.slice(1) : nextQuery;
    goTo(clean ? `${location.pathname}?${clean}` : location.pathname);
  };
  const editRules = () => setOpenPop("rules");

  return (
    <div>
      {query.isError ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <StickyStrip tools={head.tools} />
      <ReportHeader title={head.title} layouts={head.layouts} />
      <ToolRibbon reportKey={key} head={head} clearUrl={bar?.clear_url ?? ""} onOpen={setOpenPop} />

      {answer.layout === "table" && table !== null ? (
        <>
          {/* The filter bar, rules line and note stay live while a new address loads (as OrdersPage): only the table
              and the count are inert. */}
          {bar ? (
            <FilterBar bar={bar} query={table.query} editQuery={search.replace(/^\?/, "")} onChange={onFilterChange} />
          ) : null}

          <RulesAndNote
            rulesText={table.rules_text}
            showsCount={table.shows_count}
            clearRulesUrl={table.clear_rules_url}
            note={table.note}
            onEdit={editRules}
          />

          <div
            className={settling ? "opacity-60 pointer-events-none" : undefined}
            aria-busy={settling || undefined}
            inert={settling ? true : undefined}
          >
            <ReportTable
              reportKey={key}
              query={view.search}
              table={table}
              dataUpdatedAt={view.dataUpdatedAt}
              inert={settling}
            />

            {table.shows_count ? <p className="mt-3 text-sm text-slate-500">Нийт: {table.count}</p> : null}
          </div>
        </>
      ) : layoutPage && hasLayoutBody(layoutPage) ? (
        <>
          {/* The order is report.html's: the filter bar, the layout bar (not on the cards layout, as the template), the
              rules line and note. The filter bar, layout bar, rules line and note stay live while a new address loads;
              only the layout and the count are inert. */}
          {bar ? (
            <FilterBar bar={bar} query={layoutPage.query} editQuery={search.replace(/^\?/, "")} onChange={onFilterChange} />
          ) : null}

          {layoutPage.kind !== "cards" ? (
            <LayoutBar bar={layoutPage.bar} query={layoutPage.query} onChange={onFilterChange} />
          ) : null}

          <RulesAndNote
            rulesText={layoutPage.rules_text}
            showsCount={layoutPage.shows_count}
            clearRulesUrl={layoutPage.clear_rules_url}
            note={layoutPage.note}
            onEdit={editRules}
          />

          <div
            className={settling ? "opacity-60 pointer-events-none" : undefined}
            aria-busy={settling || undefined}
            inert={settling ? true : undefined}
          >
            <LayoutBody
              reportKey={key}
              page={layoutPage}
              query={view.search}
              dataUpdatedAt={view.dataUpdatedAt}
              onChange={onFilterChange}
            />

            {layoutPage.shows_count ? <p className="mt-3 text-sm text-slate-500">Нийт: {layoutPage.count}</p> : null}
          </div>
        </>
      ) : (
        <p className="mt-3 text-sm text-slate-500">
          <a href={legacyReportAddress(key, view.search)} title={LEGACY_TITLE} className="text-violet-700 hover:underline">
            Энэ харагдацыг хуучин хуудсанд нээх
          </a>
        </p>
      )}
      <ReportPopUp
        reportKey={key}
        open={openPop}
        query={popQuery}
        savedQuery={table?.query ?? popQuery}
        editPk={head.saved?.current_view ?? null}
        onClose={() => setOpenPop(null)}
      />
    </div>
  );
}

// The rules line and the note. report.html draws them for every layout, so the table and the other layouts share this.
interface RulesAndNoteProps {
  rulesText: string;
  showsCount: boolean;
  clearRulesUrl: string;
  note: string;
  onEdit: () => void;
}

function RulesAndNote({ rulesText, showsCount, clearRulesUrl, note, onEdit }: RulesAndNoteProps) {
  return (
    <>
      {rulesText && showsCount ? (
        <p className="mt-3 text-sm text-slate-700">
          Нөхцөл: <span data-rules-text>{rulesText}</span> ·{" "}
          <button type="button" onClick={onEdit} className="text-violet-700 hover:underline">
            Засах
          </button>{" "}
          ·{" "}
          <TLink to={clearRulesUrl} className="text-violet-700 hover:underline">
            Цэвэрлэх
          </TLink>
        </p>
      ) : null}

      {note ? <p className="mt-3 text-sm text-slate-500">{note}</p> : null}
    </>
  );
}
