import { useEffect, useLayoutEffect, useState } from "react";

// The sticky tool strip of a report page (app/reports/templates/reports/report.html, app/static/js/report_sticky.js,
// UI_RULES §4b). Once the filter panel has scrolled under the top bar, a thin strip shows the applied filters as chips
// and the «Багана», «Шүүлтүүр», «Хэлбэр» buttons (they click the real ribbon links) and «↑ Дээш». The wrapper has no
// height, so the page never shifts. Pure display: no value is changed.

const TOPBAR = 56; // the top bar is h-14 (report_sticky.js TOPBAR)
const CHIP_CLASS = "shrink-0 rounded-full bg-violet-50 px-2.5 py-1 text-xs text-violet-700";
const TOOL_CLASS = "rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50";

export interface StickyStripProps {
  tools: { columns: boolean; rules: boolean; format: boolean };
}

// The filter panel is the parent of the form #report-filters (report_sticky.js). A layout without a filter bar (cards,
// board, chart, ...) has no form: the tool ribbon above it stands in, so the strip still appears (report.html draws the
// strip for every layout).
function filterPanel(): HTMLElement | null {
  const form = document.getElementById("report-filters");
  if (form) return form.parentElement;
  return document.querySelector<HTMLElement>("[data-sticky-anchor]");
}

// The text of one chip for an applied filter holder (report_sticky.js chipText): the selected option, «Хайлт: …» for the
// search, and the two dates of a range joined by « – ».
export function chipText(holder: Element): string {
  const ctl = holder.matches("select, input") ? holder : holder.querySelector("select, input");
  if (!ctl) return "";
  if (ctl instanceof HTMLSelectElement) {
    const option = ctl.options[ctl.selectedIndex];
    return option ? option.text.trim() : "";
  }
  const input = ctl as HTMLInputElement;
  if (input.name === "q") return input.value.trim() ? "Хайлт: " + input.value.trim() : "";
  return Array.from(holder.querySelectorAll("input"))
    .map((field) => field.value)
    .filter(Boolean)
    .join(" – ");
}

// Every chip the page shows now: the applied filters, then the rules text.
export function readChips(): string[] {
  const texts: string[] = [];
  const form = document.getElementById("report-filters");
  form?.querySelectorAll("[data-applied]").forEach((holder) => {
    const text = chipText(holder);
    if (text) texts.push(text);
  });
  const rules = document.querySelector("[data-rules-text]")?.textContent?.trim();
  if (rules) texts.push(rules);
  return texts;
}

function isBelowTopBar(): boolean {
  const panel = filterPanel();
  return panel !== null && panel.getBoundingClientRect().bottom < TOPBAR;
}

// A tool button clicks the real control of the ribbon (report_sticky.js data-strip-tool).
function clickRibbonTool(tool: string) {
  document.querySelector<HTMLElement>(`[data-tool="${tool}"]`)?.click();
}

// Scrolls the filter panel into view (report_sticky.js data-strip-top).
function scrollToFilters() {
  filterPanel()?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function StickyStrip({ tools }: StickyStripProps) {
  const [shown, setShown] = useState(false);
  // Chips are read from the DOM after every render (the filter bar and the rules line are drawn in the same commit, and
  // layout effects run after it). The state is only set when the text changes, so this cannot loop.
  const [chipsKey, setChipsKey] = useState("[]");

  useLayoutEffect(() => {
    setShown(isBelowTopBar());
    setChipsKey(JSON.stringify(readChips()));
  });

  // Scroll and resize are throttled to one measurement per frame and removed on unmount.
  useEffect(() => {
    let frame: number | null = null;
    const update = () => {
      frame = null;
      setShown(isBelowTopBar());
    };
    const schedule = () => {
      if (frame === null) frame = requestAnimationFrame(update);
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, []);

  const chips = JSON.parse(chipsKey) as string[];

  return (
    <div data-sticky-strip className="sticky top-14 z-30 h-0">
      <div
        data-sticky-strip-bar
        hidden={!shown}
        className="absolute inset-x-0 top-0 flex items-center gap-2 border-b border-slate-200 bg-surface px-3 py-2 text-sm shadow-lg"
      >
        <div data-sticky-strip-chips className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto whitespace-nowrap">
          {chips.map((text, index) => (
            <span key={index} className={CHIP_CLASS}>
              {text}
            </span>
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {tools.columns ? (
            <button type="button" data-strip-tool="columns" className={TOOL_CLASS} onClick={() => clickRibbonTool("columns")}>
              Багана
            </button>
          ) : null}
          {tools.rules ? (
            <button type="button" data-strip-tool="rules" className={TOOL_CLASS} onClick={() => clickRibbonTool("rules")}>
              Шүүлтүүр
            </button>
          ) : null}
          {tools.format ? (
            <button type="button" data-strip-tool="format" className={TOOL_CLASS} onClick={() => clickRibbonTool("format")}>
              Хэлбэр
            </button>
          ) : null}
          <button
            type="button"
            data-strip-top
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-white hover:bg-violet-700"
            onClick={scrollToFilters}
          >
            ↑ Дээш
          </button>
        </div>
      </div>
    </div>
  );
}
