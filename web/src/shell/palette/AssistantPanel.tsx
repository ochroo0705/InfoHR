// The docked assistant panel, search half only (base.html lines 61-80, palette.js). The frame keeps the classes and the
// header of the original; the body (box, results, hint) is PaletteBody, which holds the search. The body is mounted only
// while the panel is open or sliding out, so closing it stops the search (usePaletteSearch aborts on unmount).
// Not here yet: the «Асуух» row, the thread, «Шинэ яриа», the send button and the floating button (later steps).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { PaletteOut, PaletteRowOut } from "../../api/palette";
import { legacyOrigin } from "../../lib/AppLink";
import { usePresence } from "../../lib/presence";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { modalStack } from "../../widgets/modalLogic";
import { useMeta } from "../useMeta";
import { activateRow } from "./activate";
import { browserStorage, usePalettePanel } from "./PalettePanelContext";
import { escapeAction, nextIndex, shouldIgnoreKey } from "./paletteKeys";
import { usePalettePopups } from "./PalettePopups";
import { PaletteResults } from "./PaletteResults";
import { remember } from "./recents";
import { usePaletteSearch } from "./usePaletteSearch";

// The rows in the order the keyboard walks them: the groups' rows, then the fallback rows when nothing matched.
function listRows(answer: PaletteOut | null): PaletteRowOut[] {
  if (!answer) return [];
  const rows = answer.groups.flatMap((group) => group.rows);
  return answer.empty ? [...rows, ...answer.fallback] : rows;
}

export function AssistantPanel() {
  const palette = usePalettePanel();
  const presence = usePresence(palette.isOpen);

  return (
    <aside
      ref={presence.ref}
      id="assistant-panel"
      data-assistant-panel
      hidden={!presence.mounted}
      role="complementary"
      aria-label="Асуух"
      data-no-enter={palette.openedByUser ? undefined : ""}
      data-leaving={presence.leaving ? "" : undefined}
      inert={presence.leaving}
      className="fixed bottom-0 right-0 top-14 z-40 flex w-[26rem] max-w-full flex-col border-l border-slate-200 bg-surface shadow-2xl ring-1 ring-slate-900/5 max-sm:top-0 max-sm:w-full print:hidden"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 text-sm">
        <h2 className="font-semibold text-slate-800">Асуух</h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            data-assistant-close
            aria-label="Хаах"
            onClick={() => palette.close(true)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-lg leading-none text-slate-500 hover:bg-slate-100 hover:text-slate-800 max-sm:h-11 max-sm:w-11"
          >
            ×
          </button>
        </div>
      </div>
      {presence.mounted ? <PaletteBody key={palette.session} /> : null}
    </aside>
  );
}

// The search: the box, the results and the hint. It is unmounted when the panel closes, so a new open starts empty.
function PaletteBody() {
  const palette = usePalettePanel();
  const { data: meta } = useMeta();
  const userId = String(meta?.user?.id ?? "");
  const storage = useMemo(() => browserStorage("localStorage"), []);
  const goPorted = useTransitionNavigate();
  const popups = usePalettePopups();
  // The page the panel was opened on (palette.js sends it with an empty box).
  const [from] = useState(() => window.location.pathname);
  const [box, setBox] = useState("");
  // The row the user moved to or hovered, with the answer it belongs to. It counts only for that answer; without one the
  // first row is the selected one (palette.js highlightFirst), so no effect has to set it after an answer arrives.
  // `scroll` is set by a keyboard move only: that move scrolls the selected row into view, a hover does not.
  const [choice, setChoice] = useState<{ answer: PaletteOut | null; key: string; scroll: boolean } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { openedByUser, isOpen, close } = palette;

  const search = usePaletteSearch({ q: box, from, storage, userId });
  const rows = useMemo(() => listRows(search.answer), [search.answer]);
  const selectedKey =
    (choice !== null && choice.answer === search.answer ? choice.key : null) ?? rows[0]?.key ?? null;
  const select = (key: string, scroll = false) => setChoice({ answer: search.answer, key, scroll });

  // A user open puts the caret in the box; a page-load reopen does not take focus (palette.js openPanel).
  useEffect(() => {
    if (openedByUser) inputRef.current?.focus();
    // Once per mount: the body mounts with each open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The box grows with its text up to its CSS max-height (palette.js autosize).
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }, [box]);

  // palette.js select(item, true): a keyboard move scrolls the selected row into view. The effect runs on each choice (a
  // new object per move), so a move onto the row that is already selected scrolls too, and no flag outlives its move.
  useEffect(() => {
    if (!choice?.scroll) return;
    const el = document.querySelector<HTMLElement>('[data-assistant-panel] [data-palette-item][aria-selected="true"]');
    el?.scrollIntoView?.({ block: "nearest" });
  }, [choice]);

  // Escape, in the document's bubble phase. Kept in the bubble phase on purpose: a pop-up that handles Escape in its own
  // listener (preventDefault) must be seen first, and a capture listener with stopPropagation would take the key before it.
  // The panel has no pop-up of its own inside it, so nothing is lost by this. Only with focus inside the panel, no pop-up
  // open, and not during an IME composition. A typed query is cleared first; an empty box closes the panel.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (shouldIgnoreKey({ isComposing: e.isComposing, keyCode: e.keyCode }, false)) return;
      if (modalStack().length > 0) return;
      const aside = document.querySelector("[data-assistant-panel]");
      if (aside === null || !aside.contains(document.activeElement)) return;
      e.preventDefault();
      if (escapeAction(box) === "clear") {
        setBox("");
        setChoice(null);
      } else {
        close(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, box, close]);

  const moveSelection = (step: 1 | -1) => {
    const index = rows.findIndex((row) => row.key === selectedKey);
    const next = nextIndex(index, step, rows.length);
    if (next < 0) return;
    select(rows[next].key, true);
  };

  // «Show all» asks the same query with more people and keeps the focus in the box. Any other row is activated.
  const activate = (row: PaletteRowOut) => {
    if (row.kind === "more") {
      search.showAll();
      inputRef.current?.focus();
      return;
    }
    if (row.ref) remember(storage, row.ref, userId);
    activateRow(row, {
      closePanel: (restoreFocus) => close(restoreFocus),
      goPorted,
      // A full page load into Django (the list page for a legacy row), as AppLink does it.
      legacy: (path) => window.location.assign(legacyOrigin() + path),
      popups,
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldIgnoreKey({ isComposing: e.nativeEvent.isComposing, keyCode: e.keyCode }, false)) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      // A box with several lines keeps its caret keys; the arrows move through the results only from a one-line box.
      if (box.includes("\n")) return;
      e.preventDefault();
      e.stopPropagation();
      moveSelection(e.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (e.key === "Enter") {
      if (e.shiftKey) return; // Shift+Enter: a new line
      e.preventDefault();
      e.stopPropagation();
      // The box's query is not answered yet (debounce or in flight): the rows on screen are the old answer's, so they are
      // not opened. The user presses Enter again once the new answer is in (palette.js).
      // palette.js: a waiting debounce is run now; a request already in flight is left alone (no abort, no re-send).
      if (search.debouncing) {
        search.flush();
        return;
      }
      if (search.pending) return;
      // The selected row, or the first one when nothing is selected.
      const row = rows.find((r) => r.key === selectedKey) ?? rows[0];
      if (row) activate(row);
    }
  };

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col">
        <PaletteResults
          answer={search.answer}
          busy={search.busy}
          failed={search.failed}
          selectedKey={selectedKey}
          keepScroll={search.more}
          fill={box.trim() !== ""}
          onSelect={select}
          onActivate={activate}
        />
      </div>
      {/* Composer at the bottom like a chat: one rounded box that grows with the text. Enter opens, Shift+Enter adds a line. */}
      <div className="shrink-0 border-t border-slate-200 bg-surface px-3 pb-2 pt-3">
        <div className="flex items-end gap-1.5 rounded-2xl border border-slate-300 bg-surface py-1.5 pl-3 pr-1.5 shadow-sm focus-within:border-violet-500 focus-within:ring-2 focus-within:ring-violet-500/25">
          <svg
            className="pointer-events-none mb-3 h-4 w-4 shrink-0 text-slate-400"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            aria-hidden="true"
            focusable="false"
          >
            <circle cx="9" cy="9" r="5.5" />
            <path d="M13.2 13.2L17 17" />
          </svg>
          <textarea
            ref={inputRef}
            data-palette-input
            rows={1}
            role="combobox"
            aria-label="Хайх"
            aria-controls="palette-results"
            aria-expanded="true"
            placeholder="Ажилтан, хуудас хайх…"
            autoComplete="off"
            value={box}
            onChange={(e) => {
              setBox(e.target.value);
              setChoice(null);
            }}
            onKeyDown={onKeyDown}
            className="block max-h-40 min-h-9 flex-1 resize-none self-center bg-transparent py-1.5 text-base leading-6 outline-none placeholder:text-slate-400 max-sm:min-h-11"
          />
        </div>
        <div data-palette-hint className="mt-1.5 hidden items-center justify-center text-xs text-slate-500 sm:flex">
          <span>
            <kbd className="rounded border border-slate-300 bg-surface px-1.5 text-xs">↑↓</kbd> сонгох ·{" "}
            <kbd className="rounded border border-slate-300 bg-surface px-1.5 text-xs">Enter</kbd> нээх ·{" "}
            <kbd className="rounded border border-slate-300 bg-surface px-1.5 text-xs">Shift+Enter</kbd> мөр ·{" "}
            <kbd className="rounded border border-slate-300 bg-surface px-1.5 text-xs">Esc</kbd> хаах
          </span>
        </div>
      </div>
    </>
  );
}
