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
  return { AppShell: () => <div data-testid="app-shell"><Outlet /></div> };
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

  it("the report print page at /reports/:key/print/ is outside the app shell, while the report page stays inside it", () => {
    const printClient = new QueryClient();
    const { unmount } = render(
      <QueryClientProvider client={printClient}>
        <MemoryRouter initialEntries={["/reports/staff-list/print/?sel=abc"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId("app-shell")).toBeNull();
    expect(screen.getByRole("button", { name: "Хэвлэх" })).toBeTruthy();
    unmount();

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/reports/staff-list/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("app-shell")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хэвлэх" })).toBeNull();
  });

  it("renders the order print page at /employees/orders/print/ with its heading", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/orders/print/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Хүний нөөцийн тушаалууд" })).toBeTruthy();
  });

  it("the print page is outside the app shell, while the order register is inside it", () => {
    const printClient = new QueryClient();
    const { unmount } = render(
      <QueryClientProvider client={printClient}>
        <MemoryRouter initialEntries={["/employees/orders/print/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId("app-shell")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    unmount();

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/employees/orders/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("app-shell")).toBeTruthy();
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
    const snippet = readFileSync(basePath, "utf8").split(/\r?\n/)[6];
    expect(snippet).toContain("<script>(function(){var t;");
    const index = readFileSync(indexPath, "utf8");
    expect(index).toContain(snippet);
  });
});
