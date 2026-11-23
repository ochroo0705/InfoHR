import { useState } from "react";
import { useSearchParams } from "react-router";
import { excelHref, useEmployeeLog, type EmployeeLogParams, type LogEmployeeOut, type LogEmployeeRowOut } from "../../api/logs";
import { Forbidden } from "../../routes/ErrorPage";
import { EmployeePopups, useEmployeePopups } from "../employee/EmployeePopups";
import { EmployeeLogFilters } from "./EmployeeLogFilters";
import { EmployeeLogTable } from "./EmployeeLogTable";
import { LogFrame } from "./LogFrame";
import { employeeParamsFromSearch, searchFromEmployeeParams } from "./logParams";

// Port of app/logs/templates/logs/employee.html: the employee log at /logs/. The frame (tabs, Excel link, title) is
// LogFrame; every flag, label and row comes from the API. This page only lays them out and keeps the filters in the
// address. Each change of the address is a new history entry (hx-push-url), so Back returns to the previous list.
const STALE_CLASS = "overflow-x-auto opacity-60 pointer-events-none";
const LIVE_CLASS = "overflow-x-auto";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function EmployeeLogPage() {
  // The pop-ups of the order rows: the page has no default employee, each row carries its own.
  return (
    <EmployeePopups>
      <EmployeeLogBody />
    </EmployeePopups>
  );
}

function EmployeeLogBody() {
  const [search, setSearch] = useSearchParams();
  const params = employeeParamsFromSearch(search);
  const query = useEmployeeLog(params);
  const popups = useEmployeePopups();

  // The batches of the key on screen. While a new key loads there are none (no placeholder data): the batches of the
  // last settled key (`good`) stay on screen, stale and inert, until the new first batch arrives.
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<LogEmployeeOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  // A new key that failed drops the old rows: the table area shows nothing but the alert (the filters stay mounted). A
  // failed next batch of the settled key keeps its rows (`settled` is true then).
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows: LogEmployeeRowOut[] = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (failedNew && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  // A row with an order opens that order's pop-up for the row's own employee.
  function onOpenOrder(row: LogEmployeeRowOut) {
    if (row.order_id != null) popups.openOrderDetail(row.order_id, row.employee_id);
  }

  function go(next: EmployeeLogParams) {
    setSearch(searchFromEmployeeParams(next));
  }

  return (
    // A failed new address offers no Excel link: the link would download the previous address's file.
    <LogFrame current="employee" tabs={view.tabs} excel={view.tabs.export && !failedNew ? excelHref("employee", view.address) : null}>
      {query.isError ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}
      <EmployeeLogFilters
        query={view.query}
        options={view.options}
        chip={view.chip}
        params={params}
        settled={settled}
        onChange={go}
      />
      {tableShown ? (
        <div id="rows" className={settled ? LIVE_CLASS : STALE_CLASS} aria-busy={settled ? undefined : "true"} inert={settled ? undefined : true}>
          <EmployeeLogTable
            rows={rows}
            hasMore={settled && query.hasNextPage}
            loadingMore={settled && query.isFetchingNextPage}
            onMore={() => {
              if (settled) void query.fetchNextPage();
            }}
            onOpenOrder={onOpenOrder}
            settling={!settled}
            autoLoad={!query.isError}
          />
        </div>
      ) : null}
    </LogFrame>
  );
}
