import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../copy";
import { orderRows } from "../mock/sampleData";
import { gsap } from "../motion";
import { Hero } from "./Hero";

// Shaped like a MediaQueryList: GSAP subscribes to changes through addEventListener.
function stubMatchMedia(matches: boolean) {
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("Hero (reduced-motion path)", () => {
  it("renders the section on the dark tone with the hero id", () => {
    stubMatchMedia(true);
    const { container } = render(<Hero />);

    const section = container.querySelector("section");
    expect(section?.id).toBe("hero");
    expect(section?.getAttribute("data-tone")).toBe("dark");
  });

  it("puts both title lines in the h1 as text", () => {
    stubMatchMedia(true);
    render(<Hero />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toContain(copy.hero.titleLine1);
    expect(heading.textContent).toContain(copy.hero.titleLine2);
    expect(heading.textContent?.replace(/\s+/g, " ").trim()).toBe(
      `${copy.hero.titleLine1} ${copy.hero.titleLine2}`,
    );
  });

  it("leaves no inline opacity, visibility or transform on any hero element", () => {
    stubMatchMedia(true);
    const { container } = render(<Hero />);

    const elements = Array.from(container.querySelectorAll<HTMLElement>("*"));
    expect(elements.length).toBeGreaterThan(0);
    for (const el of elements) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.visibility, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
  });

  it("links the primary CTA to #demo with the demo copy", () => {
    stubMatchMedia(true);
    const { container } = render(<Hero />);

    const cta = container.querySelector('a[href="#demo"]');
    expect(cta).toBeTruthy();
    expect(cta?.textContent).toBe(copy.demoCta);
  });

  it("renders the Orders mockup with one row element per sample row", () => {
    stubMatchMedia(true);
    const { container } = render(<Hero />);

    expect(container.querySelectorAll('[data-anim="order-row"]')).toHaveLength(orderRows.length);
    expect(container.querySelector('[data-anim="order-preview"]')).toBeTruthy();
  });

  it("does not call gsap timeline or set when animation cannot run", () => {
    stubMatchMedia(true);
    const timeline = vi.spyOn(gsap, "timeline");
    const set = vi.spyOn(gsap, "set");
    render(<Hero />);

    expect(timeline).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
  });
});

describe("Hero (animated path)", () => {
  it("builds the entrance timeline and reverts its inline styles on unmount", () => {
    stubMatchMedia(false);
    const timeline = vi.spyOn(gsap, "timeline");
    const set = vi.spyOn(gsap, "set");
    const { container, unmount } = render(<Hero />);

    expect(set).toHaveBeenCalled();
    expect(timeline).toHaveBeenCalledTimes(1);
    const word = container.querySelector<HTMLElement>("h1 .w-hero-word");
    expect(word).toBeTruthy();
    expect(word?.style.transform).not.toBe("");

    unmount();
    expect(word?.style.transform).toBe("");
  });

  it("keeps all content visible when the timeline throws", () => {
    stubMatchMedia(false);
    vi.spyOn(gsap, "timeline").mockImplementation(() => {
      throw new Error("timeline failed");
    });
    const { container } = render(<Hero />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain(copy.hero.titleLine1);
    const hidden = Array.from(container.querySelectorAll<HTMLElement>("*")).filter(
      (el) => el.style.opacity !== "" || el.style.transform !== "",
    );
    expect(hidden.map((el) => el.className)).toEqual([]);
  });
});
