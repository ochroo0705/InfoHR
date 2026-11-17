import { createElement, useCallback, type MouseEvent, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { Link, useNavigate } from "react-router";

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

export function useTransitionNavigate(): (to: string) => void {
  const navigate = useNavigate();
  return useCallback(
    (to: string) => {
      runViewTransition(() => {
        // flushSync commits the new route before the browser takes the "after" snapshot.
        flushSync(() => {
          void navigate(to);
        });
      });
    },
    [navigate],
  );
}

type TLinkProps = {
  to: string;
  children: ReactNode;
  className?: string;
  // The server decides the active item (nav groups), so the caller passes aria-current instead of NavLink.
  "aria-current"?: "page";
};

// A router link whose plain left click goes through useTransitionNavigate. Modified clicks (new tab, new window)
// and middle clicks keep the browser's own behaviour, because the link's href stays in place.
export function TLink({ to, children, className, "aria-current": ariaCurrent }: TLinkProps) {
  const go = useTransitionNavigate();
  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(to);
  }
  return createElement(Link, { to, className, onClick, "aria-current": ariaCurrent }, children);
}
