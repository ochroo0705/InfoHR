import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { usePresence } from "../lib/presence";
import { placement } from "./rowMenuLogic";

// The «Үйлдэл ▾» menu of a table row (UI_RULES §2b-2; port of the row menus in app/static/js/row_menu.js and nav.js).
// A <details data-row-menu> whose panel is marked data-nav-panel and data-row-menu-panel. The panel is pinned to the
// screen when it opens (position fixed, see rowMenuLogic.placement), so the scrolling frame of the table cannot clip it.
// It closes with the exit (data-leaving, inert, usePresence) and never by removing the open attribute at once. Closes
// on: an item click, a click on the summary, an outside click, Escape, a scroll outside the panel, a window resize.
// Opening one menu closes the one that was open. The children are always in the DOM; the closed details hides them.

// The menu that is open now, so that opening another one closes it (row_menu.js closeAll).
let closeOpen: (() => void) | null = null;

export function RowMenu({ children, summary = "Үйлдэл ▾" }: { children: ReactNode; summary?: string }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  const presence = usePresence(open);

  // Pins the panel under its button when it opens (not while it leaves). The panel is measured after it is fixed,
  // as row_menu.js does, because a fixed panel's width can differ from an absolute one.
  useLayoutEffect(() => {
    if (!presence.mounted || presence.leaving) return;
    const details = detailsRef.current;
    const panel = details?.querySelector<HTMLElement>("[data-row-menu-panel]");
    const button = details?.querySelector("summary");
    if (!panel || !button) return;
    Object.assign(panel.style, { position: "fixed", zIndex: "40", marginTop: "0" });
    Object.assign(
      panel.style,
      placement(
        button.getBoundingClientRect(),
        { width: panel.offsetWidth, height: panel.offsetHeight },
        { width: window.innerWidth, height: window.innerHeight },
      ),
    );
  }, [presence.mounted, presence.leaving]);

  // While open: close the other menu, and listen for everything that closes this one.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    if (closeOpen && closeOpen !== close) closeOpen();
    closeOpen = close;

    const onClick = (e: Event) => {
      if (e.target instanceof Node && detailsRef.current?.contains(e.target)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      detailsRef.current?.querySelector("summary")?.focus();
    };
    // A scroll inside the panel (a long panel scrolling itself) does not close it; any other scroll does.
    const onScroll = (e: Event) => {
      if (e.target instanceof Element && e.target.closest("[data-row-menu-panel]")) return;
      close();
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", close);
      if (closeOpen === close) closeOpen = null;
    };
  }, [open]);

  // The native toggle is prevented: the state decides. A click on an open menu closes it with the exit; a click on a
  // menu that is leaving reopens it (nav.js: reopen).
  const onSummary = (e: MouseEvent<HTMLElement>) => {
    e.preventDefault();
    setOpen(!open);
  };

  return (
    <details ref={detailsRef} data-row-menu className="relative inline-block text-left" open={presence.mounted}>
      <summary
        onClick={onSummary}
        className="flex h-8 cursor-pointer list-none items-center rounded-lg border border-slate-300 bg-surface px-3 text-sm hover:bg-slate-50"
      >
        {summary}
      </summary>
      <div
        ref={presence.ref}
        data-nav-panel
        data-row-menu-panel
        data-leaving={presence.leaving ? "" : undefined}
        inert={presence.leaving}
        className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-slate-200 bg-surface py-1 text-left shadow-lg"
        onClick={() => setOpen(false)}
      >
        {children}
      </div>
    </details>
  );
}
