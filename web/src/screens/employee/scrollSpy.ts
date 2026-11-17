import { useCallback, useEffect, useRef, useState } from "react";

// Port of the scroll-spy part of the inline script in app/employees/templates/employees/detail.html (setActive,
// showTab, spyPick, spy and the click handler). Thresholds, class names and timings are the template's own.
//
// The section ids are the names the rail and the narrow bar link to: "work", "salary", "personal". Each section is the
// element with id "tab-<name>". A section that is not on the page (no right to see it) is skipped, as the template does.

// A section counts as in view once its top has reached this many px from the top of the window.
export const SPY_LINE_PX = 120;
// After a click on a section link, the clicked link stays marked for this long (the smooth scroll passes other sections).
export const SPY_LOCK_MS = 600;
// The class the template puts on the active `.tab` link of the narrow bar (app.css / input.css: .tab.tab-on).
export const TAB_ON_CLASS = "tab-on";
// The classes the template puts on the active `.rtab` rail link (set and removed together).
export const RTAB_ON_CLASSES = ["bg-violet-50", "text-violet-700", "font-semibold"] as const;

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

function sectionEl(name: string): HTMLElement | null {
  return document.getElementById("tab-" + name);
}

// The section in view for the current scroll position, as the template's spyPick: the last section whose top has
// reached the line; above the first, the first; at the page's bottom, the last. With no section on the page, the
// current name is kept.
export function spyPick(names: string[], current: string): string {
  const found: { name: string; el: HTMLElement }[] = [];
  for (const name of names) {
    const el = sectionEl(name);
    if (el) found.push({ name, el });
  }
  if (found.length === 0) return current;
  let pick = found[0];
  for (const s of found) {
    if (s.el.getBoundingClientRect().top <= SPY_LINE_PX) pick = s;
  }
  if (window.scrollY > 0 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
    pick = found[found.length - 1];
  }
  return pick.name;
}

// Scrolls a section to the top of the window (the template's showTab). quiet: at once, as on page load; a reader's
// choice scrolls smoothly unless reduced motion is asked for.
export function showSection(name: string, quiet: boolean): void {
  const s = sectionEl(name);
  if (!s) return;
  const reduced = typeof window.matchMedia === "function" && window.matchMedia(REDUCED_QUERY).matches;
  s.scrollIntoView({ behavior: quiet || reduced ? "auto" : "smooth", block: "start" });
}

// Returns [name, markSection]: the name of the section in view, and a setter that marks a section at once (the
// load-time #hash uses it, as detail.html's setActive does). The rail and the narrow bar mark it: the caller sets
// TAB_ON_CLASS and aria-current on `.tab` links and RTAB_ON_CLASSES on `.rtab` links where the link's hash is "#<id>".
// It also handles clicks on `a[href^="#"]` links to a section: smooth scroll, the link stays marked for SPY_LOCK_MS,
// and the hash is replaced (not pushed), so Back does not step through sections.
//
// The spy re-runs on a scroll, on a resize of any section (a section grows when its body loads), and when a named
// section mounts after the effect (a MutationObserver watches the document until every name is on the page).
export function useScrollSpy(ids: string[]): [string, (name: string) => void] {
  const key = ids.join("|");
  const [active, setActive] = useState(ids[0] ?? "");
  const currentRef = useRef(active);
  const lockUntil = useRef(0);

  const markSection = useCallback((name: string) => {
    currentRef.current = name;
    setActive(name);
  }, []);

  useEffect(() => {
    const names = key === "" ? [] : key.split("|");
    let ticking = false;
    let frame = 0;

    // Runs at most once per frame, and not at all while a clicked link holds the mark.
    const spy = () => {
      ticking = false;
      if (Date.now() < lockUntil.current) return;
      markSection(spyPick(names, currentRef.current));
    };
    const schedule = () => {
      if (!ticking) {
        ticking = true;
        frame = requestAnimationFrame(spy);
      }
    };

    const onClick = (e: MouseEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      const a = target?.closest<HTMLAnchorElement>('a[href^="#"]') ?? null;
      if (!a) return;
      const name = a.hash.slice(1);
      if (!names.includes(name) || !sectionEl(name)) return;
      e.preventDefault();
      lockUntil.current = Date.now() + SPY_LOCK_MS;
      showSection(name, false);
      markSection(name);
      history.replaceState(null, "", a.hash);
    };

    // Sections that are on the page now are watched for size changes; the others are picked up as they mount.
    const observed = new Set<HTMLElement>();
    const resizer =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => schedule()) : null;
    const observeNew = (): boolean => {
      for (const name of names) {
        const el = sectionEl(name);
        if (el && !observed.has(el)) {
          observed.add(el);
          resizer?.observe(el);
        }
      }
      return observed.size === names.length;
    };
    let mutation: MutationObserver | null = null;
    if (!observeNew()) {
      mutation = new MutationObserver(() => {
        if (observeNew()) {
          mutation?.disconnect();
          mutation = null;
        }
        schedule();
      });
      mutation.observe(document.body, { childList: true, subtree: true });
    }

    window.addEventListener("scroll", schedule, { passive: true });
    document.addEventListener("click", onClick);
    spy();
    return () => {
      window.removeEventListener("scroll", schedule);
      document.removeEventListener("click", onClick);
      resizer?.disconnect();
      mutation?.disconnect();
      if (ticking) cancelAnimationFrame(frame);
    };
  }, [key, markSection]);

  return [active, markSection];
}
