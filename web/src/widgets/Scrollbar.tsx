import { useEffect, useRef, type HTMLAttributes, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { cn } from "../lib/utils";

// The app's scrollbars (UI_RULES §4; port of app/static/js/scrollbars.js, CSS in styles/scrollbars.css).
// Native scrollbars cannot animate, so an opted-in scroll box gets its native bars hidden (.sbar-on) and two rails drawn
// over its edges: a hairline track with a progress fill. Press-and-drag anywhere on a rail; wheel, keyboard and touch
// scrolling of the box keep working, the rails only mirror and drive scrollTop/Left. Three kinds:
//   ScrollHost     - a table frame (.ptable-fit): wrapped in .sbar-host, rails inside it, plus edge fades for hidden columns
//   ScrollFloat    - any other scroll box (menus, lists, pop-ups): rails are position: fixed in <body>, laid over the box's
//                    edges and clipped to the part of it that is visible
//   PageScrollbar  - the document: one vertical rail under the top bar, mounted once in AppShell. It hides while a
//                    pop-up locks the page (body overflow hidden, from body:has(.fixed.inset-0.z-50) in app.css).
// Opt out with the off prop: the box keeps its native bars (data-sbar="off").
// Not ported: the global scan of every overflow element. A box gets rails only when it renders one of these components.

const MIN = 28;   // shortest fill, px
const LANE = 12;  // rail thickness, px

type Axis = "x" | "y";
type Kind = "host" | "float" | "page";

interface Rig {
  kind: Kind;
  box: HTMLElement; // the scroll box; the document element for the page kind
  rails: { x?: HTMLElement; y?: HTMLElement };
  fades?: { l: HTMLElement; r: HTMLElement };
}

interface RailState {
  el: HTMLElement;
  thumb: HTMLElement;
  axis: Axis;
}

// A float rail sits just above the stacking layer its box lives in.
function zOf(node: HTMLElement): number {
  let z = 0;
  for (let e: HTMLElement | null = node; e && e !== document.body; e = e.parentElement) {
    const v = parseInt(getComputedStyle(e).zIndex, 10);
    if (!isNaN(v)) z = Math.max(z, v);
  }
  return z + 1;
}

// The part of the viewport the box can be seen in (its scrolling or clipping ancestors).
function clipOf(node: HTMLElement) {
  const c = { l: 0, t: 0, r: window.innerWidth, b: window.innerHeight };
  for (let e = node.parentElement; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
    const s = getComputedStyle(e);
    if (s.overflowX === "visible" && s.overflowY === "visible") continue;
    const r = e.getBoundingClientRect();
    c.l = Math.max(c.l, r.left);
    c.t = Math.max(c.t, r.top);
    c.r = Math.min(c.r, r.right);
    c.b = Math.min(c.b, r.bottom);
  }
  return c;
}

// Draws the rails of one scroll box and keeps them in step with it. Returns the cleanup.
export function attachScrollbar(rig: Rig): () => void {
  const { kind, box } = rig;
  const page = kind === "page";
  const sc = (page ? (document.scrollingElement ?? document.documentElement) : box) as HTMLElement; // holds the scroll values
  const cleanups: Array<() => void> = [];

  function railState(el: HTMLElement | undefined, axis: Axis): RailState | undefined {
    const thumb = el?.querySelector<HTMLElement>(".sbar-thumb");
    return el && thumb ? { el, thumb, axis } : undefined;
  }
  const X = railState(rig.rails.x, "x");
  const Y = railState(rig.rails.y, "y");
  const z = page ? 0 : zOf(box);

  function sizes(r: RailState) {
    const x = r.axis === "x";
    const view = page ? (x ? window.innerWidth : window.innerHeight) : x ? sc.clientWidth : sc.clientHeight;
    const full = x ? sc.scrollWidth : sc.scrollHeight;
    const track = x ? r.el.clientWidth : r.el.clientHeight;
    return { view, full, track, max: Math.max(0, full - view) };
  }

  // Progress fill: starts at the share in view, grows to the whole rail at the end of the scroll.
  function fill(r: RailState) {
    const s = sizes(r);
    const pos = r.axis === "x" ? sc.scrollLeft : sc.scrollTop;
    const done = s.max > 0 ? pos / s.max : 0;
    const start = Math.max(MIN, Math.min(s.track, (s.track * s.view) / Math.max(1, s.full)));
    const px = Math.round(start + (s.track - start) * Math.min(1, done));
    r.thumb.style[r.axis === "x" ? "width" : "height"] = `${px}px`;
  }

  function show(r: RailState | undefined, on: boolean): boolean {
    r?.el.classList.toggle("is-on", on);
    return on;
  }

  function paintPage(rail: RailState) {
    const locked = getComputedStyle(document.body).overflowY === "hidden"; // a pop-up holds the page still
    // The top bar (scrollbars.js: "body > header"). In the SPA it sits inside #root, so look for the shell's sticky header.
    const head = document.querySelector<HTMLElement>("body > header, #root header.sticky");
    const top = head ? Math.max(0, head.getBoundingClientRect().bottom) : 0;
    if (show(rail, !locked && sc.scrollHeight > window.innerHeight + 1)) {
      const s = rail.el.style;
      s.top = `${top}px`;
      s.height = `${window.innerHeight - top}px`;
      s.left = `${window.innerWidth - LANE}px`;
      fill(rail);
    }
  }

  function paintHost() {
    const w = box.clientWidth, h = box.clientHeight;
    const needX = box.scrollWidth > w + 1, needY = box.scrollHeight > h + 1;
    const t = box.offsetTop + box.clientTop, l = box.offsetLeft + box.clientLeft;
    if (show(X, needX) && X) {
      const s = X.el.style;
      s.left = `${l}px`;
      s.width = `${w - (needY ? LANE : 0)}px`;
      s.top = `${t + h - LANE}px`;
      fill(X);
    }
    if (show(Y, needY) && Y) {
      const s = Y.el.style;
      s.top = `${t}px`;
      s.height = `${h - (needX ? LANE : 0)}px`;
      s.left = `${l + w - LANE}px`;
      fill(Y);
    }
    // Edge fades: a soft shade on a side while columns are hidden past it. The left one starts after pinned columns.
    if (rig.fades) {
      const maxX = box.scrollWidth - w;
      let pin = 0;
      box.querySelectorAll<HTMLElement>("thead th.sticky").forEach((th) => {
        pin = Math.max(pin, th.offsetLeft + th.offsetWidth);
      });
      const fl = rig.fades.l, fr = rig.fades.r;
      fl.style.top = fr.style.top = `${t}px`;
      fl.style.height = fr.style.height = `${h}px`;
      fl.style.left = `${l + pin}px`;
      fr.style.left = `${l + w - 24}px`;
      fl.classList.toggle("is-on", needX && box.scrollLeft > 1);
      fr.classList.toggle("is-on", needX && box.scrollLeft < maxX - 1);
    }
  }

  function paintFloat() {
    const w = box.clientWidth, h = box.clientHeight;
    const needX = box.scrollWidth > w + 1, needY = box.scrollHeight > h + 1;
    // the box's inner edges on screen, cut to the part of it that can be seen
    const b = box.getBoundingClientRect();
    const L = b.left + box.clientLeft, T = b.top + box.clientTop, R = L + w, B = T + h;
    const c = clipOf(box);
    const vis = typeof box.checkVisibility === "function" ? box.checkVisibility({ visibilityProperty: true }) : true; // closed <details> keeps a size
    const seen = vis && b.width > 0 && b.height > 0 && R > c.l && L < c.r && B > c.t && T < c.b;
    if (X) X.el.style.zIndex = String(z);
    if (Y) Y.el.style.zIndex = String(z);
    // a box taller than the screen keeps its sideways bar at the bottom of what is visible, not off-screen below
    const xb = Math.min(B, c.b);
    if (show(X, seen && needX && xb - LANE >= Math.max(T, c.t)) && X) {
      const x0 = Math.max(L, c.l), x1 = Math.min(R - (needY ? LANE : 0), c.r);
      const s = X.el.style;
      s.left = `${x0}px`;
      s.width = `${Math.max(0, x1 - x0)}px`;
      s.top = `${xb - LANE}px`;
      fill(X);
    }
    if (show(Y, seen && needY && R - LANE >= c.l && R <= c.r + 1) && Y) {
      const y0 = Math.max(T, c.t), y1 = Math.min(B - (needX ? LANE : 0), c.b);
      const s = Y.el.style;
      s.top = `${y0}px`;
      s.height = `${Math.max(0, y1 - y0)}px`;
      s.left = `${R - LANE}px`;
      fill(Y);
    }
  }

  function paint() {
    if (page) {
      if (Y) paintPage(Y);
    } else if (kind === "host") {
      paintHost();
    } else {
      paintFloat();
    }
  }

  // Press anywhere on a rail and drag: the fill's end follows the pointer, so the box scrolls to that point.
  let dragOff: (() => void) | null = null;  // removes the move and up listeners of a drag in progress
  cleanups.push(() => dragOff?.());

  function drag(r: RailState, e: PointerEvent) {
    e.preventDefault();
    const x = r.axis === "x";
    const to = (ev: PointerEvent) => {
      const rect = r.el.getBoundingClientRect(), s = sizes(r);
      const at = (x ? ev.clientX - rect.left : ev.clientY - rect.top) - MIN / 2;
      const v = Math.max(0, Math.min(1, at / Math.max(1, s.track - MIN))) * s.max;
      if (x) sc.scrollLeft = v;
      else sc.scrollTop = v;
    };
    r.el.classList.add("is-drag");
    r.el.setPointerCapture(e.pointerId);
    to(e);
    const off = () => {
      r.el.classList.remove("is-drag");
      r.el.removeEventListener("pointermove", to);
      r.el.removeEventListener("pointerup", off);
      r.el.removeEventListener("pointercancel", off);
      if (dragOff === off) dragOff = null;
    };
    r.el.addEventListener("pointermove", to);
    r.el.addEventListener("pointerup", off);
    r.el.addEventListener("pointercancel", off);
    dragOff = off;
  }

  function on(target: EventTarget, type: string, fn: (e: Event) => void, opts?: AddEventListenerOptions) {
    target.addEventListener(type, fn, opts);
    cleanups.push(() => target.removeEventListener(type, fn, opts));
  }

  let raf = 0;
  function schedule() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      paint();
    });
  }

  for (const r of [X, Y]) {
    if (!r) continue;
    on(r.el, "pointerdown", (e) => drag(r, e as PointerEvent));
    on(
      r.el,
      "wheel",
      (e) => {  // a wheel over a float rail still scrolls its box
        if (kind !== "float") return;
        e.preventDefault();
        const we = e as WheelEvent;
        sc.scrollBy(we.deltaX, we.deltaY);
      },
      { passive: false },
    );
  }

  // The same repaint triggers as scrollbars.js (its htmx:afterSettle is not used here: the React app has no htmx).
  on(document, "scroll", schedule, { capture: true, passive: true });
  for (const type of ["toggle", "animationend", "transitionend", "pointerup", "keyup"]) {
    on(document, type, schedule, { capture: true });
  }
  on(window, "resize", schedule);

  // The box's first child is measured too. When it is swapped in place, the new child is observed instead.
  let ro: ResizeObserver | null = null;
  let observedChild: Element | null = null;
  function observeChild() {
    if (!ro || page) return;
    if (observedChild) ro.unobserve(observedChild);
    observedChild = box.firstElementChild;
    if (observedChild) ro.observe(observedChild);
  }
  if (typeof ResizeObserver !== "undefined") {
    ro = new ResizeObserver(schedule);
    ro.observe(page ? document.body : box);
    observeChild();
    cleanups.push(() => ro?.disconnect());
  }

  // Pop-ups opening and closing, and content changing, move the rails. Changes inside a rail or a fade (the paint
  // itself) are ignored, so painting does not set off another paint. The scroll box's own class (sbar-on) is not ignored.
  const mo = new MutationObserver((list) => {
    const relevant = list.some((m) => !(m.target instanceof Element && m.target.closest(".sbar-rail, .sbar-fade")));
    if (relevant) {
      observeChild();
      schedule();
    }
  });
  mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "hidden", "open"] });
  cleanups.push(() => mo.disconnect());

  if (page) document.documentElement.classList.add("sbar-page-on");
  paint();

  return () => {
    cleanups.forEach((f) => f());
    if (raf) cancelAnimationFrame(raf);
    if (page) document.documentElement.classList.remove("sbar-page-on");
  };
}

function Rail({
  axis,
  railRef,
  fixed = false,
  page = false,
}: {
  axis: Axis;
  railRef: RefObject<HTMLDivElement | null>;
  fixed?: boolean;
  page?: boolean;
}) {
  return (
    <div
      ref={railRef}
      className={cn("sbar-rail", axis === "x" ? "sbar-x" : "sbar-y", fixed && "sbar-fixed", page && "sbar-page")}
      aria-hidden="true"
    >
      <div className="sbar-thumb" />
    </div>
  );
}

// A table frame (.ptable-fit or any box that scrolls in both directions). It wraps the box in .sbar-host.
export function ScrollHost({ className, off = false, children }: { className?: string; off?: boolean; children: ReactNode }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const xRef = useRef<HTMLDivElement>(null);
  const yRef = useRef<HTMLDivElement>(null);
  const lRef = useRef<HTMLDivElement>(null);
  const rRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (off || !box) return;
    const fades = lRef.current && rRef.current ? { l: lRef.current, r: rRef.current } : undefined;
    return attachScrollbar({
      kind: "host",
      box,
      rails: { x: xRef.current ?? undefined, y: yRef.current ?? undefined },
      fades,
    });
  }, [off]);

  if (off) {
    return (
      <div className={className} data-sbar="off">
        {children}
      </div>
    );
  }
  return (
    <div className="sbar-host">
      <div ref={boxRef} className={cn(className, "sbar-on")}>
        {children}
      </div>
      <div ref={lRef} className="sbar-fade sbar-fade-l" aria-hidden="true" />
      <div ref={rRef} className="sbar-fade sbar-fade-r" aria-hidden="true" />
      <Rail axis="x" railRef={xRef} />
      <Rail axis="y" railRef={yRef} />
    </div>
  );
}

// Any other scroll box (overflow auto or scroll). The caller sets the overflow classes on it.
export function ScrollFloat({
  className,
  off = false,
  children,
  boxRef: outerRef,
  ...rest
}: {
  className?: string;
  off?: boolean;
  children: ReactNode;
  // The caller's own ref to the scroll box (e.g. the nav strip measures and scrolls it).
  boxRef?: { current: HTMLDivElement | null };
} & Omit<HTMLAttributes<HTMLDivElement>, "className" | "children">) {
  const boxRef = useRef<HTMLDivElement>(null);
  const setBox = (el: HTMLDivElement | null) => {
    boxRef.current = el;
    if (outerRef) outerRef.current = el;
  };
  const xRef = useRef<HTMLDivElement>(null);
  const yRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (off || !box) return;
    return attachScrollbar({
      kind: "float",
      box,
      rails: { x: xRef.current ?? undefined, y: yRef.current ?? undefined },
    });
  }, [off]);

  return (
    <>
      <div {...rest} ref={setBox} className={cn(className, !off && "sbar-on")} data-sbar={off ? "off" : undefined}>
        {children}
      </div>
      {!off &&
        createPortal(
          <>
            <Rail axis="x" railRef={xRef} fixed />
            <Rail axis="y" railRef={yRef} fixed />
          </>,
          document.body,
        )}
    </>
  );
}

// The document's own scroll: one vertical rail under the top bar. Mount it once, in AppShell.
export function PageScrollbar() {
  const yRef = useRef<HTMLDivElement>(null);

  useEffect(
    () =>
      attachScrollbar({
        kind: "page",
        box: document.documentElement,
        rails: { y: yRef.current ?? undefined },
      }),
    [],
  );

  return createPortal(<Rail axis="y" railRef={yRef} fixed page />, document.body);
}
