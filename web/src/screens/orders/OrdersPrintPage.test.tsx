import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode, type ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager, onlineManager, useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { OrderPrintOut } from "../../api/orderRegister";
import { OrdersPrintPage } from "./OrdersPrintPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in OrdersPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW_A = {
  n: 1,
  date: "2026-03-01",
  employee_name: "Бат Эрдэнэ",
  position: "Нягтлан бодогч",
  number: "№ 12 / 2026",
  summary: "Ажилд авах",
  issued_by: "Захирал",
  register_no: "АА12345678",
  gender: "Эр",
  age: "32",
};

const ROW_B = { ...ROW_A, n: 2, employee_name: "Дорж Сүрэн", number: "№ 13 / 2026", gender: "Эм", age: "" };

const PRINT_OUT: OrderPrintOut = {
  company: "Тест компани",
  today: "2026-11-19",
  empty: false,
  groups: [
    { department: "Санхүү", rows: [ROW_A, ROW_B] },
    { department: "Хэлтэсгүй", rows: [{ ...ROW_A, n: 1, employee_name: "Гэр Бүл" }] },
  ],
};

const EMPTY_OUT: OrderPrintOut = { company: "Тест компани", today: "2026-11-19", empty: true, groups: [] };

// A settled API answer, as the openapi-fetch client returns it.
function answer(body: unknown) {
  return Promise.resolve({
    data: body,
    error: undefined,
    response: new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }),
  });
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(url = "/employees/orders/print/", client = newClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <OrdersPrintPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// A failed API answer: the client returns the error and no data.
function failure(status: number) {
  return Promise.resolve({
    data: undefined,
    error: { field_errors: {}, form_errors: ["boom"] },
    response: new Response("{}", { status, headers: { "Content-Type": "application/json" } }),
  });
}

const HEADINGS = [
  "№",
  "Огноо",
  "Ажилтан",
  "Албан тушаал",
  "Тушаал №",
  "Тушаалын утга",
  "Тушаал гаргасан албан тушаалтан",
  "Регистр №",
  "Хүйс",
  "Нас",
];

describe("OrdersPrintPage", () => {
  const originalTitle = document.title;

  beforeEach(() => {
    h.get.mockReset();
    h.get.mockImplementation(() => answer(PRINT_OUT));
  });

  afterEach(() => {
    cleanup();
    document.title = originalTitle;
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  it("while loading shows the title and a disabled Хэвлэх button, but no table and no empty row", () => {
    h.get.mockImplementation(() => new Promise(() => {}));
    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Хүний нөөцийн тушаалууд" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Тушаал олдсонгүй")).toBeNull();
  });

  it("enables the Хэвлэх button once the rows are here", async () => {
    renderPage();

    await screen.findByText("Хэлтэс: Санхүү");
    expect((screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("on a failed request shows a short message and no table", async () => {
    h.get.mockImplementation(() => failure(500));
    renderPage();

    expect(await screen.findByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect((screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("StrictMode mounts still make exactly one request for one load", async () => {
    const client = newClient();
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={["/employees/orders/print/"]}>
            <OrdersPrintPage />
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );

    await screen.findByText("Хэлтэс: Санхүү");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(h.get).toHaveBeenCalledTimes(1);
  });

  it("renders company, date, headings, groups and numbered rows", async () => {
    renderPage("/employees/orders/print/?year=2026");

    expect(await screen.findByText("Хэлтэс: Санхүү")).toBeTruthy();
    expect(screen.getByText("Тест компани")).toBeTruthy();
    expect(screen.getByText("2026-11-19")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Хүний нөөцийн тушаалууд" })).toBeTruthy();

    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(HEADINGS);

    expect(screen.getByText("Хэлтэс: Хэлтэсгүй")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    // header row, then the group row of Санхүү, two rows, the group row of Хэлтэсгүй and its row
    expect(rows.length).toBe(6);
    const first = within(rows[2]).getAllByRole("cell").map((td) => td.textContent);
    expect(first).toEqual(["1", "2026-03-01", "Бат Эрдэнэ", "Нягтлан бодогч", "№ 12 / 2026", "Ажилд авах", "Захирал", "АА12345678", "Эр", "32"]);
    const second = within(rows[3]).getAllByRole("cell").map((td) => td.textContent);
    expect(second[0]).toBe("2");
    expect(second[9]).toBe("");
  });

  it("empty result shows the empty row", async () => {
    h.get.mockImplementation(() => answer(EMPTY_OUT));
    renderPage();

    const cell = await screen.findByText("Тушаал олдсонгүй");
    expect(cell.getAttribute("colspan")).toBe("10");
    expect(screen.queryByText(/^Хэлтэс:/)).toBeNull();
  });

  it("the Хэвлэх button calls window.print", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    renderPage();

    await screen.findByText("Хэлтэс: Санхүү");
    fireEvent.click(screen.getByRole("button", { name: "Хэвлэх" }));

    expect(print).toHaveBeenCalledTimes(1);
    print.mockRestore();
  });

  it("requests the page once with the filters of the address", async () => {
    renderPage("/employees/orders/print/?year=2026&state=bad");

    await screen.findByText("Хэлтэс: Санхүү");
    expect(h.get).toHaveBeenCalledTimes(1);
    const [path, init] = h.get.mock.calls[0];
    expect(path).toBe("/api/v1/orders/print");
    expect(init.params.query).toEqual({ q: "", sort: "-date", year: "2026", order_type: "", department: "", state: "bad" });
  });

  it("a focus event does not request the page again", async () => {
    // A control query on the same client with default options: it DOES refetch on focus, so the trigger is proven to work.
    const client = newClient();
    const controlFn = vi.fn(async () => "control");
    renderPage("/employees/orders/print/", client);
    await screen.findByText("Хэлтэс: Санхүү");
    const control = renderHook(() => useQuery({ queryKey: ["control-focus"], queryFn: controlFn }), {
      wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    await vi.waitFor(() => expect(control.result.current.isSuccess).toBe(true));
    expect(controlFn).toHaveBeenCalledTimes(1);

    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(controlFn.mock.calls.length).toBeGreaterThan(1);
    expect(h.get).toHaveBeenCalledTimes(1);
  });

  it("sets the document title and restores it when the page goes", async () => {
    document.title = "Өмнөх";
    const { unmount } = renderPage();

    expect(document.title).toBe("Хүний нөөцийн тушаалууд");
    unmount();
    expect(document.title).toBe("Өмнөх");
  });

  it("the stylesheet prefixes every rule with the page wrapper and keeps the print block", () => {
    const raw = readFileSync(resolve(process.cwd(), "src/screens/orders/ordersPrint.css"), "utf8");
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = [...css.matchAll(/([^{}]+)\{/g)]
      .map((m) => m[1].trim())
      .filter((s) => !s.startsWith("@"))
      .flatMap((s) => s.split(",").map((part) => part.trim()));

    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      const ok =
        selector.startsWith(".orders-print") ||
        selector.startsWith("body:has(.orders-print)") ||
        selector.startsWith("html:has(.orders-print)");
      expect(ok, selector).toBe(true);
    }
    expect(css).toContain("@media print");
    expect(css).toContain(".orders-print .noprint");
    expect(css).toContain("page-break-inside: avoid");
    expect(css).toContain("display: table-header-group");
    expect(css).toContain("body:has(.orders-print)::before");
    expect(css).toContain("body:has(.orders-print) > *:not(#root)");
    expect(css).toMatch(/\.orders-print h1 \{[^}]*font-weight: bold;/);
    expect(css).toContain("margin: 28px 0 11px");
    expect(raw).toContain("Arial is deliberate");
    expect(css).toContain(".orders-print .noprint button { all: revert; }");
    expect(css).toContain("body:has(.orders-print) { background: #fff; }");
    expect(css).toContain("html:has(.orders-print) { scrollbar-gutter: auto; }");
    expect(css).toContain("body:has(.orders-print) { min-height: 0; }");
  });
});
