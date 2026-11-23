import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../copy";
import { ScrollTrigger, gsap } from "../motion";
import { Proof } from "./Proof";

// Silence jsdom's "Window's scrollTo() is not implemented" noise. ScrollTrigger scrolls on refresh; jsdom cannot.
vi.hoisted(() => {
  window.scrollTo = () => {};
});

const REDUCE = "(prefers-reduced-motion: reduce)";
// Words the XE4 comparison must never use (see docs/UI_RULES.md §1).
// Word boundaries for the Latin words; \b does not work for Cyrillic, so хуучин stays a plain substring.
const XE4_DENYLIST = /хуучин|\bold\b|\blegacy\b|\boutdated\b|\breplaced\b/i;

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

function counterValue(container: HTMLElement): HTMLElement {
  const value = container.querySelector<HTMLElement>("[data-proof-value]");
  if (!value) {
    throw new Error("no counter value rendered");
  }
  return value;
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

describe("Proof (reduced-motion path)", () => {
  it("renders the dark section with the proof id", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Proof />);

    const section = sectionOf(container);
    expect(section.id).toBe("proof");
    expect(section.getAttribute("data-tone")).toBe("dark");
  });

  it("shows the final counter value 500 as the visible text", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Proof />);

    expect(counterValue(container).textContent).toBe("500");
  });

  it("puts the copy line on the page as text", () => {
    stubMatchMedia([REDUCE]);
    render(<Proof />);

    expect(screen.getByText(copy.proof.line)).toBeTruthy();
  });

  it("labels the counter with the copy counterLabel", () => {
    stubMatchMedia([REDUCE]);
    render(<Proof />);

    expect(screen.getByText(copy.proof.counterLabel)).toBeTruthy();
  });

  it("keeps the final 500 readable by assistive technology while the visible number animates", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Proof />);

    const hiddenFromAt = counterValue(container);
    expect(hiddenFromAt.getAttribute("aria-hidden")).toBe("true");
    const spoken = Array.from(container.querySelectorAll(".w-proof-sr")).map((el) => el.textContent);
    expect(spoken).toContain("500");
  });

  it("contains no word from the XE4 denylist", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Proof />);

    expect(sectionOf(container).textContent).not.toMatch(XE4_DENYLIST);
  });

  it("leaves no inline opacity, visibility or transform on any proof element", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Proof />);

    for (const el of sectionElements(container)) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.visibility, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
  });

  it("does not build a tween or a ScrollTrigger when animation cannot run", () => {
    stubMatchMedia([REDUCE]);
    const to = vi.spyOn(gsap, "to");
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<Proof />);

    expect(to).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });
});

describe("Proof (animated path)", () => {
  it("creates a once-only ScrollTrigger that plays the counter tween", () => {
    stubMatchMedia([]);
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<Proof />);

    expect(create).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ once: true }));
  });

  it("counts with a snapped tween from 5 to 500", () => {
    stubMatchMedia([]);
    const to = vi.spyOn(gsap, "to");
    render(<Proof />);

    expect(to).toHaveBeenCalledWith(
      expect.objectContaining({ value: 5 }),
      expect.objectContaining({ value: 500, snap: { value: 1 } }),
    );
  });

  it("keeps the final 500 when the tween throws", () => {
    stubMatchMedia([]);
    vi.spyOn(gsap, "to").mockImplementation(() => {
      throw new Error("tween failed");
    });
    const { container } = render(<Proof />);

    expect(counterValue(container).textContent).toBe("500");
    for (const el of sectionElements(container)) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
  });

  it("keeps the final 500 when ScrollTrigger.create throws", () => {
    stubMatchMedia([]);
    const create = vi.spyOn(ScrollTrigger, "create").mockImplementation(() => {
      throw new Error("create failed");
    });
    const { container } = render(<Proof />);

    // The throw was reached: the tween was built first, then create failed.
    expect(create).toHaveBeenCalledTimes(1);
    expect(counterValue(container).textContent).toBe("500");
    expect(ScrollTrigger.getAll()).toHaveLength(0);
  });

  it("shows 5 as the visible counter text once the trigger is created", () => {
    stubMatchMedia([]);
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Proof />);

    expect(create).toHaveBeenCalledTimes(1);
    expect(counterValue(container).textContent).toBe("5");
  });

  it("writes the rounded tween value into the visible counter on each update", () => {
    stubMatchMedia([]);
    const to = vi.spyOn(gsap, "to");
    const { container } = render(<Proof />);

    const [counter, vars] = to.mock.calls[0] as unknown as [
      { value: number },
      { onUpdate: () => void },
    ];
    counter.value = 123.4;
    vars.onUpdate();
    expect(counterValue(container).textContent).toBe("123");

    counter.value = 500;
    vars.onUpdate();
    expect(counterValue(container).textContent).toBe("500");
  });

  it("leaves no inline hidden style after unmount", () => {
    stubMatchMedia([]);
    const { container, unmount } = render(<Proof />);
    const elements = sectionElements(container);

    unmount();

    for (const el of elements) {
      expect(el.style.opacity, el.className).toBe("");
      expect(el.style.transform, el.className).toBe("");
    }
    expect(ScrollTrigger.getAll()).toHaveLength(0);
  });
});
