import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useSlotList, type SlotListOut, type SlotRowOut } from "../../api/slots";
import { TLink } from "../../lib/viewTransition";
import { Forbidden } from "../../routes/ErrorPage";
import { SlotFormModal } from "./SlotFormModal";
import { SlotsTable } from "./SlotsTable";

// Port of app/employees/templates/employees/slots_list.html: the position budget («Орон тооны төлөвлөгөө») at
// /employees/slots/. Classes, the title, the header links and the description are copied from the template. The year
// comes from ?year= (the server picks the current year when it is missing); every other value comes from the API.
const TITLE = "Орон тооны төлөвлөгөө";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";

export interface SlotsPageProps {
  // Notified when «Нэмэх» or a row opens the pop-up. The page mounts the pop-up itself (SlotFormModal).
  onAdd?: (year: number) => void;
  onOpen?: (id: number) => void;
}

export function SlotsPage({ onAdd = () => {}, onOpen = () => {} }: SlotsPageProps) {
  const [search] = useSearchParams();
  const raw = search.get("year");
  const year = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  const query = useSlotList(year);
  // The open pop-up: { row: undefined } adds a row, { row } edits that row. null: none is open.
  const [editing, setEditing] = useState<{ row: SlotRowOut | undefined } | null>(null);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The batches of the key on screen. While a new year loads there are none: the batches of the last settled year
  // (`good`) stay on screen, stale and inert, until the new first batch arrives (as OrdersPage).
  const pages = query.data?.pages;
  const settled = pages !== undefined;
  const [good, setGood] = useState<SlotListOut[] | null>(null);
  if (pages && pages !== good) setGood(pages);
  const shown = pages ?? good;
  const view = shown?.[0] ?? null;
  // A new year that failed shows no rows, only the alert. A failed next batch keeps its rows (`settled` is true then).
  const failedNew = query.isError && !settled;
  const tableShown = view !== null && !failedNew;
  const rows = tableShown && shown ? shown.flatMap((page) => page.rows) : [];

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (failedNew && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (view === null) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        Мэдээлэл ачаалж чадсангүй.
      </p>
    ) : null;
  }

  // The header follows the URL year while a new year loads. Once the list has settled, the server's year is the truth:
  // it is the URL year when that is valid, else the current year (a bad ?year= such as 1999 shows that year's rows).
  const settling = !settled;
  const y = settling ? (year ?? view.year) : view.year;
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold">{`${TITLE} — ${y}`}</h1>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          <TLink to={`?year=${y - 1}`} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            {`← ${y - 1}`}
          </TLink>
          <TLink to={`?year=${y + 1}`} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            {`${y + 1} →`}
          </TLink>
          <button
            type="button"
            disabled={settling}
            onClick={() => {
              setEditing({ row: undefined });
              onAdd(y);
            }}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Нэмэх
          </button>
        </div>
      </div>
      <p className="mt-2 text-sm text-slate-500">
        Албан тушаал, салбар, төрөл (үндсэн эсвэл түр), оны хувьд хэдэн хүн авч болохыг энд бүртгэнэ. «Ашиглаж буй» нь
        тухайн орон тоонд ажиллаж буй, мөн тухайн оны дотор ажилд орох хүмүүсийн тоо.
      </p>
      <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">
        <span className="font-medium">Орон тоогоор хязгаарлах:</span>{" "}
        {view.enforce ? (
          <>
            <span className="rounded bg-green-50 px-2 py-0.5 text-green-700">Асаалттай</span> — орон тоо дүүрсэн үед ажилд
            авах, дахин авахыг хориглоно.
          </>
        ) : (
          <>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">Унтраалттай</span> — орон тоо шалгахгүй,
            зөвхөн төлөвлөгөө хөтөлнө.
          </>
        )}
        <a href={view.settings_url} className="ml-1 text-violet-700 hover:underline">
          Байгууллагын тохиргоо
        </a>
      </div>
      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      {tableShown ? (
        <SlotsTable
          rows={rows}
          totals={view.totals}
          emptyText={view.empty_text}
          hasMore={settled && query.hasNextPage}
          loadingMore={settled && query.isFetchingNextPage}
          onMore={() => {
            if (settled) void query.fetchNextPage();
          }}
          onOpen={(id) => {
            // The row is found in the rows on screen; its data is what the pop-up edits.
            const row = rows.find((item) => item.id === id);
            if (row === undefined) return;
            setEditing({ row });
            onOpen(id);
          }}
          settling={settling}
        />
      ) : null}
      {editing ? <SlotFormModal row={editing.row} year={y} onClose={() => setEditing(null)} /> : null}
    </>
  );
}
