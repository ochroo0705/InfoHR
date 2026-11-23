import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "./copy";
import { Footer } from "./Footer";
import { TopBar } from "./TopBar";
import WelcomePage from "./WelcomePage";

afterEach(() => {
  cleanup();
});

// Collects every string leaf of an object tree, so the copy rules are checked on all of the text.
function allStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(allStrings);
  return [];
}

describe("welcome copy", () => {
  it("has exactly four showcase steps", () => {
    expect(copy.showcase.steps).toHaveLength(4);
    for (const step of copy.showcase.steps) {
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.text.length).toBeGreaterThan(0);
    }
  });

  it("never calls MACS XE4 old, legacy or replaced (XE4 rule)", () => {
    const strings = allStrings(copy);
    expect(strings.length).toBeGreaterThan(0);
    for (const text of strings) {
      expect(text).not.toMatch(/хуучин|old|legacy|outdated|replaced/i);
    }
  });
});

describe("Footer", () => {
  it("shows the phone and email from copy, with tel and mailto links", () => {
    render(<Footer />);

    expect(screen.getByText(copy.footer.company)).toBeTruthy();
    expect(screen.getByText(copy.footer.phone)).toBeTruthy();
    expect(screen.getByText(copy.footer.email)).toBeTruthy();
    expect(screen.getByText(copy.footer.hours)).toBeTruthy();
    expect(document.querySelector('a[href="mailto:contact@infosystems.mn"]')).toBeTruthy();
    expect(document.querySelector('a[href="tel:+97670126399"]')).toBeTruthy();
  });
});

describe("TopBar", () => {
  it("has a login link to /login and a demo link to #demo", () => {
    const { container } = render(<TopBar />);

    expect(screen.getByText(copy.brand)).toBeTruthy();
    const login = container.querySelector('a[href="/login"]');
    const demo = container.querySelector('a[href="#demo"]');
    expect(login?.textContent).toBe(copy.login);
    expect(demo?.textContent).toBe(copy.demoCta);
  });

  it("takes the nav label from copy, not from a literal in the component", () => {
    const { container } = render(<TopBar />);

    expect(container.querySelector("nav")?.getAttribute("aria-label")).toBe(copy.nav.label);
  });
});

describe("WelcomePage", () => {
  it("renders the top bar, the page main element and the footer", () => {
    const { container } = render(<WelcomePage />);

    expect(screen.getByTestId("welcome-page")).toBeTruthy();
    expect(container.querySelector('a[href="/login"]')).toBeTruthy();
    expect(screen.getByText(copy.footer.email)).toBeTruthy();
  });

  it("places the sections in order inside main: hero, showcase, more, fit, faq, demo", () => {
    render(<WelcomePage />);

    const main = screen.getByTestId("welcome-page");
    const ids = ["hero", "showcase", "more", "fit", "faq", "demo"];
    let previous: Element = main;
    for (const id of ids) {
      const section = document.getElementById(id);
      expect(section, `section #${id}`).not.toBeNull();
      expect(main.contains(section), `#${id} inside main`).toBe(true);
      // Each section must come after the one before it in document order.
      expect(previous.compareDocumentPosition(section!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      previous = section!;
    }
  });

  it("puts the top bar before main and the footer after main", () => {
    const { container } = render(<WelcomePage />);

    const main = screen.getByTestId("welcome-page");
    const topbar = container.querySelector("header.w-topbar")!;
    const footer = container.querySelector("footer.w-footer")!;
    expect(topbar.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(main.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(main.contains(topbar)).toBe(false);
    expect(main.contains(footer)).toBe(false);
  });

  it("sets document.title on mount and restores the previous title on unmount", () => {
    document.title = "Before";
    const { unmount } = render(<WelcomePage />);

    expect(document.title).toBe("MACS Human Capital");
    unmount();
    expect(document.title).toBe("Before");
  });

  it("has exactly one h1 on the page", () => {
    const { container } = render(<WelcomePage />);

    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });

  it("has a target for every in-page link", () => {
    const { container } = render(<WelcomePage />);

    const links = Array.from(container.querySelectorAll<HTMLAnchorElement>('a[href^="#"]'));
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      const id = link.getAttribute("href")!.slice(1);
      expect(document.getElementById(id), `target for ${link.getAttribute("href")}`).not.toBeNull();
    }
  });

  it("does not use the XE4 denylist words anywhere in the rendered text", () => {
    const { container } = render(<WelcomePage />);

    expect(container.textContent).not.toMatch(/хуучин|\bold\b|\blegacy\b|\boutdated\b|\breplaced\b/i);
  });
});

describe("WelcomePage with reduced motion", () => {
  function stubReducedMotion() {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }));
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders with no inline opacity 0 or visibility hidden, and no pin spacer", () => {
    stubReducedMotion();
    const { container } = render(<WelcomePage />);

    expect(container.querySelectorAll('[style*="opacity: 0"]')).toHaveLength(0);
    expect(container.querySelectorAll('[style*="visibility: hidden"]')).toHaveLength(0);
    expect(container.querySelector(".pin-spacer")).toBeNull();
  });
});
