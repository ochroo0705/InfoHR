import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { useListPage } from "../../api/lists";
import { AppLink } from "../../lib/AppLink";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { EntryFormModal } from "./EntryFormModal";
import { ListTable } from "./ListTable";

// Port of app/lists/templates/lists/list.html: one list at /lists/<slug>/. Classes, the back link, the «Нэмэх» button and
// the Mongolian texts are copied from the template. The slug comes from the route; the label, the columns and the rows
// come from the API. The page is full width (UI_RULES §4), as LogFrame.
const MAIN_WIDTH = "max-w-none px-4 sm:px-6";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

// The open pop-up: add (no pk) or edit entry `pk`. null: none is open.
// It remembers the list it was opened on, so Back or a palette jump to another list never shows it against the new slug.
type Popup = { slug: string; pk: number | undefined } | null;

export function ListPage() {
  useMainWidth(MAIN_WIDTH);
  const { slug = "" } = useParams();
  const query = useListPage(slug);
  const [popup, setPopup] = useState<Popup>(null);
  const label = query.data?.label;

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    if (label === undefined) return;
    const previous = document.title;
    document.title = label + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, [label]);

  // A user without the right is refused on the first request, and an unknown slug is not found (both as the other pages).
  if (query.isError && query.data === undefined) {
    const status = (query.error as { status?: number } | null)?.status;
    if (status === 403) return <Forbidden />;
    if (status === 404) return <NotFound />;
    return (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED_TEXT}
      </p>
    );
  }
  const data = query.data;
  if (data === undefined) return null;

  return (
    <>
      <div className="flex items-center gap-3">
        <AppLink to="/lists/" className="text-sm text-violet-700 hover:underline">
          ← Жагсаалтууд
        </AppLink>
        <h1 className="mr-auto text-xl font-semibold">{data.label}</h1>
        <button
          type="button"
          onClick={() => setPopup({ slug, pk: undefined })}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700"
        >
          Нэмэх
        </button>
      </div>

      <ListTable columns={data.columns} rows={data.rows} onOpen={(pk) => setPopup({ slug, pk })} />

      {popup && popup.slug === slug ? (
        <EntryFormModal
          key={`${slug}:${popup.pk ?? "add"}`}
          slug={slug}
          pk={popup.pk}
          onClose={() => setPopup(null)}
        />
      ) : null}
    </>
  );
}
