import {
  createElement,
  useCallback,
  useRef,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router";
import { anyUnsaved, confirmLeave } from "./unsaved";

// Page cross-fade for the React app. Port of the same-origin View Transitions rules in styles/motion.css (input.css
// 482-493): when the browser has document.startViewTransition and the user has not asked for reduced motion, a
// client-side navigation runs inside a view transition. Otherwise the navigation runs at once, as a plain load would.

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

type ViewTransitionLike = {
  ready: Promise<void>;
  finished: Promise<void>;
  updateCallbackDone: Promise<void>;
};

type DocumentWithViewTransitions = Document & {
  startViewTransition?: (update: () => void) => ViewTransitionLike;
};

function motionAllowed(): boolean {
  return (
    typeof window.matchMedia !== "function" || !window.matchMedia(REDUCED_QUERY).matches
  );
}

// Runs update inside a view transition when one can run. The three promises are swallowed the same way base.html
// line 9 does it (inventory M-11): an aborted transition is normal (a fast second click) and must not log an error.
export function runViewTransition(update: () => void): void {
  const doc = document as DocumentWithViewTransitions;
  if (typeof doc.startViewTransition !== "function" || !motionAllowed()) {
    update();
    return;
  }
  const transition = doc.startViewTransition(update);
  for (const promise of [transition.ready, transition.finished, transition.updateCallbackDone]) {
    promise.catch(() => {});
  }
}

// True when the link keeps the current path (a hash, a query, or the same page). Only a path change counts as leaving.
function staysOnPath(to: string, current: string): boolean {
  return new URL(to, "http://local" + current).pathname === current;
}

export function useTransitionNavigate(): (to: string) => void {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // A leave question that is open: a second click on a leave link meanwhile does nothing (one question, one navigation).
  const asking = useRef(false);
  return useCallback(
    (to: string) => {
      const go = () => {
        runViewTransition(() => {
          // flushSync commits the new route before the browser takes the "after" snapshot.
          flushSync(() => {
            void navigate(to);
          });
        });
      };
      // Leaving the page with unsaved edits asks first (the unsaved registry, unsaved.ts). A same-page link does not ask.
      if (!anyUnsaved() || staysOnPath(to, pathname)) {
        go();
        return;
      }
      if (asking.current) return;
      asking.current = true;
      void confirmLeave().then((ok) => {
        asking.current = false;
        if (ok) go();
      });
    },
    [navigate, pathname],
  );
}

type TLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  to: string;
  children: ReactNode;
  className?: string;
  // The server decides the active item (nav groups), so the caller passes aria-current instead of NavLink.
  "aria-current"?: "page";
};

// A router link whose plain left click goes through useTransitionNavigate. Modified clicks (new tab, new window)
// and middle clicks keep the browser's own behaviour, because the link's href stays in place. Other anchor props
// (id, title, data-*, target, ...) reach the anchor. The caller's onClick runs first; if it calls preventDefault,
// or the link has a target other than _self, the browser handles the click.
export function TLink({
  to,
  children,
  className,
  onClick,
  target,
  "aria-current": ariaCurrent,
  ...rest
}: TLinkProps) {
  const go = useTransitionNavigate();
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0) return;
    if (target && target !== "_self") return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(to);
  }
  return createElement(
    Link,
    { ...rest, to, target, className, onClick: handleClick, "aria-current": ariaCurrent },
    children,
  );
}
