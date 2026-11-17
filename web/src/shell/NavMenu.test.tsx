import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NavMenu, NavMenuProvider, type NavGroupData } from "./NavMenu";
import { NavIcon } from "./NavIcon";

// Hover is on only when the (hover: hover) and (pointer: fine) query matches, as with a mouse.
function stubHover(hover: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: hover && query.includes("hover"),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const A: NavGroupData = {
  key: "a",
  label: "Ажил",
  active: false,
  badge: 0,
  items: [
    { label: "Хэрэглэгч", url: "/users/", active: false, badge: 0, icon: "user", hint: "Нэвтрэх эрх", compact: false, section: "" },
    { label: "Тайлан", url: "/reports/", active: false, badge: 0, icon: "chart", hint: "", compact: true, section: "Бусад" },
  ],
};

const B: NavGroupData = {
  key: "b",
  label: "Бүртгэл",
  active: false,
  badge: 0,
  items: [
    { label: "Ажилтан", url: "/employees/", active: false, badge: 0, icon: "people", hint: "", compact: false, section: "" },
    { label: "Гэрээ", url: "/contracts/", active: false, badge: 0, icon: "order", hint: "", compact: true, section: "" },
  ],
};

function renderMenus(groups: NavGroupData[]) {
  function Harness() {
    const strip = useRef<HTMLDivElement>(null);
    return (
      <MemoryRouter>
        <NavMenuProvider stripRef={strip}>
          <div ref={strip}>
            {groups.map((g) => (
              <NavMenu key={g.key} group={g} />
            ))}
          </div>
        </NavMenuProvider>
      </MemoryRouter>
    );
  }
  return render(<Harness />);
}

function rootOf(label: string): HTMLElement {
  const trigger = screen.getByRole("button", { name: new RegExp(label) });
  return trigger.closest("[data-nav-menu]") as HTMLElement;
}

function panelOf(label: string): HTMLElement | null {
  return rootOf(label).querySelector("[data-nav-panel]");
}

describe("NavMenu", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("with a mouse, hover opens the menu after 60 ms and not at 59 ms", () => {
    stubHover(true);
    renderMenus([A]);
    fireEvent.mouseEnter(rootOf("Ажил"));

    act(() => {
      vi.advanceTimersByTime(59);
    });
    expect(panelOf("Ажил")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(panelOf("Ажил")).not.toBeNull();
    expect(screen.getByText("Хэрэглэгч")).toBeTruthy();
  });

  it("leaving with a mouse closes the menu 200 ms later, through the exit", () => {
    stubHover(true);
    renderMenus([A]);
    fireEvent.mouseEnter(rootOf("Ажил"));
    act(() => {
      vi.advanceTimersByTime(60);
    });

    fireEvent.mouseLeave(rootOf("Ажил"));
    act(() => {
      vi.advanceTimersByTime(199);
    });
    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);

    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(panelOf("Ажил")).toBeNull();
  });

  it("a click toggles the menu through its exit", () => {
    stubHover(false);
    renderMenus([A]);
    const trigger = screen.getByRole("button", { name: /Ажил/ });

    fireEvent.click(trigger);
    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(trigger);
    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
  });

  it("opening a second menu closes the first", () => {
    stubHover(false);
    renderMenus([A, B]);

    fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));
    fireEvent.click(screen.getByRole("button", { name: /Бүртгэл/ }));

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
    expect(panelOf("Бүртгэл")?.hasAttribute("data-leaving")).toBe(false);
  });

  it("Escape closes the open menu and gives focus back to its label", () => {
    stubHover(false);
    renderMenus([A]);
    const trigger = screen.getByRole("button", { name: /Ажил/ });
    fireEvent.click(trigger);

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("a mouse click on a menu the hover opened keeps it open (nav.js: e.detail > 0)", () => {
    stubHover(true);
    renderMenus([A]);
    const trigger = screen.getByRole("button", { name: /Ажил/ });
    fireEvent.mouseEnter(rootOf("Ажил"));
    act(() => {
      vi.advanceTimersByTime(60);
    });

    fireEvent.click(trigger, { detail: 1 });

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("an outside click closes the open menu", () => {
    stubHover(false);
    renderMenus([A]);
    fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));
    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(false);

    fireEvent.click(document.body);

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
  });

  it("scrolling the strip closes the open menu", () => {
    stubHover(false);
    renderMenus([A]);
    fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));
    const strip = rootOf("Ажил").parentElement as HTMLElement;

    fireEvent.scroll(strip);

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
  });

  it("a window resize closes the open menu", () => {
    stubHover(false);
    renderMenus([A]);
    fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));

    fireEvent(window, new Event("resize"));

    expect(panelOf("Ажил")?.hasAttribute("data-leaving")).toBe(true);
  });

  it("moves a strip panel left when it would run past the window's right edge", () => {
    stubHover(false);
    const panelWidth = 288;
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const isPanel = this.hasAttribute("data-nav-panel");
      return {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        bottom: 0,
        width: isPanel ? panelWidth : 0,
        height: 0,
        right: isPanel ? window.innerWidth + 200 : 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
    try {
      renderMenus([A]);
      fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));

      const panel = panelOf("Ажил") as HTMLElement;
      expect(panel.style.left).toBe(`${window.innerWidth - panelWidth - 8}px`);
    } finally {
      spy.mockRestore();
    }
  });

  it("Escape with no menu open does nothing", () => {
    stubHover(false);
    renderMenus([A]);
    const trigger = screen.getByRole("button", { name: /Ажил/ });
    trigger.focus();

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(panelOf("Ажил")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("renders section headings, compact rows and icon rows with a hint", () => {
    stubHover(false);
    renderMenus([A]);
    fireEvent.click(screen.getByRole("button", { name: /Ажил/ }));

    expect(screen.getByText("Бусад")).toBeTruthy();
    expect(screen.getByText("Нэвтрэх эрх")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Тайлан" }).className).toContain("text-sm");
  });
});

describe("NavIcon", () => {
  it.each([
    ["people", "bg-violet-100"],
    ["list", "bg-violet-100"],
    ["user", "bg-violet-100"],
    ["order", "bg-amber-100"],
    ["inbox", "bg-amber-100"],
    ["calendar", "bg-sky-100"],
    ["chart", "bg-emerald-100"],
    ["gear", "bg-slate-100"],
    ["page", "bg-slate-100"],
  ])("kind %s renders its tile colour %s", (kind, tile) => {
    const { container } = render(<NavIcon kind={kind} />);
    const tileEl = container.querySelector("span");
    expect(tileEl?.className).toContain(tile);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
});
