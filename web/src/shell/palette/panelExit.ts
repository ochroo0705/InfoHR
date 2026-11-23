// The assistant panel's exit state. Port of isPanelOpen, startExit and cancelExit in app/static/js/palette.js (plan
// 2026-11-08-selection-motion, task 9). A panel that is sliding out is still visible (hidden is false) but no longer open:
// isPanelOpen is false from the moment the exit starts. Each exit has a token (el.__closing): cancelExit (a reopen during
// the exit) clears it, so the pending done() does nothing, as nav.js does. No DOM here: the element is a minimal interface,
// so the tests use plain objects.

export type ExitElement = {
  hidden: boolean;
  inert: boolean;
  __closing?: object | null;
  hasAttribute(name: string): boolean;
  setAttribute(name: string): void;
  removeAttribute(name: string): void;
};

// The leave animation: window.hrLeave in the page. It sets data-leaving and inert on the element, then calls done when the
// exit has ended.
export type LeaveFn = (el: ExitElement, opts: { done: () => void }) => void;

export function isPanelOpen(el: ExitElement): boolean {
  return !el.hidden && !el.hasAttribute("data-leaving");
}

// Starts the exit of el through hrLeaveFn. done() clears the leaving state and then calls hide(), and only while its own
// token is still current. Without hrLeaveFn the element is hidden at once.
export function startExit(el: ExitElement, hrLeaveFn: LeaveFn | undefined, hide: () => void): void {
  if (typeof hrLeaveFn !== "function") {
    el.__closing = null;
    hide();
    return;
  }
  const token = {};
  el.__closing = token;
  hrLeaveFn(el, {
    done: () => {
      if (el.__closing !== token) return; // cancelled by cancelExit, or a newer exit has taken over
      el.__closing = null;
      el.removeAttribute("data-leaving");
      el.inert = false;
      hide();
    },
  });
}

// Cancels an exit in flight: the element is shown and interactive again, and the pending done() does nothing.
export function cancelExit(el: ExitElement): void {
  el.__closing = null;
  el.removeAttribute("data-leaving");
  el.inert = false;
}
