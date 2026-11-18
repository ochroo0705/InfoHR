import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// The meta request never answers here: RequireAuth would then show only the bare shell background. The route tests
// need the page content, so the guard and the shell frame are passed through and the two screens are stubs.
vi.mock("./api/client", () => ({
  api: { GET: vi.fn(() => new Promise(() => {})) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("./shell/RequireAuth", () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("./shell/AppShell", async () => {
  const { Outlet } = await import("react-router");
  return { AppShell: () => <Outlet /> };
});

vi.mock("./screens/hire/HirePage", () => ({
  HirePage: () => <p>stub: HirePage</p>,
}));

vi.mock("./screens/employee/EmployeePage", () => ({
  EmployeePage: () => <p>stub: EmployeePage</p>,
}));

// npm test runs from web/, so process.cwd() is the web/ folder.
const basePath = resolve(process.cwd(), "../app/templates/base.html");
const indexPath = resolve(process.cwd(), "index.html");

describe("App", () => {
  afterEach(() => {
    cleanup();
  });

  it("sets the document language to mn", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(document.documentElement.lang).toBe("mn");
  });

  it("renders HirePage at /employees/new/ (static segment wins over /employees/:pk/)", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/new/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("stub: HirePage")).toBeTruthy();
    expect(screen.queryByText("stub: EmployeePage")).toBeNull();
  });

  it("still renders EmployeePage at /employees/12/", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/12/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("stub: EmployeePage")).toBeTruthy();
    expect(screen.queryByText("stub: HirePage")).toBeNull();
  });
});

describe("index.html", () => {
  it("contains the pre-paint theme snippet from base.html line 7 verbatim", () => {
    const snippet = readFileSync(basePath, "utf8").split("\n")[6];
    expect(snippet).toContain("<script>(function(){var t;");
    const index = readFileSync(indexPath, "utf8");
    expect(index).toContain(snippet);
  });
});
