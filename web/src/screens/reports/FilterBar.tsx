import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import type { components } from "../../api/schema";
import { TLink } from "../../lib/viewTransition";
import { ColumnChips } from "./ColumnChips";
import { set } from "./filterAddress";
import {
  filterControlApplied,
  filterSpan,
  groupControlApplied,
  renderFilterControl,
  renderGroupControl,
  type FilterControlContext,
} from "./FilterControls";

// The filter bar of a report page (app/reports/templates/reports/_filters.html): the panel, the `form#report-filters`
// grid with the search box first, then the drawn filters in the order the API sent, the «Шүүлтүүр нэмэх» menu and
// «Цэвэрлэх». Classes, labels and placeholders are copied from the template. The bar decides nothing: the names drawn,
// their ✕ addresses, the menu entries and the cleaned address all come from `bar`. A change writes the new address by
// editing `query` (filterAddress.set) and hands it to onChange; the caller navigates.

type ReportBarOut = components["schemas"]["ReportBarOut"];
type ReportPickerOut = components["schemas"]["ReportPickerOut"];

export interface FilterBarProps {
  bar: ReportBarOut;
  query: string; // the settled answer's cleaned address (table.query): what the bar displays
  // The latest REQUESTED address query (the address without its leading "?"). Every edit is built on it, so edits made
  // while a new address loads compose instead of dropping each other. Equal to `query` when nothing is loading.
  editQuery: string;
  onChange: (nextQuery: string) => void;
}

// report_filters.js and the search box of _filters.html: a text box sends its text 300 ms after the last keystroke.
const SEARCH_DELAY_MS = 300;
const PANEL_CLASS = "mt-4 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm";
const FORM_CLASS = "grid min-w-0 flex-1 grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-2";
const SEARCH_CLASS = "w-full rounded-lg border border-slate-300 bg-surface py-2 pl-8 pr-3 text-sm";
const SEARCH_APPLIED_CLASS =
  "w-full rounded-lg border border-violet-500 bg-violet-50 py-2 pl-8 pr-3 text-sm font-medium text-violet-900";
const REMOVE_CLASS =
  "absolute -right-1.5 -top-1.5 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 bg-surface text-xs leading-none text-violet-700 hover:bg-violet-100";
const CLEAR_CLASS = "shrink-0 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-surface hover:text-violet-700";
const PICKER_SUMMARY_CLASS =
  "flex cursor-pointer list-none items-center rounded-lg border border-slate-300 bg-surface py-2 pl-3 pr-8 text-sm hover:bg-slate-50";
const PICKER_PANEL_CLASS = "absolute left-0 z-20 mt-1 w-64 rounded-lg border border-slate-200 bg-surface shadow-lg";
const PICKER_SEARCH_CLASS = "sel-search w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:outline-none";
const PICKER_HEADING_CLASS = "px-3 pb-1 pt-2 text-xs font-medium text-slate-500";
const PICKER_ITEM_CLASS =
  "block cursor-pointer px-3 py-1.5 text-sm hover:bg-slate-50 focus:bg-violet-50 focus:outline-none";

// The filter bar. The search box's text is the address's q; `drawnQ` is the q the page was drawn with.
export function FilterBar({ bar, query, editQuery, onChange }: FilterBarProps) {
  const drawnQ = new URLSearchParams(query).get("q") ?? "";

  // The typed text, the debounce and the last text sent. Timers and listeners may run after a render, so the refs are
  // refreshed after every render.
  const [qText, setQText] = useState(drawnQ);
  const textRef = useRef(drawnQ);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sentRef = useRef(drawnQ);
  const drawnRef = useRef(drawnQ);
  const onChangeRef = useRef(onChange);
  // The base of every edit, read when the edit happens (a timer fired later sees the newest address). It moves with each
  // edit at once, and follows the prop whenever the requested address changes.
  const editRef = useRef(editQuery);
  useLayoutEffect(() => {
    drawnRef.current = drawnQ;
    onChangeRef.current = onChange;
  });
  useEffect(() => {
    editRef.current = editQuery;
  }, [editQuery]);

  // One edit of the address: the parameter changes, every other part of the latest requested address stays.
  const edit = (name: string, value: string) => {
    const next = set(editRef.current, name, value);
    editRef.current = next;
    onChangeRef.current(next);
  };

  const clearTimer = () => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  // Sends the text as the q of the address. Skipped when that text is already the last one sent (waiting or drawn), or
  // when it is the drawn text and nothing different is in flight. A clear after a send still in flight is sent.
  const commitQ = (text: string) => {
    clearTimer();
    if (text === sentRef.current) return;
    if (text === drawnRef.current && sentRef.current === drawnRef.current) return;
    sentRef.current = text;
    edit("q", text);
  };

  // Enter or the search event: sends the waiting text now. Nothing happens when no send is waiting.
  const flushQ = () => {
    if (timer.current === null) return;
    commitQ(textRef.current);
  };

  // The address moved from outside (Back, «Цэвэрлэх», a link): the box shows it and a waiting send is dropped. An echo of
  // our own send leaves the box alone, so typing that came meanwhile is kept.
  useEffect(() => {
    if (drawnQ === sentRef.current) return;
    clearTimer();
    sentRef.current = drawnQ;
    textRef.current = drawnQ;
    setQText(drawnQ);
  }, [drawnQ]);

  useEffect(() => () => clearTimer(), []);

  // The native search event (Enter or the clear cross of a search box) flushes too. Bound once; flushQ reads refs only.
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const box = searchRef.current;
    if (!box) return;
    const onSearch = () => flushQ();
    box.addEventListener("search", onSearch);
    return () => box.removeEventListener("search", onSearch);
    // flushQ is rebuilt each render but only reads refs, so binding once is correct.
  }, []);

  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    flushQ();
  };

  const onSearchType = (text: string) => {
    setQText(text);
    textRef.current = text;
    clearTimer();
    timer.current = setTimeout(() => commitQ(textRef.current), SEARCH_DELAY_MS);
  };

  // The context of the select controls: a change edits only its own parameter.
  const ctx: FilterControlContext = {
    bar,
    query,
    onChange: edit,
  };

  const searchApplied = qText.trim() !== "";
  const anyApplied =
    searchApplied ||
    bar.column_chips.length > 0 ||
    bar.items.some((item) => filterControlApplied(item.name, ctx)) ||
    groupControlApplied(ctx);

  return (
    <div className={PANEL_CLASS}>
      <form
        id="report-filters"
        className={FORM_CLASS}
        onSubmit={(e) => {
          // The page is never submitted: Enter in a box is handled by onSearchKey.
          e.preventDefault();
        }}
      >
        <div className="relative">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 shrink-0 text-slate-500"
          >
            <circle cx="11" cy="11" r="6.5" />
            <path d="M20 20l-4.2-4.2" />
          </svg>
          <input
            ref={searchRef}
            type="search"
            name="q"
            value={qText}
            maxLength={200}
            placeholder="Хайх…"
            aria-label="Тайлангаас хайх"
            autoComplete="off"
            data-applied={searchApplied ? "" : undefined}
            className={searchApplied ? SEARCH_APPLIED_CLASS : SEARCH_CLASS}
            onChange={(e) => onSearchType(e.target.value)}
            onKeyDown={onSearchKey}
          />
        </div>
        {bar.items.map((item) => {
          const control = renderFilterControl(item.name, ctx);
          const span = filterSpan(item.name) || undefined;
          if (item.remove === "") return <div key={item.name} className={span}>{control}</div>;
          return (
            <div key={item.name} data-filter-wrap className={span ? `relative ${span}` : "relative"}>
              {/* a folded filter picked from the menu, or holding a value: the hidden add keeps it drawn */}
              <input type="hidden" name="add" value={item.name} />
              <TLink to={item.remove} aria-label="Шүүлтүүрийг арилгах" className={REMOVE_CLASS}>
                ×
              </TLink>
              {control}
            </div>
          );
        })}
        {/* the column-filter chips follow the drawn filters, then the «Бүлэглэх» select (_filters.html) */}
        <ColumnChips chips={bar.column_chips} query={query} onEdit={edit} />
        {renderGroupControl(ctx)}
      </form>
      {bar.picker.length > 0 ? <FilterPicker entries={bar.picker} /> : null}
      <TLink to={bar.clear_url} hidden={!anyApplied} data-filters-clear className={CLEAR_CLASS}>
        Цэвэрлэх
      </TLink>
    </div>
  );
}

type PickerGroup = { heading: string; items: ReportPickerOut[] };

// Every typed word is part of the label, lower case (the template's script).
function matches(label: string, words: string[]): boolean {
  const text = label.toLowerCase();
  return words.every((word) => text.includes(word));
}

// The entries in their headed groups, filtered by the search box. A heading with no entry left is dropped with them.
function groupsOf(entries: ReportPickerOut[], words: string[]): PickerGroup[] {
  const groups: PickerGroup[] = [];
  for (const entry of entries) {
    if (groups.length === 0 || entry.heading !== "") groups.push({ heading: entry.heading, items: [] });
    if (matches(entry.label, words)) groups[groups.length - 1].items.push(entry);
  }
  return groups.filter((group) => group.items.length > 0);
}

// The «Шүүлтүүр нэмэх» menu (_column_filters.html, part picker). Each entry is an address; choosing it moves to that
// address through TLink (the view transition and the unsaved-changes guard) and closes the menu. The menu closes on a
// press outside it and on Escape (only while it is open), and its search box is empty each time it opens.
function FilterPicker({ entries }: { entries: ReportPickerOut[] }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  const words = search.trim().toLowerCase().split(/\s+/).filter((word) => word !== "");
  const groups = groupsOf(entries, words);
  const visible = groups.reduce((count, group) => count + group.items.length, 0);

  const openMenu = () => {
    setSearch("");
    setOpen(true);
  };
  const closeMenu = (focusSummary: boolean) => {
    setOpen(false);
    if (focusSummary) summaryRef.current?.focus();
  };

  // While open: a press outside the menu closes it, and Escape closes it (and is consumed only then).
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (detailsRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      closeMenu(true);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <details ref={detailsRef} data-column-picker open={open} className="relative shrink-0">
      <summary
        ref={summaryRef}
        className={PICKER_SUMMARY_CLASS}
        onClick={(e) => {
          // The menu is opened and closed by state, not by the native toggle.
          e.preventDefault();
          if (open) closeMenu(false);
          else openMenu();
        }}
      >
        Шүүлтүүр нэмэх ▾
      </summary>
      <div className={PICKER_PANEL_CLASS}>
        <div className="border-b border-slate-100 p-2">
          <input
            type="search"
            data-picker-search
            placeholder="Хайх…"
            aria-label="Шүүлтүүр хайх"
            autoComplete="off"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={PICKER_SEARCH_CLASS}
          />
        </div>
        <div data-picker-list className="max-h-80 overflow-y-auto py-1">
          {groups.map((group, index) => (
            <div key={`${index}-${group.heading}`}>
              {group.heading !== "" ? (
                <p data-picker-heading className={PICKER_HEADING_CLASS}>
                  {group.heading}
                </p>
              ) : null}
              {group.items.map((entry) => (
                <TLink
                  key={entry.href}
                  to={entry.href}
                  data-picker-item
                  className={PICKER_ITEM_CLASS}
                  onClick={() => setOpen(false)}
                >
                  {entry.label}
                </TLink>
              ))}
            </div>
          ))}
          <p data-picker-empty hidden={visible > 0} className="px-3 py-2 text-sm text-slate-500">
            Олдсонгүй
          </p>
        </div>
      </div>
    </details>
  );
}
