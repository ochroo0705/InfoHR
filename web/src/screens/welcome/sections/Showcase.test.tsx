import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copy } from "../copy";
import { ScrollTrigger, gsap } from "../motion";
import { Showcase } from "./Showcase";

// Silence jsdom's "Window's scrollTo() is not implemented" noise. ScrollTrigger scrolls on refresh; jsdom cannot.
// Runs before gsap is loaded through the imports above is evaluated, so GSAP captures the no-op.
vi.hoisted(() => {
  window.scrollTo = () => {};
});

const REDUCE = "(prefers-reduced-motion: reduce)";
const NO_PREFERENCE = "(prefers-reduced-motion: no-preference)";
const DESKTOP = "(min-width: 768px)";
const TALL = "(min-height: 640px)";
const PHONE = "(max-width: 767.98px)";
const PINNED_QUERY = "(min-width: 768px) and (min-height: 640px) and (prefers-reduced-motion: no-preference)";
const PINNED_CLAUSES = [NO_PREFERENCE, DESKTOP, TALL];

// The clauses currently true. A query matches when every "and" clause is in this list.
let trueClauses: string[] = [];
// Change listeners GSAP registers on each MediaQueryList (addListener or addEventListener).
let listeners: Array<() => void> = [];

// Shaped like a MediaQueryList. `matches` is live, so GSAP's re-check after a change sees the new answer.
function stubMatchMedia(clauses: string[]) {
  trueClauses = clauses;
  listeners = [];
  const stub = (query: string) => ({
    get matches() {
      return query.split(" and ").every((clause) => trueClauses.includes(clause));
    },
    media: query,
    addEventListener: (_type: string, fn: () => void) => {
      listeners.push(fn);
    },
    removeEventListener: () => {},
    addListener: (fn: () => void) => {
      listeners.push(fn);
    },
    removeListener: () => {},
  });
  vi.stubGlobal("matchMedia", vi.fn(stub));
}

// Simulates the viewport or the reduced-motion setting changing, then tells every listener.
function changeMedia(clauses: string[]) {
  trueClauses = clauses;
  for (const fn of [...listeners]) {
    fn();
  }
}

// Every element under the section, including the section itself.
function sectionElements(container: HTMLElement): HTMLElement[] {
  const section = container.querySelector<HTMLElement>("section");
  return section ? [section, ...Array.from(section.querySelectorAll<HTMLElement>("*"))] : [];
}

function expectAllVisible(container: HTMLElement) {
  for (const el of sectionElements(container)) {
    expect(el.style.opacity, el.className).toBe("");
    expect(el.style.visibility, el.className).toBe("");
    expect(el.style.transform, el.className).toBe("");
  }
  for (const article of Array.from(container.querySelectorAll("article"))) {
    expect(article.hasAttribute("aria-hidden")).toBe(false);
  }
}

function sectionOf(container: HTMLElement): HTMLElement {
  const section = container.querySelector<HTMLElement>("section");
  if (!section) {
    throw new Error("no section rendered");
  }
  return section;
}

// The trigger options the component passed to ScrollTrigger.create, in call order.
interface TriggerVars {
  trigger?: unknown;
  start?: string;
  end?: string;
  scrub?: number;
  pin?: boolean;
  pinSpacing?: boolean;
  anticipatePin?: number;
  once?: boolean;
  onEnter?: () => void;
  onUpdate?: (self: { progress: number }) => void;
  snap?: { snapTo?: number | number[] };
}

// The scrubbed trigger: the one that carries onUpdate (the entrance trigger has onEnter instead).
function scrubbedVars(create: { mock: { calls: unknown[][] } }): TriggerVars | undefined {
  return triggerVars(create).find((vars) => typeof vars.onUpdate === "function");
}

function triggerVars(create: { mock: { calls: unknown[][] } }): TriggerVars[] {
  return create.mock.calls.map(([vars]) => vars as TriggerVars);
}

// Every timeline the component built, in creation order: the scrubbed one first, then the four step timelines.
function timelinesCreated(timeline: { mock: { results: { value: unknown }[] } }): gsap.core.Timeline[] {
  return timeline.mock.results.map((result) => result.value as gsap.core.Timeline);
}

function opacityOf(el: HTMLElement): number {
  return Number(gsap.getProperty(el, "opacity"));
}

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  // jsdom has no layout, so the track would measure 0 high. The pinned scroll distance is 250% of the viewport, which
  // needs a track three and a half viewports tall. Only the track is stubbed; every other element keeps jsdom's answer.
  const realRect = Element.prototype.getBoundingClientRect;
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.classList.contains("w-showcase-track")) {
      const height = window.innerHeight * 3.5;
      return { x: 0, y: 0, top: 0, left: 0, right: 0, width: 0, height, bottom: height, toJSON() {} } as DOMRect;
    }
    return realRect.call(this);
  });
});

afterEach(() => {
  cleanup();
  for (const trigger of ScrollTrigger.getAll()) {
    trigger.kill(true);
  }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as { matchMedia?: unknown }).matchMedia;
  listeners = [];
});

describe("Showcase (static path)", () => {
  it("renders the dark section with the showcase id", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    const section = container.querySelector("section");
    expect(section?.id).toBe("showcase");
    expect(section?.getAttribute("data-tone")).toBe("dark");
  });

  it("renders four articles in the order orders, leave, today, assistant", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll("article"));
    expect(articles.map((article) => article.getAttribute("data-step"))).toEqual([
      "orders",
      "leave",
      "today",
      "assistant",
    ]);
  });

  it("pairs each data-step with the caption at the same position in copy.showcase.steps", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll("article"));
    expect(articles).toHaveLength(copy.showcase.steps.length);
    const keys = ["orders", "leave", "today", "assistant"];
    articles.forEach((article, index) => {
      expect(article.getAttribute("data-step")).toBe(keys[index]);
      expect(article.querySelector("h2")?.textContent).toBe(copy.showcase.steps[index].title);
      expect(article.textContent).toContain(copy.showcase.steps[index].text);
    });
  });

  it("keeps every caption outside the device frame, so assistive technology reads it", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    for (const heading of Array.from(container.querySelectorAll("article h2"))) {
      expect(heading.closest('[role="img"]')).toBeNull();
    }
    // Each mock is still one image with a label.
    expect(container.querySelectorAll('[role="img"]')).toHaveLength(copy.showcase.steps.length);
  });

  it("leaves every article visible with no inline opacity, visibility or transform", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    expect(sectionElements(container).length).toBeGreaterThan(0);
    expectAllVisible(container);
  });

  it("has no pin spacer and no pinned class", () => {
    stubMatchMedia([REDUCE]);
    const { container } = render(<Showcase />);

    expect(container.querySelector(".pin-spacer")).toBeNull();
    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
  });

  it("does not build a timeline or a ScrollTrigger when animation cannot run", () => {
    stubMatchMedia([REDUCE]);
    const timeline = vi.spyOn(gsap, "timeline");
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<Showcase />);

    expect(timeline).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
  });
});

describe("Showcase (pinned path, 768px and up with a tall viewport)", () => {
  it("asks matchMedia for the full pinned query, including the minimum height", () => {
    stubMatchMedia(PINNED_CLAUSES);
    render(<Showcase />);

    expect(window.matchMedia).toHaveBeenCalledWith(PINNED_QUERY);
  });

  it("drives the stage from the track with a scrubbed trigger, without a pin, and adds the pinned class", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    const scrubbed = scrubbedVars(create);
    // Fields are checked one by one: a failed whole-object match would print the track element.
    expect(scrubbed?.trigger === container.querySelector(".w-showcase-track")).toBe(true);
    expect(scrubbed?.start).toBe("top top");
    expect(scrubbed?.end).toBe("bottom bottom");
    expect(scrubbed?.scrub).toBe(1);
    // ScrollTrigger may fill in its own defaults for these, so the check is that none of them is switched on.
    expect(scrubbed?.pin).toBeFalsy();
    expect(scrubbed?.pinSpacing).toBeFalsy();
    expect(scrubbed?.anticipatePin).toBeFalsy();
    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(true);
    expect(container.querySelector(".pin-spacer")).toBeNull();
  });

  it("adds the pinned class only after every trigger exists", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const realCreate = ScrollTrigger.create.bind(ScrollTrigger);
    const classSeen: boolean[] = [];
    vi.spyOn(ScrollTrigger, "create").mockImplementation(((vars: unknown) => {
      classSeen.push(document.querySelector("#showcase")?.classList.contains("w-showcase--pinned") ?? true);
      return realCreate(vars as never);
    }) as never);
    render(<Showcase />);

    expect(classSeen).toEqual([false, false]);
    expect(document.querySelector("#showcase")?.classList.contains("w-showcase--pinned")).toBe(true);
  });

  it("builds a timeline of exactly four units, one per step", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    render(<Showcase />);

    const built = timeline.mock.results[0]?.value as gsap.core.Timeline | undefined;
    expect(built).toBeDefined();
    expect(built?.duration()).toBe(4);
  });

  it("does not pin when the viewport is shorter than 640px", () => {
    stubMatchMedia([NO_PREFERENCE, DESKTOP]);
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    expect(create).not.toHaveBeenCalledWith(expect.objectContaining({ pin: true }));
    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    expectAllVisible(container);
  });

  it("removes the pinned class, the pin spacer and the section's pin styles on unmount", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container, unmount } = render(<Showcase />);
    const section = sectionOf(container);
    expect(section.classList.contains("w-showcase--pinned")).toBe(true);
    expect(ScrollTrigger.getAll().length).toBeGreaterThan(0);

    unmount();

    expect(section.classList.contains("w-showcase--pinned")).toBe(false);
    expect(ScrollTrigger.getAll()).toHaveLength(0);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    expect(section.style.position).toBe("");
    expect(section.style.transform).toBe("");
  });

  it("tears down cleanly when the viewport crosses below 768px", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container } = render(<Showcase />);
    const section = sectionOf(container);
    expect(section.classList.contains("w-showcase--pinned")).toBe(true);

    changeMedia([NO_PREFERENCE, PHONE]);

    expect(section.classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    for (const article of Array.from(container.querySelectorAll("article"))) {
      expect(article.hasAttribute("aria-hidden")).toBe(false);
    }
    // The phone reveal takes over: each article is hidden from JavaScript until it enters the viewport.
    expect(container.querySelectorAll<HTMLElement>("article")[1]?.style.opacity).toBe("0");
  });

  it("tears down cleanly when reduced motion is turned on", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container } = render(<Showcase />);
    const section = sectionOf(container);
    expect(section.classList.contains("w-showcase--pinned")).toBe(true);

    changeMedia([REDUCE, DESKTOP, TALL]);

    expect(section.classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    expectAllVisible(container);
  });

  it("keeps every article visible when the timeline throws", () => {
    stubMatchMedia(PINNED_CLAUSES);
    vi.spyOn(gsap, "timeline").mockImplementation(() => {
      throw new Error("timeline failed");
    });
    const { container } = render(<Showcase />);

    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
    expectAllVisible(container);
    expect(container.querySelectorAll("article h2")).toHaveLength(copy.showcase.steps.length);
  });

  it("keeps every article visible, with no class and no aria-hidden, when ScrollTrigger.create throws", () => {
    stubMatchMedia(PINNED_CLAUSES);
    vi.spyOn(ScrollTrigger, "create").mockImplementation(() => {
      throw new Error("create failed");
    });
    const set = vi.spyOn(gsap, "set");
    const { container } = render(<Showcase />);

    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    expectAllVisible(container);
    // The hidden starting states come only after the trigger exists, so none were set.
    expect(set).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ y: 24 }));
  });

  it("restores visibility, with no pin spacer left, when gsap.set throws after the trigger was created", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const create = vi.spyOn(ScrollTrigger, "create");
    const realSet = gsap.set.bind(gsap);
    // Throws only on the hidden-start call (an array of targets with y: 24), which runs after create.
    vi.spyOn(gsap, "set").mockImplementation(((target: unknown, vars: unknown) => {
      if (Array.isArray(target) && (vars as { y?: number } | undefined)?.y === 24) {
        throw new Error("set failed");
      }
      return realSet(target as gsap.TweenTarget, vars as gsap.TweenVars);
    }) as typeof gsap.set);
    const { container } = render(<Showcase />);

    // The pin trigger and the entrance trigger were both created before the hidden states failed.
    expect(triggerVars(create).filter((vars) => typeof vars.onUpdate === "function")).toHaveLength(1);
    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
    expect(ScrollTrigger.getAll()).toHaveLength(0);
    expectAllVisible(container);
  });

  it("never creates a pin spacer, and removes the pinned class when the pinned viewport is left", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container } = render(<Showcase />);
    const section = sectionOf(container);
    expect(container.querySelector(".pin-spacer")).toBeNull();

    changeMedia([REDUCE, DESKTOP, TALL]);

    expect(container.querySelector(".pin-spacer")).toBeNull();
    expect(section.classList.contains("w-showcase--pinned")).toBe(false);
    expect(section.style.position).toBe("");
  });

  it("never leaves a pin spacer in the document, across breakpoints and on unmount", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { unmount } = render(<Showcase />);
    expect(document.querySelector(".pin-spacer")).toBeNull();

    changeMedia([NO_PREFERENCE, PHONE]);
    expect(document.querySelector(".pin-spacer")).toBeNull();

    changeMedia(PINNED_CLAUSES);
    expect(document.querySelector(".pin-spacer")).toBeNull();

    unmount();
    expect(document.querySelector(".pin-spacer")).toBeNull();
  });
});

describe("Showcase (pinned choreography)", () => {
  // Properties a scrubbed crossfade may animate. Anything else on a tween is a bug in this choreography.
  const ALLOWED_PROPS = new Set(["opacity", "y"]);
  // Tween settings that are not animated properties. GSAP adds `parent` when a tween joins a timeline.
  const NON_PROP_KEYS = new Set([
    "duration",
    "ease",
    "immediateRender",
    "delay",
    "startAt",
    "stagger",
    "overwrite",
    "parent",
  ]);

  it("snaps the pin to the middle of each step's plateau, and to both ends", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<Showcase />);

    const pin = scrubbedVars(create);
    expect(pin?.snap).toEqual(expect.objectContaining({ snapTo: [0, 0.125, 0.375, 0.625, 0.875, 1] }));
  });

  it("builds a scrubbed timeline of exactly four units whose tweens animate only opacity and y on the articles", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const [main] = timelinesCreated(timeline);
    expect(main.duration()).toBe(4);
    const tweens = main.getChildren(false, true, false) as gsap.core.Tween[];
    expect(tweens.length).toBeGreaterThan(0);
    for (const tween of tweens) {
      for (const target of tween.targets()) {
        expect(articles).toContain(target);
      }
      const vars = tween.vars as Record<string, unknown>;
      const startAt = (vars.startAt ?? {}) as Record<string, unknown>;
      const props = [...Object.keys(vars), ...Object.keys(startAt)].filter((key) => !NON_PROP_KEYS.has(key));
      for (const prop of props) {
        expect(ALLOWED_PROPS.has(prop), `unexpected property ${prop}`).toBe(true);
      }
    }
  });

  // Samples the pinned timeline the way a scroll does, and reads what the browser would paint: the inline opacity.
  function sampledOpacities(main: gsap.core.Timeline, articles: HTMLElement[], points: number[]) {
    return points.map((p) => {
      main.progress(p);
      return { p, opacities: articles.map((article) => Number(article.style.opacity)) };
    });
  }

  const SAMPLES = Array.from({ length: 101 }, (_, i) => i / 100);
  const RESTS = [0, 0.125, 0.375, 0.625, 0.875, 1];

  it("shows at most one article above 0.15 opacity at each of 101 sampled positions", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const [main] = timelinesCreated(timeline);
    for (const { p, opacities } of sampledOpacities(main, articles, SAMPLES)) {
      const above = opacities.filter((opacity) => opacity > 0.15).length;
      expect(above, `articles above 0.15 at progress ${p}`).toBeLessThanOrEqual(1);
    }
  });

  it("keeps the empty stage to at most 8% of the sampled positions (no article above 0.15)", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const [main] = timelinesCreated(timeline);
    const empty = sampledOpacities(main, articles, SAMPLES).filter(({ opacities }) =>
      opacities.every((opacity) => opacity <= 0.15),
    );
    expect(empty.length / SAMPLES.length).toBeLessThanOrEqual(0.08);
  });

  it("shows exactly one full step at each resting point, and the others at or below 0.1", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const [main] = timelinesCreated(timeline);
    for (const { p, opacities } of sampledOpacities(main, articles, RESTS)) {
      const full = opacities.filter((opacity) => opacity > 0.9);
      expect(full, `full steps at resting point ${p}`).toHaveLength(1);
      opacities.forEach((opacity, index) => {
        if (opacity <= 0.9) {
          expect(opacity, `inactive step ${index} at resting point ${p}`).toBeLessThanOrEqual(0.1);
        }
      });
    }
    // At progress 0 the first step is the full one.
    main.progress(0);
    expect(Number(articles[0].style.opacity)).toBe(1);
  });

  it("starts with only the first step visible: the pin refresh does not bring the later steps back", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    expect(opacityOf(articles[0])).toBe(1);
    for (const article of articles.slice(1)) {
      expect(opacityOf(article)).toBe(0);
    }
  });

  it("plays the orders timeline once when the showcase first reaches the viewport", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const create = vi.spyOn(ScrollTrigger, "create");
    render(<Showcase />);

    const entry = triggerVars(create).find((vars) => typeof vars.onEnter === "function");
    expect(entry?.once).toBe(true);
    const [, orders] = timelinesCreated(timeline);
    // jsdom puts the section at the top of the page, so the entrance may already have fired on creation. Start from rest.
    orders.pause(0);

    entry?.onEnter?.();

    expect(orders.paused()).toBe(false);
  });

  it("moves the active step at each boundary: aria-hidden, the dot, and the new step's timeline", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const dots = Array.from(container.querySelectorAll<HTMLElement>(".w-showcase-dot"));
    const [, ...minis] = timelinesCreated(timeline);
    const pin = scrubbedVars(create);

    pin?.onUpdate?.({ progress: 0.4 });

    expect(articles[1].hasAttribute("aria-hidden")).toBe(false);
    expect(articles[0].getAttribute("aria-hidden")).toBe("true");
    expect(articles[2].getAttribute("aria-hidden")).toBe("true");
    expect(articles[3].getAttribute("aria-hidden")).toBe("true");
    expect(dots[1].classList.contains("is-active")).toBe(true);
    expect(dots[0].classList.contains("is-active")).toBe(false);
    expect(minis[1].paused()).toBe(false);
    expect(minis[0].paused()).toBe(true);
    expect(minis[0].progress()).toBe(0);

    pin?.onUpdate?.({ progress: 0.9 });

    expect(articles[3].hasAttribute("aria-hidden")).toBe(false);
    expect(articles[1].getAttribute("aria-hidden")).toBe("true");
    expect(dots[3].classList.contains("is-active")).toBe(true);
    expect(minis[3].paused()).toBe(false);
    expect(minis[1].paused()).toBe(true);
    expect(minis[1].progress()).toBe(0);
  });

  it("makes the step dots labelled buttons that scroll to the middle of a step's plateau", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const { container } = render(<Showcase />);
    const dots = Array.from(container.querySelectorAll<HTMLButtonElement>("button.w-showcase-dot"));
    const scrollTo = vi.mocked(window.scrollTo);

    expect(dots).toHaveLength(4);
    expect(dots.map((dot) => dot.getAttribute("aria-label"))).toEqual(copy.showcase.steps.map((step) => step.title));
    expect(dots[0].getAttribute("aria-current")).toBe("step");

    scrollTo.mockClear();
    fireEvent.click(dots[2]);

    expect(scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({ top: expect.any(Number) }));
  });
});

describe("Showcase (active step changes at the crossfade midpoints)", () => {
  it("changes the active step exactly at progress 0.25, 0.5 and 0.75", () => {
    stubMatchMedia(PINNED_CLAUSES);
    const timeline = vi.spyOn(gsap, "timeline");
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const dots = Array.from(container.querySelectorAll<HTMLElement>(".w-showcase-dot"));
    const [, ...minis] = timelinesCreated(timeline);
    const pin = scrubbedVars(create);
    const activeIndex = () => articles.findIndex((article) => !article.hasAttribute("aria-hidden"));

    // Each pair is progress just below and at the boundary, with the step expected at that progress.
    const cases: Array<[number, number]> = [
      [0.2499, 0],
      [0.25, 1],
      [0.4999, 1],
      [0.5, 2],
      [0.7499, 2],
      [0.75, 3],
    ];
    for (const [progress, expected] of cases) {
      pin?.onUpdate?.({ progress });
      expect(activeIndex(), `active step at progress ${progress}`).toBe(expected);
      expect(dots[expected].classList.contains("is-active"), `dot at progress ${progress}`).toBe(true);
      // Step 0 is started by the entrance trigger, which jsdom may have fired already; the later steps are played here.
      if (expected > 0) {
        expect(minis[expected].paused(), `timeline of step ${expected} at progress ${progress}`).toBe(false);
      }
    }
  });
});

describe("Showcase (phone reveal, below 768px)", () => {
  it("does not pin: no pinned class, no pin spacer, no pin trigger", () => {
    stubMatchMedia([NO_PREFERENCE, PHONE]);
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    expect(create).not.toHaveBeenCalledWith(expect.objectContaining({ pin: true }));
    expect(sectionOf(container).classList.contains("w-showcase--pinned")).toBe(false);
    expect(container.querySelector(".pin-spacer")).toBeNull();
  });

  it("creates one once-only reveal trigger per article and hides each article from JavaScript", () => {
    stubMatchMedia([NO_PREFERENCE, PHONE]);
    // In jsdom every element sits at offset 0, so a fired `once` trigger removes itself from getAll().
    // The create calls are the reliable record of what was set up.
    const create = vi.spyOn(ScrollTrigger, "create");
    const { container } = render(<Showcase />);

    const articles = Array.from(container.querySelectorAll<HTMLElement>("article"));
    const reveals = create.mock.calls.map(([vars]) => vars as { trigger: Element; once?: boolean });
    expect(reveals).toHaveLength(copy.showcase.steps.length);
    expect(reveals.every((vars) => vars.once === true)).toBe(true);
    expect(reveals.map((vars) => vars.trigger)).toEqual(articles);
    for (const article of articles) {
      expect(article.style.opacity).toBe("0");
    }
  });

  it("makes every article visible again on unmount", () => {
    stubMatchMedia([NO_PREFERENCE, PHONE]);
    const { container, unmount } = render(<Showcase />);

    unmount();

    expect(ScrollTrigger.getAll()).toHaveLength(0);
    for (const article of Array.from(container.querySelectorAll<HTMLElement>("article"))) {
      expect(article.style.opacity).toBe("");
      expect(article.style.transform).toBe("");
    }
  });
});
