import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../copy";
import { ScrollTrigger, gsap } from "../motion";
import { More } from "./More";

// Silence jsdom's "Window's scrollTo() is not implemented" noise. ScrollTrigger scrolls on refresh; jsdom cannot.
vi.hoisted(() => {
  window.scrollTo = () => {};
});

const REDUCE = "(prefers-reduced-motion: reduce)";

// The clauses currently true. A query matches when every "and" clause is in this list.
// Shaped like a MediaQueryList so GSAP's own subscriptions work.
function stubMatchMedia(clauses: string[]) {
  const stub = (query: string) => ({
    get matches() {
      return query.split(" and ").every((clause) => clauses.includes(clause));
    },
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  });
  vi.stubGlobal("matchMedia", vi.fn(stub));
}

function sectionOf(container: HTMLElement): HTMLElement {
  const section = container.querySelector<HTMLElement>("section");
  if (!section) {
    throw new Error("no section rendered");
  }
  return section;
}

// Every element under the section, including the section itself.
function sectionElements(container: HTMLElement): HTMLElement[] {
  const section = sectionOf(container);
  return [section, ...Array.from(section.querySelectorAll<HTMLElement>("*"))];
}

function cardsOf(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>("[data-more-card]"));
}

afterEach(() => {
  cleanup();
  for (const trigger of ScrollTrigger.getAll()) {
    trigger.kill(true);
  }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("More (reduced-motion path)", () => {
  it("renders the light section with the more id", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<More />);

    const section = sectionOf(container);
    expect(section.id).toBe("more");
    expect(section.getAttribute("data-tone")).toBe("light");
  });

  it("shows the section title as a heading", () => {
    stubMatchMedia([REDUCE]);
    render(<More />);

    expect(screen.getByRole("heading", { level: 2, name: copy.more.title })).toBeTruthy();
  });

  it("renders one card per copy.more.cards entry, with its title and text", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<More />);

    const cards = cardsOf(container);
    expect(cards).toHaveLength(copy.more.cards.length);
    cards.forEach((card, index) => {
      const entry = copy.more.cards[index];
      expect(card.querySelector("h3")?.textContent).toBe(entry.title);
      expect(card.textContent).toContain(entry.text);
    });
  });

  it("leaves every card visible with no inline opacity, visibility or transform", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<More />);

    for (const el of sectionElements(container)) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.visibility, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
  });

  it("does not build a tween or a ScrollTrigger when animation cannot run", () => {
    stubMatchMedia([REDUCE]);
    const fromTo = vi.spyOn(gsap, "fromTo");
    const set = vi.spyOn(gsap, "set");
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<More />);

    expect(fromTo).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });
});

describe("More (animated path)", () => {
  it("creates a once-only ScrollTrigger for the card reveal", () => {
    stubMatchMedia([]);
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<More />);

    expect(create).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ once: true }));
  });

  it("hides the cards from JavaScript only after the trigger exists", () => {
    stubMatchMedia([]);
    const create = vi.spyOn(ScrollTrigger, "create");
    const set = vi.spyOn(gsap, "set");
    const { container } = render(<More />);

    expect(create).toHaveBeenCalled();
    // The hidden-state call on the card targets must come after the trigger was created.
    const hideIndex = set.mock.calls.findIndex(
      ([target]) => Array.isArray(target) && target.length === copy.more.cards.length,
    );
    expect(hideIndex).toBeGreaterThanOrEqual(0);
    expect(set.mock.invocationCallOrder[hideIndex]).toBeGreaterThan(create.mock.invocationCallOrder[0]);
    for (const card of cardsOf(container)) {
      expect(card.style.opacity).toBe("0");
    }
  });

  it("keeps every card visible when gsap.set throws", () => {
    stubMatchMedia([]);
    vi.spyOn(gsap, "set").mockImplementation(() => {
      throw new Error("set failed");
    });
    const { container } = render(<More />);

    expect(cardsOf(container)).toHaveLength(copy.more.cards.length);
    for (const el of sectionElements(container)) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
  });

  it("keeps every card visible when ScrollTrigger.create throws", () => {
    stubMatchMedia([]);
    vi.spyOn(ScrollTrigger, "create").mockImplementation(() => {
      throw new Error("create failed");
    });
    const set = vi.spyOn(gsap, "set");
    const { container } = render(<More />);

    expect(cardsOf(container)).toHaveLength(copy.more.cards.length);
    for (const el of sectionElements(container)) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
    // The hidden starting states come only after the trigger exists, so none were set.
    expect(set).not.toHaveBeenCalled();
    expect(ScrollTrigger.getAll()).toHaveLength(0);
  });

  it("leaves no inline hidden style after unmount", () => {
    stubMatchMedia([]);
    const { container, unmount } = render(<More />);
    const elements = sectionElements(container);

    unmount();

    for (const el of elements) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
    expect(ScrollTrigger.getAll()).toHaveLength(0);
  });
});
