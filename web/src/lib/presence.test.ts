import { act, cleanup, render, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Presence, usePresence, type PresenceState } from "./presence";

// Ports the createLeave cases of web/legacy-specs/motion.test.ts (hrLeave) to usePresence.

function setReducedMotion(on: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: on && query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

function setup(initialOpen = true, opts?: { fallbackMs?: number }) {
  return renderHook(({ open }: { open: boolean }) => usePresence(open, opts), {
    initialProps: { open: initialOpen },
  });
}

function attach(current: { current: PresenceState }): HTMLElement {
  const el = document.createElement("div");
  act(() => current.current.ref(el));
  return el;
}

function animationEnd(target: EventTarget) {
  act(() => {
    target.dispatchEvent(new Event("animationend", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setReducedMotion(false);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("usePresence", () => {
  it("leaves, then is removed on the element's animationend", () => {
    const { result, rerender } = setup(true);
    const el = attach(result);
    expect(result.current.mounted).toBe(true);
    expect(result.current.leaving).toBe(false);

    rerender({ open: false });
    expect(result.current.leaving).toBe(true);
    expect(result.current.mounted).toBe(true);

    animationEnd(el);
    expect(result.current.mounted).toBe(false);
    expect(result.current.leaving).toBe(false);
  });

  it("is removed by the 250 ms fallback when no animation event fires", () => {
    const { result, rerender } = setup(true);
    attach(result);
    rerender({ open: false });

    act(() => vi.advanceTimersByTime(249));
    expect(result.current.mounted).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.mounted).toBe(false);
    expect(result.current.leaving).toBe(false);
  });

  it("uses a custom fallbackMs when given", () => {
    const { result, rerender } = setup(true, { fallbackMs: 100 });
    attach(result);
    rerender({ open: false });

    act(() => vi.advanceTimersByTime(100));
    expect(result.current.mounted).toBe(false);
  });

  it("reopening during the exit cancels it: still mounted, timer cleared", () => {
    const { result, rerender } = setup(true);
    const el = attach(result);
    rerender({ open: false });
    expect(result.current.leaving).toBe(true);

    rerender({ open: true });
    expect(result.current.leaving).toBe(false);
    expect(result.current.mounted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);

    act(() => vi.advanceTimersByTime(1000));
    animationEnd(el);
    expect(result.current.mounted).toBe(true);
  });

  it("ignores a child's animationend, which bubbles up to the element", () => {
    const { result, rerender } = setup(true);
    const el = attach(result);
    const child = document.createElement("span");
    el.appendChild(child);
    rerender({ open: false });

    animationEnd(child);
    expect(result.current.leaving).toBe(true);
    expect(result.current.mounted).toBe(true);
    expect(vi.getTimerCount()).toBe(1);

    animationEnd(el);
    expect(result.current.mounted).toBe(false);
  });

  it("is removed at once on close under reduced motion", () => {
    setReducedMotion(true);
    const { result, rerender } = setup(true);
    attach(result);
    rerender({ open: false });

    expect(result.current.mounted).toBe(false);
    expect(result.current.leaving).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("is not mounted when it starts closed, and mounts when opened", () => {
    const { result, rerender } = setup(false);
    expect(result.current.mounted).toBe(false);
    expect(result.current.leaving).toBe(false);

    rerender({ open: true });
    expect(result.current.mounted).toBe(true);
    expect(result.current.leaving).toBe(false);
  });
});

describe("Presence", () => {
  it("renders the exit state through the render prop and removes the element on animationend", () => {
    const view = (open: boolean) =>
      createElement(Presence, {
        open,
        children: (s: PresenceState) =>
          s.mounted
            ? createElement("div", {
                "data-testid": "pop",
                ref: s.ref,
                "data-leaving": s.leaving ? "" : undefined,
                inert: s.leaving,
              })
            : null,
      });

    const { rerender, getByTestId, queryByTestId } = render(view(true));
    const el = getByTestId("pop");
    expect(el.hasAttribute("data-leaving")).toBe(false);

    rerender(view(false));
    expect(getByTestId("pop").hasAttribute("data-leaving")).toBe(true);
    expect(getByTestId("pop").hasAttribute("inert")).toBe(true);

    animationEnd(el);
    expect(queryByTestId("pop")).toBeNull();
  });
});
