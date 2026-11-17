import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { NavMenuProvider } from "./NavMenu";
import { ThemeMenu } from "./ThemeMenu";

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

function renderThemeMenu() {
  return render(
    <MemoryRouter>
      <NavMenuProvider stripRef={createRef<HTMLElement>()}>
        <ThemeMenu />
      </NavMenuProvider>
    </MemoryRouter>,
  );
}

describe("ThemeMenu", () => {
  beforeEach(() => {
    stubHover(true);
  });

  afterEach(() => {
    cleanup();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("opens on hover, like the nav menus", async () => {
    const { container } = renderThemeMenu();
    const root = container.querySelector('[data-nav-trigger="ui:theme"]')?.parentElement as HTMLElement;
    expect(screen.queryByText("Бараан")).toBeNull();

    fireEvent.mouseEnter(root);

    expect(await screen.findByText("Бараан")).toBeTruthy();
  });

  it("marks the rows with the theme-item and theme-check classes from motion.css", async () => {
    stubHover(false);
    renderThemeMenu();
    fireEvent.click(screen.getByRole("button", { name: "Өнгө" }));

    const rows = await screen.findAllByRole("button", { name: /Цайвар|Бараан|Автомат/ });
    for (const row of rows) {
      expect(row.classList.contains("theme-item")).toBe(true);
      const check = row.querySelector(".theme-check");
      expect(check).not.toBeNull();
      expect(check?.classList.contains("invisible")).toBe(false);
      expect(row.classList.contains("font-medium")).toBe(false);
    }
  });

  it("keeps the menu open after a mouse click on the trigger that the hover opened", async () => {
    const { container } = renderThemeMenu();
    const root = container.querySelector('[data-nav-trigger="ui:theme"]')?.parentElement as HTMLElement;
    fireEvent.mouseEnter(root);
    await screen.findByText("Бараан");

    fireEvent.click(screen.getByRole("button", { name: "Өнгө" }), { detail: 1 });

    await waitFor(() => expect(screen.getByText("Бараан")).toBeTruthy());
  });
});
