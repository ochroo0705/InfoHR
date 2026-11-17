import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apply, getChoice, setChoice, watchSystem } from "./theme";

// A stand-in for matchMedia('(prefers-color-scheme: dark)'): the test sets the system value and fires the change.
function stubSystemDark(initial: boolean) {
  const state = { dark: initial };
  const listeners = new Set<(e: { matches: boolean }) => void>();
  window.matchMedia = ((query: string) => ({
    get matches() {
      return state.dark;
    },
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: (_type: string, cb: (e: { matches: boolean }) => void) => listeners.add(cb),
    removeEventListener: (_type: string, cb: (e: { matches: boolean }) => void) => listeners.delete(cb),
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return {
    setSystemDark(value: boolean) {
      state.dark = value;
      listeners.forEach((cb) => cb({ matches: value }));
    },
  };
}

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    delete (window as { matchMedia?: unknown }).matchMedia;
    vi.restoreAllMocks();
  });

  it("setChoice('dark') stores the value and sets the attribute", () => {
    stubSystemDark(false);
    setChoice("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(getChoice()).toBe("dark");
  });

  it("setChoice('auto') removes the stored key and follows the system", () => {
    stubSystemDark(true);
    localStorage.setItem("theme", "light");
    setChoice("auto");
    expect(localStorage.getItem("theme")).toBeNull();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(getChoice()).toBe("auto");
  });

  it("anything other than light or dark in storage reads as auto", () => {
    stubSystemDark(false);
    localStorage.setItem("theme", "sepia");
    expect(getChoice()).toBe("auto");
    apply();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("in auto, a system change flips the attribute", () => {
    const system = stubSystemDark(false);
    setChoice("auto");
    expect(document.documentElement.dataset.theme).toBe("light");

    const stop = watchSystem();
    system.setSystemDark(true);
    expect(document.documentElement.dataset.theme).toBe("dark");
    stop();
  });

  it("in dark, a system change does not touch the attribute", () => {
    const system = stubSystemDark(false);
    setChoice("dark");

    const stop = watchSystem();
    system.setSystemDark(false);
    expect(document.documentElement.dataset.theme).toBe("dark");
    stop();
  });

  it("the returned function stops the system listener", () => {
    const system = stubSystemDark(false);
    setChoice("auto");
    const stop = watchSystem();
    stop();
    system.setSystemDark(true);
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("a storage that throws does not break apply()", () => {
    stubSystemDark(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => apply()).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("a storage that throws does not break setChoice()", () => {
    stubSystemDark(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => setChoice("dark")).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
