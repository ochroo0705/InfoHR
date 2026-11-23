import { useState } from "react";
import { useSearchParams } from "react-router";
import { excelHref, useSystemLog, type LogSystemOut, type LogSystemRowOut, type SystemLogParams } from "../../api/logs";
import { Forbidden } from "../../routes/ErrorPage";
import { LogFrame } from "./LogFrame";
import { SystemLogFilters } from "./SystemLogFilters";
import { SystemLogTable } from "./SystemLogTable";
import { searchFromSystemParams, systemParamsFromSearch } from "./logParams";

// Port of app/logs/templates/logs/system.html: the system log at /logs/system/. The frame (tabs, Excel link, title) is
// LogFrame; every flag, label and row comes from the API. The same rules as EmployeeLogPage, without the pop-ups: system
// rows lead nowhere.
const STALE_CLASS = "overflow-x-auto opacity-60 pointer-events-none";
const LIVE_CLASS = "overflow-x-auto";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function SystemLogPage() {
  const [search, setSearch] = useSearchParams();
  const params = systemParamsFromSearch(search);
  const query = useSystemLog(params);

  // The batches of the key on screen; the same stale handling as EmployeeLogPage and OrdersPage.
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<LogSystemOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows: LogSystemRowOut[] = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (failedNew && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  function go(next: SystemLogParams) {
    setSearch(searchFromSystemParams(next));
  }

  return (
    // A failed new address offers no Excel link: the link would download the previous address's file.
    <LogFrame current="system" tabs={view.tabs} excel={view.tabs.export && !failedNew ? excelHref("system", view.address) : null}>
      {query.isError ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <SystemLogFilters query={view.query} options={view.options} params={params} settled={settled} onChange={go} />
      {tableShown ? (
        <div id="rows" className={settled ? LIVE_CLASS : STALE_CLASS} aria-busy={settled ? undefined : "true"} inert={settled ? undefined : true}>
          <SystemLogTable
            rows={rows}
            hasMore={settled && query.hasNextPage}
            loadingMore={settled && query.isFetchingNextPage}
            onMore={() => {
              if (settled) void query.fetchNextPage();
            }}
            settling={!settled}
            autoLoad={!query.isError}
          />
        </div>
      ) : null}
    </LogFrame>
  );
}
