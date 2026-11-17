import { act, cleanup, fireEvent, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SPY_LOCK_MS, spyPick, useScrollSpy } from "./scrollSpy";

// A section element whose top edge is `top` px from the window's top (the only geometry the spy reads).
function section(name: string, top: number): HTMLElement {
  const el = document.createElement("div");
  el.id = "tab-" + name;
  el.getBoundingClientRect = () =>
    ({ top, bottom: top + 100, left: 0, right: 0, width: 0, height: 100, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
  el.scrollIntoView = vi.fn();
  document.body.appendChild(el);
  return el;
}

// Moves the sections to new tops (the page scrolled) and fires a scroll event.
function scrollTo(tops: Record<string, number>) {
  for (const [name, top] of Object.entries(tops)) {
    const el = document.getElementById("tab-" + name);
    if (el) el.getBoundingClientRect = () => ({ top }) as DOMRect;
  }
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
}

const IDS = ["work", "salary", "personal"];

describe("useScrollSpy", () => {
  beforeEach(() => {
    // The frame callback runs at once, so the throttled scroll handler can be checked in the same tick.
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true, writable: true });
    Object.defineProperty(document.documentElement, "scrollHeight", { value: 0, configurable: true });
  });

  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    history.replaceState(null, "", "/");
  });

  it("marks the section whose top has passed the 120 px line", () => {
    section("work", -400);
    section("salary", 60);
    section("personal", 600);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("salary");
  });

  it("marks the first section above the first line and keeps the last passed one below the rest", () => {
    section("work", 300);
    section("salary", 500);
    section("personal", 700);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("work");
  });

  it("at the page's bottom marks the last section even when the 120 px line alone would pick an earlier one", () => {
    // The 120 px rule alone gives "salary" (its top is past the line, "personal" is not). At the bottom, the last wins.
    window.scrollY = 500;
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    Object.defineProperty(document.documentElement, "scrollHeight", { value: 1300, configurable: true });
    section("work", -900);
    section("salary", 60);
    section("personal", 300);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("personal");
  });

  it("skips a section that is not on the page", () => {
    section("work", -300);
    section("personal", -10);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("personal");
  });

  it("follows the scroll position on each scroll event", () => {
    section("work", -300);
    section("salary", 500);
    section("personal", 900);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("work");
    scrollTo({ work: -800, salary: 40, personal: 900 });
    expect(result.current).toBe("salary");
  });

  it("a clicked section link scrolls to it, keeps the mark for the lock, then the spy takes over", () => {
    section("work", -300);
    section("salary", 500);
    section("personal", 900);
    const link = document.createElement("a");
    link.href = "#personal";
    document.body.appendChild(link);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);

    act(() => {
      fireEvent.click(link);
    });
    expect(result.current).toBe("personal");
    expect(window.location.hash).toBe("#personal");
    expect(document.getElementById("tab-personal")?.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });

    // While the lock holds, a scroll that would pick "work" changes nothing.
    scrollTo({ work: 100, salary: -700, personal: -20 });
    expect(result.current).toBe("personal");

    // After the lock, the spy follows the scroll again.
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now + SPY_LOCK_MS + 1);
    scrollTo({ work: 100, salary: -700, personal: -20 });
    expect(result.current).toBe("personal");
    scrollTo({ work: 100, salary: 50, personal: 900 });
    expect(result.current).toBe("salary");
  });
});

describe("spyPick", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("keeps the current name when no section is on the page", () => {
    expect(spyPick(IDS, "salary")).toBe("salary");
  });
});

describe("useScrollSpy observers and the mark setter", () => {
  let resizeCallbacks: ResizeObserverCallback[];
  let observed: Element[];

  beforeEach(() => {
    resizeCallbacks = [];
    observed = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
    class FakeResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        resizeCallbacks.push(cb);
      }
      observe(el: Element) {
        observed.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  });

  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("observes each section and re-marks when a section resizes", () => {
    section("work", -300);
    const salary = section("salary", 500);
    section("personal", 900);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("work");
    expect(observed.length).toBe(3);
    expect(observed).toContain(salary);

    // The salary body loads and the section grows: its top is now past the line.
    salary.getBoundingClientRect = () => ({ top: 40 }) as DOMRect;
    act(() => {
      resizeCallbacks[0]([], {} as ResizeObserver);
    });
    expect(result.current).toBe("salary");
  });

  it("the mark setter marks a section at once, with no scroll", () => {
    section("work", -300);
    section("salary", 500);
    section("personal", 900);
    const { result } = renderHook(() => useScrollSpy(IDS));
    act(() => {
      result.current[1]("personal");
    });
    expect(result.current[0]).toBe("personal");
  });

  it("marks a section that mounts after the effect ran", async () => {
    section("work", -300);
    const { result } = renderHook(() => useScrollSpy(IDS)[0]);
    expect(result.current).toBe("work");
    section("salary", 40);
    await waitFor(() => expect(result.current).toBe("salary"));
  });
});
