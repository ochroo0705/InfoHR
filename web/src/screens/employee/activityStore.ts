import { useEffect, useState } from "react";

// The «Түүх» drawer's open state, kept across pages on wide screens (detail.html's hr.activityOpen in localStorage),
// and the wide breakpoint. Kept apart from the component file (react-refresh: a file exports components or helpers).

export const WIDE_QUERY = "(min-width:1024px)";
const STORE_KEY = "hr.activityOpen";

export function isWide(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches;
}

// Tracks the wide breakpoint, so the backdrop and the page padding follow a resize (detail.html's resize listener).
export function useWide(): boolean {
  const [wide, setWide] = useState(isWide);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(WIDE_QUERY);
    const onChange = () => setWide(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return wide;
}

// The state the drawer had when the page was left. Only a wide screen reopens it (detail.html's load-time render).
export function readActivityOpen(): boolean {
  try {
    return isWide() && localStorage.getItem(STORE_KEY) === "1";
  } catch {
    return false;
  }
}

// Called by the page on each user open and close. Opening is kept only on a wide screen, closing always (detail.html).
export function writeActivityOpen(open: boolean): void {
  if (open && !isWide()) return;
  try {
    localStorage.setItem(STORE_KEY, open ? "1" : "0");
  } catch {
    // Private mode or blocked storage: the drawer simply starts closed next time.
  }
}
