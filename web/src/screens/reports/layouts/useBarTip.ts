import {
  createElement,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// The timeline bar tooltip (port of app/static/js/bar_tip.js, UI_RULES §4b): the bar's name and its dates and days, in
// one floating box. It shows on pointer hover and on keyboard focus, and it leaves on pointer out, blur, Escape, or any
// scroll. The box sits centred above the bar, or below it when there is no room above, and is kept inside the window
// with an 8 px margin. Title and text are rendered as text, never as HTML.

export interface BarTipData {
  title: string;
  tip: string;
}

export interface BarTipHandlers {
  onMouseEnter: (event: MouseEvent<HTMLElement>) => void;
  onMouseLeave: () => void;
  onFocus: (event: FocusEvent<HTMLElement>) => void;
  onBlur: () => void;
}

interface Shown extends BarTipData {
  anchor: DOMRect;
}

const MARGIN = 8;
const BOX_CLASS =
  "pointer-events-none fixed z-50 flex max-w-xs flex-col rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow-lg";

export function useBarTip(): {
  bind: (data: BarTipData) => BarTipHandlers;
  tip: ReactNode;
} {
  const [shown, setShown] = useState<Shown | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const show = (element: HTMLElement, data: BarTipData) => {
    setShown({ ...data, anchor: element.getBoundingClientRect() });
  };
  const hide = () => setShown(null);

  // The box is measured once it is drawn, then placed before the browser paints it.
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!shown || !box) return;
    const width = box.offsetWidth;
    const height = box.offsetHeight;
    const rect = shown.anchor;
    const left = Math.min(
      Math.max(MARGIN, rect.left + rect.width / 2 - width / 2),
      window.innerWidth - width - MARGIN,
    );
    let top = rect.top - height - MARGIN;
    if (top < MARGIN) top = rect.bottom + MARGIN;
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  }, [shown]);

  // While the box is up: Escape closes it, and any scroll closes it (the box is fixed, so it would not follow the bar).
  useEffect(() => {
    if (!shown) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShown(null);
    };
    const onScroll = () => setShown(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [shown]);

  const bind = (data: BarTipData): BarTipHandlers => ({
    onMouseEnter: (event) => show(event.currentTarget, data),
    onMouseLeave: hide,
    onFocus: (event) => show(event.currentTarget, data),
    onBlur: hide,
  });

  const tip = shown
    ? createPortal(
        createElement(
          "div",
          { ref: boxRef, role: "tooltip", className: BOX_CLASS, style: { left: 0, top: 0 } },
          createElement("strong", { className: "font-semibold" }, shown.title),
          createElement("span", null, shown.tip),
        ),
        document.body,
      )
    : null;

  return { bind, tip };
}
