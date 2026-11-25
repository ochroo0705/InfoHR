import type { ChangeEvent } from "react";
import type { components } from "../../api/schema";
import { AppLink, legacyOrigin } from "../../lib/AppLink";
import { TLink, useTransitionNavigate } from "../../lib/viewTransition";
import { ToolIcon } from "./ToolIcon";

// The tool ribbon of app/reports/templates/reports/report.html: captioned groups of tools. Classes and Mongolian texts
// are copied from the template. The API decides which tools exist (head.tools, head.saved, print_url, excel_url,
// staff_actions); this component only draws them. The pop-ups (columns, rules, format, save, edit) are not ported in 5a:
// each link opens the full Django report page with the same cleaned address, where the same button opens the pop-up.
// Print and Excel are plain links to the Django exports. The reset link and the saved-view select stay in the report's
// own address (in-app).

type ReportHeadOut = components["schemas"]["ReportHeadOut"];
type ReportSavedOut = components["schemas"]["ReportSavedOut"];

export interface ToolRibbonProps {
  reportKey: string;
  head: ReportHeadOut;
  columnsQuery: string; // bar.columns_query: the cleaned address plus the picker's adds
  clearUrl: string; // bar.clear_url: the «Бүгдийг арилгах» address
  search: string; // the settled answer's address search ("" or "?…"): the report page the «Засах» link opens
}

// The title of every link that opens a pop-up on the Django page.
const LEGACY_TITLE = "Хуучин хуудсанд нээгдэнэ, тэндээс товчийг дахин дарна уу";
const GROUP_CLASS =
  "inline-flex max-w-full overflow-x-auto divide-x divide-slate-300 rounded-lg border border-slate-300 bg-surface text-sm [&>*]:inline-flex [&>*]:items-center [&>*]:gap-1.5 [&>*]:whitespace-nowrap [&>*]:px-3 [&>*]:py-2 [&>*:hover]:bg-slate-50";
const SAVE_GROUP_CLASS =
  "inline-flex divide-x divide-slate-300 rounded-lg border border-slate-300 bg-surface text-sm [&>*]:inline-flex [&>*]:items-center [&>*]:gap-1.5 [&>*]:whitespace-nowrap [&>*]:px-3 [&>*]:py-2 [&>*:hover]:bg-slate-50";
const ICON_BUTTON =
  "flex h-9 w-9 items-center justify-center rounded-lg border border-slate-300 bg-surface text-slate-700 hover:bg-slate-50";
const ICON_PRIMARY = "flex h-9 w-9 items-center justify-center rounded-lg bg-violet-600 text-white hover:bg-violet-700";

// The Django origin address of a path (exports and the report pages that open a pop-up).
function legacy(path: string): string {
  return legacyOrigin() + path;
}

// The full Django report page with the given cleaned address. 5b replaces these links with React pop-ups.
export function legacyReportPage(reportKey: string, query: string): string {
  return legacy(`/reports/${reportKey}/?${query}`);
}

// The full Django report page at the address the page shows (the «Засах» link of the current view).
export function legacyReportAddress(reportKey: string, search: string): string {
  return legacy(`/reports/${reportKey}/${search}`);
}

// True when the address is another address of this same report (the router serves it).
function isSameReport(url: string, reportKey: string): boolean {
  return url.startsWith(`/reports/${reportKey}/`);
}

// The saved-view select: the «—» entry is the plain address, then the saved views and the starter templates. Choosing
// one opens its address: in-app when it is this report, otherwise on the Django origin.
function SavedViews({
  reportKey,
  saved,
  columnsQuery,
  search,
}: {
  reportKey: string;
  saved: ReportSavedOut;
  columnsQuery: string;
  search: string;
}) {
  const go = useTransitionNavigate();
  const chosen = [...saved.options, ...saved.templates].find((option) => option.selected)?.url ?? saved.plain_url;

  function onChange(event: ChangeEvent<HTMLSelectElement>) {
    const url = event.target.value;
    if (isSameReport(url, reportKey)) go(url);
    else window.location.href = legacy(url);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <select
          aria-label="Хадгалсан харагдац"
          data-search="off"
          value={chosen}
          onChange={onChange}
          className="w-48 max-w-full shrink-0 truncate rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm"
        >
          <option value={saved.plain_url}>—</option>
          {saved.options.length > 0 ? (
            <optgroup label="Хадгалсан">
              {saved.options.map((option) => (
                <option key={option.url} value={option.url}>
                  {option.name}
                </option>
              ))}
            </optgroup>
          ) : null}
          {saved.templates.length > 0 ? (
            <optgroup label="Загвар">
              {saved.templates.map((option) => (
                <option key={option.url} value={option.url}>
                  {option.name}
                </option>
              ))}
            </optgroup>
          ) : null}
        </select>
        <div className={SAVE_GROUP_CLASS}>
          <a href={legacyReportPage(reportKey, columnsQuery)} title={LEGACY_TITLE}>
            <ToolIcon kind="save" />
            Хадгалах
          </a>
          {saved.can_edit_view && saved.current_view !== null ? (
            <a href={legacyReportAddress(reportKey, search)} title={LEGACY_TITLE}>
              Засах
            </a>
          ) : null}
        </div>
      </div>
      <span className="text-xs text-slate-500">Харагдац</span>
    </div>
  );
}

export function ToolRibbon({ reportKey, head, columnsQuery, clearUrl, search }: ToolRibbonProps) {
  const { columns, rules, format } = head.tools;
  const showExport = head.print_url !== "" || head.excel_url !== "";

  return (
    <div data-sticky-anchor="" className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3">
      {head.saved !== null ? (
        <SavedViews reportKey={reportKey} saved={head.saved} columnsQuery={columnsQuery} search={search} />
      ) : null}

      {columns || rules || format ? (
        <div className="flex flex-col gap-1">
          <div className={GROUP_CLASS}>
            {columns ? (
              <a href={legacyReportPage(reportKey, columnsQuery)} data-tool="columns" title={LEGACY_TITLE}>
                <ToolIcon kind="columns" />
                Багана
              </a>
            ) : null}
            {rules ? (
              <a href={legacyReportPage(reportKey, columnsQuery)} data-tool="rules" title={LEGACY_TITLE}>
                <ToolIcon kind="filter" />
                Шүүлтүүр
              </a>
            ) : null}
            {format ? (
              <a href={legacyReportPage(reportKey, columnsQuery)} data-tool="format" title={LEGACY_TITLE}>
                <ToolIcon kind="format" />
                Хэлбэр
              </a>
            ) : null}
          </div>
          <span className="text-xs text-slate-500">Тохируулах</span>
        </div>
      ) : null}

      {showExport ? (
        <div className="flex flex-col gap-1">
          <div className={GROUP_CLASS}>
            {head.print_url !== "" ? (
              <a href={legacy(head.print_url)} target="_blank" rel="noopener" title={LEGACY_TITLE}>
                <ToolIcon kind="print" />
                Хэвлэх
              </a>
            ) : null}
            {head.excel_url !== "" ? (
              <a href={legacy(head.excel_url)} title={LEGACY_TITLE}>
                <ToolIcon kind="excel" />
                Excel
              </a>
            ) : null}
          </div>
          <span className="text-xs text-slate-500">Гаргах, сонгох</span>
        </div>
      ) : null}

      {/* Clean slate: the report's plain address, served in-app. Icon only, like the staff buttons. */}
      <div className="flex flex-col gap-1">
        <TLink
          to={clearUrl}
          data-reset-all
          title="Бүгдийг арилгах: шүүлтүүр, загвар, багана, эрэмбэ бүгдийг цэвэрлэнэ"
          aria-label="Бүгдийг арилгах"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-300 bg-surface text-slate-700 hover:bg-slate-50"
        >
          <ToolIcon kind="reset" className="h-[18px] w-[18px]" />
        </TLink>
        <span className="text-center text-xs text-slate-500">Эхнээс</span>
      </div>

      {head.staff_actions ? (
        <div className="ml-auto flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <AppLink to="/employees/import/" title="Ажилтан импортлох" aria-label="Ажилтан импортлох" className={ICON_BUTTON}>
              <ToolIcon kind="import" />
            </AppLink>
            <AppLink to="/employees/new/" title="Ажилтан нэмэх" aria-label="Ажилтан нэмэх" className={ICON_PRIMARY}>
              <ToolIcon kind="person_add" />
            </AppLink>
          </div>
          <span className="text-right text-xs text-slate-500">Ажилтан</span>
        </div>
      ) : null}
    </div>
  );
}
