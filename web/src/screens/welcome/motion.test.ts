import { afterEach, describe, expect, it, vi } from "vitest";
import { canAnimate, prefersReducedMotion, registerGsap } from "./motion";

function stubMatchMedia(matches: boolean) {
  // Shaped like a MediaQueryList: GSAP subscribes to changes through addEventListener.
  const stub = (query: string) => ({
    matches,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  });
  vi.stubGlobal("matchMedia", vi.fn(stub));
}

describe("motion helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("treats reduced motion as true when window.matchMedia is missing", () => {
    delete (window as { matchMedia?: unknown }).matchMedia;
    expect(prefersReducedMotion()).toBe(true);
    expect(canAnimate()).toBe(false);
  });

  it("returns true when the reduced-motion query matches", () => {
    stubMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    expect(canAnimate()).toBe(false);
  });

  it("returns false and canAnimate true when the reduced-motion query does not match", () => {
    stubMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
    expect(canAnimate()).toBe(true);
  });

  it("queries the prefers-reduced-motion media feature", () => {
    stubMatchMedia(false);
    prefersReducedMotion();
    expect(window.matchMedia).toHaveBeenCalledWith("(prefers-reduced-motion: reduce)");
  });

  it("registerGsap does not throw when window.matchMedia is missing", async () => {
    delete (window as { matchMedia?: unknown }).matchMedia;
    vi.resetModules();
    const motion = await import("./motion");
    expect(() => motion.registerGsap()).not.toThrow();
  });

  it("registerGsap does not throw and does not register plugins on the reduced-motion path", async () => {
    stubMatchMedia(true);
    vi.resetModules();
    const { gsap } = await import("gsap");
    const spy = vi.spyOn(gsap, "registerPlugin");
    const motion = await import("./motion");
    expect(() => motion.registerGsap()).not.toThrow();
    expect(spy).not.toHaveBeenCalled();
  });

  it("registerGsap registers the plugins exactly once when animation can run", async () => {
    stubMatchMedia(false);
    vi.resetModules();
    const { gsap } = await import("gsap");
    const spy = vi.spyOn(gsap, "registerPlugin");
    const motion = await import("./motion");
    motion.registerGsap();
    motion.registerGsap();
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
