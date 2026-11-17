import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readActivityOpen, writeActivityOpen } from "./activityStore";

// matchMedia is not in jsdom: each test sets the wide answer it needs, and the global is removed afterwards.
function setWide(wide: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: wide,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }),
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
  localStorage.clear();
});

describe("activityStore", () => {
  it("opening is kept only on a wide screen", () => {
    setWide(false);
    writeActivityOpen(true);
    expect(localStorage.getItem("hr.activityOpen")).toBeNull();

    setWide(true);
    writeActivityOpen(true);
    expect(localStorage.getItem("hr.activityOpen")).toBe("1");
  });

  it("closing is always kept (detail.html stores 0 on every close)", () => {
    setWide(false);
    writeActivityOpen(false);
    expect(localStorage.getItem("hr.activityOpen")).toBe("0");
  });

  it("a stored open state reopens the drawer only on a wide screen", () => {
    localStorage.setItem("hr.activityOpen", "1");
    setWide(false);
    expect(readActivityOpen()).toBe(false);
    setWide(true);
    expect(readActivityOpen()).toBe(true);
  });

  it("a stored closed state stays closed on a wide screen", () => {
    localStorage.setItem("hr.activityOpen", "0");
    setWide(true);
    expect(readActivityOpen()).toBe(false);
  });
});
