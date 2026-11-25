import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useCatalogue, type ReportCatalogueOut } from "../../api/reports";
import { AppLink } from "../../lib/AppLink";
import { cn } from "../../lib/utils";
import { Forbidden } from "../../routes/ErrorPage";

// Port of app/reports/templates/reports/catalogue.html at /reports/: the report catalogue. Classes, Mongolian texts and
// the element order are copied from the template. The cards and their search text come from the API; the search runs in
// the browser, as the template's script did (trimmed, lower-case substring of each card's `search`). `?q=` prefills the
// box and applies on load; typing writes the address with `replace`, so no history entries are added.
const PAGE_TITLE = "Тайлан";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const MAX_Q = 200;

type ReportCardOut = ReportCatalogueOut["sections"][number]["rows"][number];

// The word the box filters by: trimmed and lower-case, as the template's script read it.
function needleOf(text: string): string {
  return text.trim().toLowerCase();
}

export function CataloguePage() {
  const [search, setSearch] = useSearchParams();
  const query = useCatalogue();

  // The box starts with the address's word, trimmed and cut as the server did; it then shows what is typed.
  const [text, setText] = useState(() => (search.get("q") ?? "").trim().slice(0, MAX_Q));

  // The page's title, as LogFrame sets it; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = PAGE_TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if (query.isError && (query.error as { status?: number } | null)?.status === 403) return <Forbidden />;

  // Typing narrows the cards at once and writes the word into the address without a new history entry.
  function onSearch(next: string) {
    setText(next);
    setSearch(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === "") params.delete("q");
        else params.set("q", next);
        return params;
      },
      { replace: true },
    );
  }

  const sections = query.data?.sections ?? [];
  const needle = needleOf(text);
  const matches = (card: ReportCardOut) => card.search.toLowerCase().indexOf(needle) !== -1;
  const shownCount = sections.reduce((count, section) => count + section.rows.filter(matches).length, 0);
  const noneShown = query.data !== undefined && shownCount === 0;

  return (
    <div>
      <h1 className="text-xl font-semibold">MACS-ийн бүх тайлан</h1>
      <p className="mt-2 text-sm text-slate-500">MACS-д байсан тайлангууд, шинэ системд хэвээр</p>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        <input
          type="search"
          id="report-search"
          placeholder="Тайлан хайх"
          aria-label="Тайлан хайх"
          autoComplete="off"
          className="min-w-64 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          value={text}
          onChange={(event) => onSearch(event.target.value)}
        />
        <p className="w-full text-xs text-slate-400">Нэр, хуучин нэр, хуучин маягтын нэр, тайлбараар нь хайж олно.</p>
      </div>

      {query.isError ? (
        <p role="alert" className="mt-4 text-sm text-red-600">
          {LOAD_FAILED}
        </p>
      ) : null}

      {sections.map((section) => {
        const sectionShown = section.rows.some(matches);
        return (
          <section key={section.title} className={cn("mt-8", !sectionShown && "hidden")} data-report-section="">
            <h2 className="sec-title">{section.title}</h2>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {section.rows.map((card) => (
                // The whole card is the link: the title's link covers the card (after:inset-0).
                <div
                  key={card.key}
                  className={cn(
                    "relative rounded-xl border border-slate-200 bg-surface p-4",
                    card.link && "hover:border-violet-300 hover:bg-violet-50",
                    !matches(card) && "hidden",
                  )}
                  data-report-card=""
                  data-search={card.search}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    {card.link ? (
                      <>
                        <AppLink to={card.path} className="font-medium text-slate-900 after:absolute after:inset-0">
                          {card.title}
                        </AppLink>
                        {card.empty ? <span className="shrink-0 text-xs text-slate-400">бүртгэл алга</span> : null}
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-slate-400">{card.title}</span>
                        <span className="shrink-0 text-xs text-slate-400">удахгүй</span>
                      </>
                    )}
                  </div>
                  <div className={cn("mt-1 text-sm", card.link ? "text-slate-500" : "text-slate-400")}>
                    {card.description}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}

      {noneShown ? <p id="report-none" className="mt-8 text-center text-slate-400">Хайлтад тохирох тайлан олдсонгүй.</p> : null}
    </div>
  );
}
