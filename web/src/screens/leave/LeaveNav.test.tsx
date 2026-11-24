import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import { LeaveNav, type LeaveView } from "./LeaveNav";

function renderNav(current: LeaveView, canSettings: boolean) {
  return render(
    <MemoryRouter>
      <LeaveNav current={current} canSettings={canSettings} />
    </MemoryRouter>,
  );
}

function panelOf(container: HTMLElement): HTMLElement {
  const panel = container.querySelector<HTMLElement>("[data-row-menu-panel]");
  if (!panel) throw new Error("no menu panel");
  return panel;
}

function openMenu() {
  fireEvent.click(screen.getByText("Тохиргоо ▾"));
}

describe("LeaveNav", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the three views in order, each with its path", () => {
    renderNav("list", false);
    const tabs = screen.getAllByRole("link").slice(0, 3);
    expect(tabs.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Бүртгэл", "/leave/"],
      ["Үлдэгдэл", "/leave/balances/"],
      ["Багийн хуанли", "/leave/calendar/"],
    ]);
  });

  it("marks only the current view with aria-current and the violet fill", () => {
    renderNav("balances", false);
    const balances = screen.getByRole("link", { name: "Үлдэгдэл" });
    expect(balances.getAttribute("aria-current")).toBe("page");
    expect(balances.className).toContain("bg-violet-600");
    const list = screen.getByRole("link", { name: "Бүртгэл" });
    expect(list.hasAttribute("aria-current")).toBe(false);
    expect(list.className).toContain("bg-surface");
  });

  it("the settings menu is hidden without the settings right", () => {
    const { container } = renderNav("list", false);
    expect(screen.queryByText("Тохиргоо ▾")).toBeNull();
    expect(screen.queryByRole("link", { name: "Баярын өдрүүд" })).toBeNull();
    expect(container.querySelector("details")).toBeNull();
  });

  it("the settings menu holds the holidays and the leave settings links", () => {
    renderNav("list", true);
    expect(screen.getByText("Тохиргоо ▾")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Баярын өдрүүд" }).getAttribute("href")).toBe("/leave/holidays/");
    expect(screen.getByRole("link", { name: "Амралтын төрөл, тохиргоо" }).getAttribute("href")).toBe(
      "/leave/settings/",
    );
  });

  it("the settings menu opens on its summary and its panel carries data-nav-panel", () => {
    const { container } = renderNav("list", true);
    openMenu();
    const details = container.querySelector("details") as HTMLDetailsElement;
    expect(details.hasAttribute("open")).toBe(true);
    expect(panelOf(container).hasAttribute("data-nav-panel")).toBe(true);
  });

  it("clicking an item closes the menu", () => {
    const { container } = renderNav("list", true);
    openMenu();
    fireEvent.click(screen.getByRole("link", { name: "Баярын өдрүүд" }));
    expect(panelOf(container).hasAttribute("data-leaving")).toBe(true);
  });

  it("Escape closes the menu and returns focus to the summary", () => {
    const { container } = renderNav("list", true);
    openMenu();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(panelOf(container).hasAttribute("data-leaving")).toBe(true);
    expect(document.activeElement).toBe(screen.getByText("Тохиргоо ▾"));
  });

  it("a click outside the menu closes it", () => {
    const { container } = renderNav("list", true);
    openMenu();
    fireEvent.click(document.body);
    expect(panelOf(container).hasAttribute("data-leaving")).toBe(true);
  });
});
