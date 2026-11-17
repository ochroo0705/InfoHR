import { useCallback, useEffect, useState, type ReactNode } from "react";

// The exit primitive for the React app: a pop-up, panel or row stays mounted while it plays its exit, then goes.
// Port of window.hrLeave (app/static/js/motion.js, plan 2026-11-08-selection-motion). The exit's CSS is the
// [data-leaving] rules in styles/motion.css.
//
// Usage: render the element while `mounted`, set `ref` on it, and while `leaving` set data-leaving="" and inert.

export type PresenceState = {
  mounted: boolean;
  leaving: boolean;
  ref: (el: HTMLElement | null) => void;
};

export type PresenceOptions = {
  // The exit's fallback timer. It must stay above --dur-out (140 ms) and under 300 ms, the longest motion in the app.
  fallbackMs?: number;
};

type Phase = { mounted: boolean; leaving: boolean };

const DEFAULT_FALLBACK_MS = 250;
const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
const SHOWN: Phase = { mounted: true, leaving: false };
const GONE: Phase = { mounted: false, leaving: false };

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_QUERY).matches
  );
}

export function usePresence(open: boolean, opts?: PresenceOptions): PresenceState {
  const fallbackMs = opts?.fallbackMs ?? DEFAULT_FALLBACK_MS;
  const [phase, setPhase] = useState<Phase>(open ? SHOWN : GONE);
  // The element is kept in state, not in a ref, so the listener effect re-runs when the element changes.
  const [node, setNode] = useState<HTMLElement | null>(null);
  const ref = useCallback((el: HTMLElement | null) => setNode(el), []);

  // Opening (also reopening during an exit) shows the element again; closing starts the exit, or removes it at once
  // under reduced motion.
  useEffect(() => {
    if (open) {
      setPhase((p) => (p.mounted && !p.leaving ? p : SHOWN));
      return;
    }
    const reduced = prefersReducedMotion();
    setPhase((p) => {
      if (!p.mounted) return p;
      return reduced ? GONE : { mounted: true, leaving: true };
    });
  }, [open]);

  const leaving = phase.leaving;

  // The fallback: the exit ends after fallbackMs even if no animationend arrives. A reopen clears this timer.
  useEffect(() => {
    if (!leaving) return;
    const id = setTimeout(() => setPhase(GONE), fallbackMs);
    return () => clearTimeout(id);
  }, [leaving, fallbackMs]);

  // The element's own animationend ends the exit. A child's animationend bubbles up here, so its target is checked.
  useEffect(() => {
    if (!node || !leaving) return;
    const onEnd = (e: Event) => {
      if (e.target !== node) return;
      setPhase(GONE);
    };
    node.addEventListener("animationend", onEnd);
    return () => node.removeEventListener("animationend", onEnd);
  }, [node, leaving]);

  return { mounted: phase.mounted, leaving: phase.leaving, ref };
}

// Render-prop form for JSX: <Presence open={open}>{(s) => s.mounted ? <div ref={s.ref} ... /> : null}</Presence>
export function Presence(props: {
  open: boolean;
  fallbackMs?: number;
  children: (state: PresenceState) => ReactNode;
}): ReactNode {
  const state = usePresence(props.open, { fallbackMs: props.fallbackMs });
  return props.children(state);
}
