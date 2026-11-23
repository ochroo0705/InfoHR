import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

// Single place for motion decisions on the /welcome page. Every GSAP import on that page goes through here,
// so animations can be skipped or retuned in one file.

export const EASE = "power3.out";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

// jsdom and some old browsers have no matchMedia. Treat that as reduced motion: the page shows its final static state.
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

export function canAnimate(): boolean {
  return !prefersReducedMotion();
}

let pluginsRegistered = false;

// Registers the GSAP plugins this page uses. Safe to call more than once.
// Does nothing on the reduced-motion path (or without matchMedia): ScrollTrigger's registration calls
// gsap.matchMedia(), which throws there, and no animation runs anyway, so the plugins are not needed.
export function registerGsap(): void {
  if (pluginsRegistered || !canAnimate()) {
    return;
  }
  gsap.registerPlugin(ScrollTrigger, SplitText);
  pluginsRegistered = true;
}

// Re-exported so components import GSAP only through this file.
export { gsap, ScrollTrigger, SplitText };
