import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { LogTabsOut } from "../../api/logs";
import { LogFrame } from "./LogFrame";

const BOTH: LogTabsOut = { employee: true, export: true, system: true };

function renderFrame(props: Partial<Parameters<typeof LogFrame>[0]> = {}) {
  return render(
    <MemoryRouter>
      <LogFrame current="employee" tabs={BOTH} excel={null} {...props}>
        <p>body text</p>
      </LogFrame>
    </MemoryRouter>,
  );
}

describe("LogFrame", () => {
  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("shows only the tabs the server allows", () => {
    renderFrame({ tabs: { employee: true, export: false, system: false } });
    const nav = screen.getByRole("navigation", { name: "Бүртгэлийн харагдац" });
    expect(nav.textContent).toBe("Ажилтны бүртгэл");
    expect(screen.queryByText("Системийн бүртгэл")).toBeNull();
  });

  it("current tab has aria-current and the violet class", () => {
    renderFrame({ current: "system" });
    const nav = screen.getByRole("navigation", { name: "Бүртгэлийн харагдац" });
    const system = within(nav).getByText("Системийн бүртгэл");
    const employee = within(nav).getByText("Ажилтны бүртгэл");
    expect(system.getAttribute("aria-current")).toBe("page");
    expect(system.className).toContain("bg-violet-600");
    expect(employee.getAttribute("aria-current")).toBeNull();
    expect(employee.className).not.toContain("bg-violet-600");
  });

  it("excel link shown only when given", () => {
    const { container, unmount } = renderFrame({ excel: null });
    expect(container.querySelector("#log-excel")).toBeNull();
    unmount();

    const again = renderFrame({ excel: "/api/v1/logs/employee/export?q=abc" });
    const link = again.container.querySelector("#log-excel") as HTMLAnchorElement | null;
    expect(link).not.toBeNull();
    expect(link?.textContent).toBe("Excel");
    expect(link?.getAttribute("href")).toBe("/api/v1/logs/employee/export?q=abc");
  });

  it("sets the document title and restores it", () => {
    document.title = "Info HR";
    const { unmount } = renderFrame({ current: "employee" });
    expect(document.title).toBe("Ажилтны бүртгэл · MACS Human Capital");
    unmount();
    expect(document.title).toBe("Info HR");
  });

  it("renders the sr-only heading and the children", () => {
    const { container } = renderFrame({ current: "system" });
    const h1 = container.querySelector("h1");
    expect(h1?.textContent).toBe("Системийн бүртгэл");
    expect(h1?.className).toContain("sr-only");
    expect(screen.getByText("body text")).toBeTruthy();
  });
});
