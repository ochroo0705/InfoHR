import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useListsIndex, type ListsIndexOut } from "../../api/lists";
import { AppLink } from "../../lib/AppLink";
import { Forbidden } from "../../routes/ErrorPage";
import { useDebouncedField } from "../logs/useDebouncedField";

// Port of app/lists/templates/lists/index.html: the «Жагсаалтууд» index at /lists/. Classes, Mongolian text and the
// element order are copied from the template. The search lives in the address (`?q=`), replaced, not pushed. The matching
// (which lists match, the hit counts) is decided by the API; this page only draws its answer.
const PAGE_TITLE = "Жагсаалтууд";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const SEARCH_DELAY_MS = 250;
const CARD_CLASS = "block rounded-xl border border-slate-200 bg-surface p-4 hover:border-violet-300 hover:bg-violet-50";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function ListsIndexPage() {
  const [search, setSearch] = useSearchParams();
  const q = search.get("q") ?? "";
  const query = useListsIndex(q);

  // The page's title, as LogFrame sets it; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = PAGE_TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // The answer of the last settled search stays on screen while a new search loads, so the cards do not flash away.
  // A failed new search drops it: only the alert shows.
  const [good, setGood] = useState<ListsIndexOut | null>(null);
  if (query.data && query.data !== good) setGood(query.data);
  const view = query.data ?? (query.isError ? null : good);

  // The search box shows what was typed and sends it SEARCH_DELAY_MS after the last keystroke, or at once on Enter.
  const [text, setText, flush] = useDebouncedField(
    q,
    (next) =>
      setSearch(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next === "") params.delete("q");
          else params.set("q", next);
          return params;
        },
        { replace: true },
      ),
    SEARCH_DELAY_MS,
  );

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (query.isError && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    flush();
  }

  const items = view?.items ?? [];
  const showMeanings = view?.show_meanings ?? false;

  return (
    <>
      <h1 className="text-xl font-semibold">Жагсаалтууд</h1>
      <p className="mt-2 text-sm text-slate-500">
        Ажилтны бүртгэлд ашиглагдах нийтлэг жагсаалтууд. Бичлэг устгахаас өмнө ашиглагдаж байгаа эсэхийг шалгана.
      </p>

      {/* Search: a list matches by its name or by the name of one of its entries (UI_RULES §2b-3). */}
      <form method="get" action="/lists/" className="mt-4" role="search" onSubmit={onSubmit}>
        <input
          type="search"
          name="q"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Жагсаалт эсвэл бичлэгийн нэрээр хайх"
          aria-label="Хайх"
          autoComplete="off"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm md:max-w-md"
        />
      </form>

      {query.isError ? (
        <p role="alert" className="mt-4 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}

      {view !== null && (
        <div id="lists-body">
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {items.map((item) => (
              <AppLink key={item.slug} to={`/lists/${item.slug}/`} className={CARD_CLASS}>
                <div className="font-medium">{item.label}</div>
                <div className="mt-1 text-sm text-slate-500">
                  {item.count} бичлэг
                  {item.hits ? (
                    <>
                      {" · "}
                      <span className="text-violet-700">{item.hits} таарсан</span>
                    </>
                  ) : null}
                </div>
              </AppLink>
            ))}
            {items.length === 0 && !showMeanings ? <p className="text-sm text-slate-500 md:col-span-3">Олдсонгүй</p> : null}
          </div>

          {showMeanings && (
            <>
              <h2 className="mt-8 text-lg font-semibold">Утгын холбоо</h2>
              <p className="mt-1 text-sm text-slate-500">Программ зарим утгыг жагсаалтын тодорхой бичлэгээр тодорхойлдог.</p>
              <AppLink to="/lists/meaning/" className={`mt-3 ${CARD_CLASS}`}>
                <div className="font-medium">Утгын холбоо</div>
                <div className="mt-1 text-sm text-slate-500">{view.meanings_count} холбоо</div>
              </AppLink>
            </>
          )}
        </div>
      )}
    </>
  );
}
