import { useEffect, type RefObject } from "react";

// The sticky table header of a report page (app/static/js/report_sticky.js, the second part, UI_RULES §4b). The table
// sits in a sideways scroll box (.ptable), which turns CSS `position: sticky` off, so while the real header is above the
// line (the top bar, plus the sticky strip when it shows) a fixed copy of the header is drawn in <body>. The copy only
// appears and disappears; it follows the box's sideways scroll. Clicks on the copy's links are handed to the real ones,
// so the router still handles them. Pure display: no value is changed.

const TOPBAR = 56; // the top bar is h-14

// `resetKey` is anything that changes the header's widths or rows (the address, the version of the answer, the batches
// loaded): the copy is dropped and measured again. `disabled` (the table is inert while a new address loads) drops the
// copy and draws none, because the copy sits in <body> and would bypass the inert rule.
export function useStickyHeader(tableRef: RefObject<HTMLTableElement | null>, resetKey: string, disabled = false) {
  useEffect(() => {
    const table = tableRef.current;
    const box = table?.parentElement;
    if (!table || !box || disabled) return;
    const doc = table.ownerDocument;
    let clone: HTMLElement | null = null;
    let frame: number | null = null;

    function drop() {
      clone?.remove();
      clone = null;
    }

    // The line under which the real header counts as out of view: the top bar, plus the strip when it is shown.
    function lineBelow(): number {
      const bar = doc.querySelector<HTMLElement>("[data-sticky-strip-bar]");
      const stripShown = bar !== null && !bar.hidden;
      return TOPBAR + (stripShown && bar ? bar.offsetHeight : 0);
    }

    function place(el: HTMLElement, rect: DOMRect, top: number) {
      el.style.top = `${top}px`;
      el.style.left = `${rect.left}px`;
      el.style.width = `${rect.width}px`;
    }

    function build(rect: DOMRect, top: number): HTMLElement {
      const head = table!.tHead!;
      const wrap = doc.createElement("div");
      wrap.setAttribute("data-sticky-head", "");
      wrap.className = "ptable"; // the same th look as the real header
      wrap.style.cssText =
        "position:fixed;margin:0;overflow:hidden;z-index:25;border-radius:0;border-top:0;" +
        "box-shadow:0 4px 6px -2px rgba(15,23,42,.18)";
      const copy = doc.createElement("table");
      copy.style.cssText = `table-layout:fixed;border-collapse:collapse;width:${table!.offsetWidth}px`;
      const thead = head.cloneNode(true) as HTMLTableSectionElement;
      thead.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
      const srcTh = head.querySelectorAll("th");
      thead.querySelectorAll("th").forEach((th, index) => {
        const width = `${srcTh[index]?.getBoundingClientRect().width ?? 0}px`;
        th.style.width = width;
        th.style.minWidth = width;
        th.style.maxWidth = width;
        th.style.background = "var(--color-slate-100)";
        th.style.borderBottom = "1px solid var(--color-slate-300)";
      });
      // A plain or Shift click on a copied link is handed to the real link (same order) as a new click with the same
      // modifiers, so the real link's own handlers decide (a Shift click appends the sort). Ctrl, Meta, Alt and other
      // buttons are not intercepted: the copied anchor has the same href, so the browser does what it does on the real one.
      const srcLinks = head.querySelectorAll("a");
      thead.querySelectorAll("a").forEach((link, index) => {
        link.addEventListener("click", (event) => {
          if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey) return;
          const real = srcLinks[index];
          if (!real) return;
          event.preventDefault();
          real.dispatchEvent(
            new MouseEvent("click", {
              bubbles: true,
              cancelable: true,
              shiftKey: event.shiftKey,
              button: 0,
            }),
          );
        });
      });
      copy.appendChild(thead);
      wrap.appendChild(copy);
      doc.body.appendChild(wrap);
      place(wrap, rect, top);
      wrap.scrollLeft = box!.scrollLeft;
      return wrap;
    }

    function update() {
      frame = null;
      if (!table!.tHead) {
        drop();
        return;
      }
      const top = lineBelow();
      const rect = box!.getBoundingClientRect();
      const headH = table!.tHead.getBoundingClientRect().height;
      const footH = table!.tFoot ? table!.tFoot.getBoundingClientRect().height : 0;
      // Shown while the real header is above the line and the table still has body rows under it.
      const want = rect.top < top && rect.bottom - footH - headH > top;
      if (!want) {
        drop();
        return;
      }
      if (clone) place(clone, rect, top);
      else clone = build(rect, top);
    }

    function schedule() {
      if (frame === null) frame = requestAnimationFrame(update);
    }

    function onResize() {
      drop();
      schedule();
    }

    function onBoxScroll() {
      if (clone) clone.scrollLeft = box!.scrollLeft;
    }

    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", onResize);
    box.addEventListener("scroll", onBoxScroll, { passive: true });
    schedule();

    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", onResize);
      box.removeEventListener("scroll", onBoxScroll);
      if (frame !== null) cancelAnimationFrame(frame);
      drop();
    };
  }, [tableRef, resetKey, disabled]);
}
