import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import { flushSync } from "react-dom";
import { TLink, useTransitionNavigate } from "./viewTransition";

// Spy on flushSync but keep its real behaviour.
vi.mock("react-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-dom")>();
  return { ...actual, flushSync: vi.fn((fn: () => void) => actual.flushSync(fn)) };
});

// The DOM lib types startViewTransition as always present; tests add and remove it, so they see it as optional.
type DocWithVT = { startViewTransition?: unknown };

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

function fakeTransition() {
  return {
    ready: { catch: vi.fn() },
    finished: { catch: vi.fn() },
    updateCallbackDone: { catch: vi.fn() },
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={["/"]}>{children}</MemoryRouter>;
}

function setup() {
  return renderHook(
    () => ({ go: useTransitionNavigate(), loc: useLocation() }),
    { wrapper },
  );
}

describe("viewTransition", () => {
  let originalMatchMedia: typeof window.matchMedia;

  beforeEach(() => {
    originalMatchMedia = window.matchMedia;
    setReducedMotion(false);
  });

  afterEach(() => {
    cleanup();
    vi.mocked(flushSync).mockClear();
    window.matchMedia = originalMatchMedia;
    delete (document as unknown as DocWithVT).startViewTransition;
  });

  it("calls navigate inside startViewTransition and swallows the three promises", () => {
    const transition = fakeTransition();
    const start = vi.fn((cb: () => void) => {
      cb();
      return transition;
    });
    (document as unknown as DocWithVT).startViewTransition = start;

    const { result } = setup();
    act(() => result.current.go("/reports"));

    expect(start).toHaveBeenCalledTimes(1);
    // The route is committed inside the callback (flushSync), so the new page is in the snapshot.
    expect(flushSync).toHaveBeenCalledTimes(1);
    expect(result.current.loc.pathname).toBe("/reports");
    expect(transition.ready.catch).toHaveBeenCalledTimes(1);
    expect(transition.finished.catch).toHaveBeenCalledTimes(1);
    expect(transition.updateCallbackDone.catch).toHaveBeenCalledTimes(1);
  });

  it("calls navigate directly when startViewTransition is missing", () => {
    const { result } = setup();

    act(() => result.current.go("/reports"));

    expect(result.current.loc.pathname).toBe("/reports");
  });

  it("calls navigate directly under reduced motion, even when the API exists", () => {
    const start = vi.fn();
    (document as unknown as DocWithVT).startViewTransition = start;
    setReducedMotion(true);

    const { result } = setup();
    act(() => result.current.go("/reports"));

    expect(start).not.toHaveBeenCalled();
    expect(result.current.loc.pathname).toBe("/reports");
  });

  it("TLink navigates through the transition on a plain click", () => {
    const transition = fakeTransition();
    const start = vi.fn((cb: () => void) => {
      cb();
      return transition;
    });
    (document as unknown as DocWithVT).startViewTransition = start;

    function Probe() {
      const loc = useLocation();
      return <p>at {loc.pathname}</p>;
    }
    render(
      <MemoryRouter initialEntries={["/"]}>
        <TLink to="/reports">Тайлан</TLink>
        <Probe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Тайлан" }));

    expect(start).toHaveBeenCalledTimes(1);
    expect(screen.getByText("at /reports")).toBeTruthy();
  });

  it("TLink leaves modifier clicks to the browser", () => {
    const start = vi.fn();
    (document as unknown as DocWithVT).startViewTransition = start;
    render(
      <MemoryRouter initialEntries={["/"]}>
        <TLink to="/reports">Тайлан</TLink>
      </MemoryRouter>,
    );

    // jsdom cannot navigate: stop its default action so the test log stays clean. Our handler runs before this.
    const stop = (event: Event) => event.preventDefault();
    window.addEventListener("click", stop);
    fireEvent.click(screen.getByRole("link", { name: "Тайлан" }), { ctrlKey: true });
    window.removeEventListener("click", stop);

    expect(start).not.toHaveBeenCalled();
  });
});
