import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { getCsrf } from "../../api/client";
import { useOrderRegister, type OrderRegisterOut, type OrderRegisterRowOut, type RegisterParams } from "../../api/orderRegister";
import { useMainWidth } from "../../shell/mainWidth";
import { EmployeePopups, useEmployeePopups } from "../employee/EmployeePopups";
import { PrintSelected } from "./PrintSelected";
import { RegisterFilters } from "./RegisterFilters";
import { RegisterTable } from "./RegisterTable";
import { paramsFromSearch, printHref, searchFromParams } from "./registerParams";

// Port of app/employees/templates/employees/orders.html: the order register at /employees/orders/. Classes, the title and
// the header row are copied from the template. Every flag (report link, print rights, background threshold, filter
// options, sort heads, rows) comes from the API; this page only lays them out and keeps the filters in the address.
const TITLE = "Тушаалын бүртгэл";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const MAIN_WIDTH = "max-w-none px-4 sm:px-6"; // a list page: full width (UI_RULES §4)
const NO_PICKS: ReadonlySet<string> = new Set();
const STALE_CLASS = "overflow-x-auto opacity-60 pointer-events-none";
const LIVE_CLASS = "overflow-x-auto";

export function OrdersPage() {
  useMainWidth(MAIN_WIDTH);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The pop-ups of the order rows: the page has no default employee, each row carries its own.
  return (
    <EmployeePopups>
      <OrdersBody />
    </EmployeePopups>
  );
}

function OrdersBody() {
  const [search, setSearch] = useSearchParams();
  const params = paramsFromSearch(search);
  const query = useOrderRegister(params);
  const popups = useEmployeePopups();

  // The batches of the key on screen. While a new key loads there are none (no placeholder data): the batches of the
  // last settled key (`good`) stay on screen, stale and inert, until the new first batch arrives.
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<OrderRegisterOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  // A new key that failed drops the old rows: the table area shows nothing but the alert (the filters stay mounted). A
  // failed next batch of the settled key keeps its rows (`settled` is true then).
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows: OrderRegisterRowOut[] = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // The ticks belong to one set of filters. A change of filter, sort or search drops them at once and for good, so
  // changing back to an earlier set shows no ticks. Batches added to the same set keep them.
  const scope = JSON.stringify(params);
  const [selection, setSelection] = useState<{ scope: string; keys: ReadonlySet<string> }>({
    scope,
    keys: NO_PICKS,
  });
  if (selection.scope !== scope) setSelection({ scope, keys: NO_PICKS });
  const picked = selection.scope === scope ? selection.keys : NO_PICKS;
  function updatePicked(change: (next: Set<string>) => void) {
    setSelection((prev) => {
      const next = new Set(prev.scope === scope ? prev.keys : NO_PICKS);
      change(next);
      return { scope, keys: next };
    });
  }

  // The stale rows of a new key are inert: their ids never reach «Сонгосныг хэвлэх», and the picks do not change.
  const pickedIds = settled ? rows.flatMap((row) => (picked.has(row.key) && row.order_id != null ? [row.order_id] : [])) : [];

  function onPick(key: string, checked: boolean) {
    if (!settled) return;
    updatePicked((next) => {
      if (checked) next.add(key);
      else next.delete(key);
    });
  }

  // Select-all ticks (or clears) only the loaded rows that have a checkbox.
  function onPickAll(checked: boolean) {
    if (!settled) return;
    const keys = rows.filter((row) => row.pickable).map((row) => row.key);
    updatePicked((next) => {
      for (const key of keys) {
        if (checked) next.add(key);
        else next.delete(key);
      }
    });
  }

  // A row opens its order's pop-up for the row's own employee; the table handles the employee-page rows itself.
  function onOpen(row: OrderRegisterRowOut) {
    if (row.order_id != null) popups.openOrderDetail(row.order_id, row.employee_id);
  }

  // Filter changes and sort clicks are a new history entry (hx-push-url), so Back returns to the previous list.
  function go(next: RegisterParams) {
    setSearch(searchFromParams(next));
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{TITLE}</h1>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {view?.report_link ? (
            <a href="/reports/orders/" className="text-sm text-violet-700 hover:underline">
              Тайлан гаргах
            </a>
          ) : null}
          {view?.can_manage ? <PrintSelected picked={pickedIds} backgroundFrom={view.background_from} csrfToken={getCsrf()} /> : null}
          <a
            id="print-link"
            href={printHref(params)}
            target="_blank"
            rel="noopener"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
          >
            Хэвлэх
          </a>
        </div>
      </div>
      {query.isError ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      {view ? (
        <RegisterFilters
          options={view.options}
          query={view.query}
          allLabels={view.all_labels}
          params={params}
          settled={settled}
          onChange={go}
        />
      ) : null}
      {tableShown && view ? (
        <div
          id="rows"
          className={settled ? LIVE_CLASS : STALE_CLASS}
          aria-busy={settled ? undefined : "true"}
          inert={settled ? undefined : true}
        >
          <RegisterTable
            rows={rows}
            sort={view.query.sort}
            sortHeads={view.sort_heads}
            canManage={view.can_manage}
            picked={picked}
            onPick={onPick}
            onPickAll={onPickAll}
            onOpen={onOpen}
            onSort={(next) => go({ ...params, sort: next })}
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
    </>
  );
}
