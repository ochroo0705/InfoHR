import { useEffect, useRef, type RefObject } from "react";

// Calls onMore once when the element scrolls into view (the Django `hx-trigger="revealed"` of the «Цааш харуулах» pill).
// It observes only while `enabled` is true: a batch that is loading turns it off, and when the next batch lands the
// observer starts again, so the pill loads one batch per time it is seen. An observer that is still visible when it
// starts fires at once, as IntersectionObserver always reports the initial state.
export function useMoreSentinel(ref: RefObject<HTMLElement | null>, onMore: () => void, enabled: boolean): void {
  const onMoreRef = useRef(onMore);
  useEffect(() => {
    onMoreRef.current = onMore;
  });

  useEffect(() => {
    const element = ref.current;
    if (!enabled || !element || typeof IntersectionObserver === "undefined") return;
    let fired = false;
    const observer = new IntersectionObserver((entries) => {
      if (fired || !entries.some((entry) => entry.isIntersecting)) return;
      fired = true;
      onMoreRef.current();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, enabled]);
}
