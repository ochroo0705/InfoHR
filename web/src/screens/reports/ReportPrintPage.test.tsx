import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode, type ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager, onlineManager, useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import type { ReportCellOut, ReportPrintOut } from "../../api/reports";
import { ReportPrintPage } from "./ReportPrintPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in OrdersPrintPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

function cell(text: string, extra: Partial<ReportCellOut> = {}): ReportCellOut {
  return { css: "", href: "", money: false, person: 0, style: "", text, value: null, ...extra };
}

const TITLE = "Ажилтны жагсаалт";

const PRINT_OUT: ReportPrintOut = {
  title: TITLE,
  company: "Тест компани",
  today: "2026-11-27",
  printed_by: "Админ Бат",
  lines: ["Төлөв: идэвхтэй", "Хэлтэс: Санхүү"],
  note: "Тайлбар мөр",
  landscape: false,
  min_group: 3,
  heads: [
    { label: "Нэр", css: "" },
    { label: "Цалин", css: "text-right" },
  ],
  groups: [
    {
      label: "Санхүү",
      rows: [
        [cell("Бат", { href: "/employees/5/", css: "bg-red-50 text-red-700" }), cell("", { money: true, value: "2500000" })],
      ],
    },
    {
      label: "Маркетинг",
      rows: [[cell("Дорж"), cell("", { money: true, value: null })]],
    },
  ],
  count: 2,
  shows_count: true,
  grouped: true,
  footer: [cell("Нийт"), cell("2,500,000₮", { css: "font-bold" })],
  summary: {
    title: "Хураангуй",
    head: ["Бүлэг", "Тоо"],
    lines: [["Санхүү", "1"]],
    foot: ["Нийт", "1"],
    money: false,
    masked: true,
  },
};

const EMPTY_OUT: ReportPrintOut = {
  ...PRINT_OUT,
  count: 0,
  grouped: false,
  groups: [],
  footer: null,
  summary: null,
};

// A settled API answer, as the openapi-fetch client returns it.
function answer(body: unknown) {
  return Promise.resolve({
    data: body,
    error: undefined,
    response: new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }),
  });
}

// A refused API answer with the API's form errors.
function refused(status: number, formErrors: string[]) {
  return Promise.resolve({
    data: undefined,
    error: { field_errors: {}, form_errors: formErrors },
    response: new Response("{}", { status, headers: { "Content-Type": "application/json" } }),
  });
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(url = "/reports/staff-list/print/", client = newClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/reports/:key/print/" element={<ReportPrintPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReportPrintPage", () => {
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

  it("renders the company and the date with the printer, the title, the filter lines and the note", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("Тест компани")).toBeTruthy();
    expect(screen.getByText("2026-11-27 · Админ Бат")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeTruthy();
    const filters = container.querySelector(".filters");
    expect(filters?.textContent).toBe("Төлөв: идэвхтэйХэлтэс: Санхүү");
    expect(screen.getByText("Тайлбар мөр").className).toBe("note");
  });

  it("renders the table heads, the rows with their cells, the footer and the summary with its masked note", async () => {
    renderPage();

    await screen.findByText("Тест компани");
    const mainTable = document.querySelector("table:not(.summary)") as HTMLElement;
    const heads = within(mainTable).getAllByRole("columnheader");
    expect(heads.map((th) => th.textContent)).toEqual(["Нэр", "Цалин"]);
    expect(heads[1].className).toBe("text-right");

    const link = screen.getByRole("link", { name: "Бат" });
    expect(link.getAttribute("href")).toBe("/employees/5/");
    expect(link.closest("td")?.className).toBe("bg-red-50 text-red-700");
    expect(screen.getAllByText("2,500,000₮")).toHaveLength(2);
    expect(screen.getByText("Дорж")).toBeTruthy();

    const footer = document.querySelector("table:not(.summary) tfoot") as HTMLElement;
    expect(within(footer).getByText("2,500,000₮").className).toBe("font-bold");

    expect(screen.getByRole("heading", { level: 2, name: "Хураангуй" })).toBeTruthy();
    const summary = document.querySelector("table.summary") as HTMLElement;
    expect(within(summary).getAllByRole("cell").map((td) => td.textContent)).toEqual(["Санхүү", "1", "Нийт", "1"]);
    expect(screen.getByText("3-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»).")).toBeTruthy();
  });

  it("draws the group heading rows with the row count only when the report is grouped", async () => {
    const first = renderPage();
    expect(await screen.findByText("Санхүү · 1")).toBeTruthy();
    expect(screen.getByText("Маркетинг · 1")).toBeTruthy();
    first.unmount();

    h.get.mockImplementation(() => answer({ ...PRINT_OUT, grouped: false }));
    renderPage();
    await screen.findByText("Тест компани");
    expect(screen.queryByText("Санхүү · 1")).toBeNull();
    expect(screen.getByText("Бат")).toBeTruthy();
  });

  it("draws the total line after the table only when shows_count is true", async () => {
    const first = renderPage();
    expect((await screen.findByText("Нийт: 2")).className).toBe("total");
    first.unmount();

    h.get.mockImplementation(() => answer({ ...PRINT_OUT, shows_count: false }));
    renderPage();
    await screen.findByText("Тест компани");
    expect(screen.queryByText(/^Нийт: /)).toBeNull();
  });

  it("an empty report shows the empty row across all the columns and no group rows", async () => {
    h.get.mockImplementation(() => answer(EMPTY_OUT));
    renderPage();

    const cellText = await screen.findByText("Өгөгдөл олдсонгүй");
    expect(cellText.getAttribute("colspan")).toBe("2");
    expect(document.querySelector("tfoot")).toBeNull();
    expect(screen.queryByText("Хураангуй")).toBeNull();
  });

  it("without a summary shows no summary table and no masked note", async () => {
    h.get.mockImplementation(() => answer({ ...PRINT_OUT, summary: null }));
    renderPage();

    await screen.findByText("Тест компани");
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(document.querySelector("table.summary")).toBeNull();
    expect(screen.queryByText(/нуусан/)).toBeNull();
  });

  it("the @page size is landscape when the report is landscape and portrait otherwise", async () => {
    const first = renderPage();
    await screen.findByText("Тест компани");
    expect(first.container.querySelector("style")?.textContent).toBe("@page { size: A4 portrait; margin: 12mm; }");
    first.unmount();

    h.get.mockImplementation(() => answer({ ...PRINT_OUT, landscape: true }));
    const second = renderPage();
    await screen.findByText("Тест компани");
    expect(second.container.querySelector("style")?.textContent).toBe("@page { size: A4 landscape; margin: 12mm; }");
  });

  it("the Хэвлэх button is disabled until the rows are here and then calls window.print", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    h.get.mockImplementation(() => new Promise(() => {}));
    const first = renderPage();
    expect((screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement).disabled).toBe(true);
    first.unmount();

    h.get.mockImplementation(() => answer(PRINT_OUT));
    renderPage();
    await screen.findByText("Тест компани");
    const button = screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(print).toHaveBeenCalledTimes(1);
    print.mockRestore();
  });

  it("a refused request shows the API's form error in role=alert, no table, and keeps Хэвлэх disabled", async () => {
    h.get.mockImplementation(() => refused(400, ["Тасалбар хүчингүй байна."]));
    renderPage("/reports/staff-list/print/?sel=bad");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Тасалбар хүчингүй байна.");
    expect(document.querySelector("table")).toBeNull();
    expect((screen.getByRole("button", { name: "Хэвлэх" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("a failed request without a form error shows the short message", async () => {
    h.get.mockImplementation(() => refused(500, []));
    renderPage();

    expect((await screen.findByRole("alert")).textContent).toBe("Татаж чадсангүй. Дахин оролдоно уу.");
  });

  it("requests the page once under StrictMode", async () => {
    render(
      <StrictMode>
        <QueryClientProvider client={newClient()}>
          <MemoryRouter initialEntries={["/reports/staff-list/print/"]}>
            <Routes>
              <Route path="/reports/:key/print/" element={<ReportPrintPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );

    await screen.findByText("Тест компани");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(h.get).toHaveBeenCalledTimes(1);
  });

  it("forwards the whole address, the ticket included, to the print route of the report key", async () => {
    renderPage("/reports/staff-list/print/?sel=abc123&year=2026");

    await screen.findByText("Тест компани");
    expect(h.get).toHaveBeenCalledTimes(1);
    const [path, init] = h.get.mock.calls[0];
    expect(path).toBe("/api/v1/reports/{key}/print");
    expect(init.params.path).toEqual({ key: "staff-list" });
    expect(init.querySerializer({})).toBe("sel=abc123&year=2026");
  });

  it("sets the document title to the report title and restores the previous one when the page goes", async () => {
    document.title = "Өмнөх";
    const { unmount } = renderPage();

    expect(await screen.findByText("Тест компани")).toBeTruthy();
    expect(document.title).toBe(TITLE);
    unmount();
    expect(document.title).toBe("Өмнөх");
  });

  it("the print query is not refetched on window focus or reconnect", async () => {
    const client = newClient();
    renderPage("/reports/staff-list/print/", client);
    await screen.findByText("Тест компани");

    // A control query on the same client, with default options: it DOES refetch on focus, so the trigger is proven.
    const controlFn = vi.fn(async () => "control");
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

  it("a footer that is an empty list draws no tfoot", async () => {
    h.get.mockImplementation(() => answer({ ...PRINT_OUT, footer: [] }));
    renderPage();

    await screen.findByText("Тест компани");
    expect(document.querySelector("table:not(.summary) tfoot")).toBeNull();
  });

  it("a money cell with an empty value prints the dash, a null value prints nothing (as mnt in _cell.html)", async () => {
    h.get.mockImplementation(() =>
      answer({
        ...PRINT_OUT,
        grouped: false,
        footer: null,
        summary: null,
        groups: [{ label: "X", rows: [[cell("", { money: true, value: "" }), cell("", { money: true, value: null })]] }],
        count: 1,
      }),
    );
    renderPage();

    await screen.findByText("Тест компани");
    const cells = within(document.querySelector("tbody") as HTMLElement).getAllByRole("cell");
    expect(cells.map((td) => td.textContent)).toEqual(["—", ""]);
  });

  it("the colour classes match print.html, each with its hex fallback before the oklch value", () => {
    const printHtml = readFileSync(resolve(process.cwd(), "../app/reports/templates/reports/print.html"), "utf8");
    const css = readFileSync(resolve(process.cwd(), "src/screens/reports/reportPrint.css"), "utf8");
    const classes = ["bg-red-50", "text-red-700", "bg-amber-50", "text-amber-800", "bg-green-50", "text-green-700", "bg-blue-50", "text-blue-700", "bg-slate-100", "text-slate-600"];
    const norm = (text: string) => text.replace(/\s+/g, " ").trim();

    for (const name of classes) {
      const fromDjango = new RegExp(`\.${name} \{([^}]*)\}`).exec(printHtml);
      const fromReact = new RegExp(`\.report-print \.${name} \{([^}]*)\}`).exec(css);
      expect(fromDjango, `print.html ${name}`).not.toBeNull();
      expect(fromReact, `reportPrint.css ${name}`).not.toBeNull();
      expect(norm(fromReact![1]), name).toBe(norm(fromDjango![1]));
      const block = fromReact![1];
      if (block.includes("oklch(")) {
        expect(block.indexOf("#"), `${name} hex fallback first`).toBeGreaterThanOrEqual(0);
        expect(block.indexOf("#")).toBeLessThan(block.indexOf("oklch("));
      }
    }
  });

  it("the stylesheet scopes every rule under .report-print and keeps the print block", () => {
    const raw = readFileSync(resolve(process.cwd(), "src/screens/reports/reportPrint.css"), "utf8");
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = [...css.matchAll(/([^{}]+)\{/g)]
      .map((m) => m[1].trim())
      .filter((s) => !s.startsWith("@"))
      .flatMap((s) => s.split(",").map((part) => part.trim()));

    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      const ok =
        selector.startsWith(".report-print") ||
        selector.startsWith("body:has(.report-print)") ||
        selector.startsWith("html:has(.report-print)");
      expect(ok, selector).toBe(true);
    }
    expect(css).toContain(".report-print .bg-red-50 { background-color: #fef2f2; background-color: oklch(97.1% .013 17.38); }");
    expect(css).toContain("@media print");
    expect(css).toContain("body:has(.report-print) > *:not(#root)");
    expect(css).not.toContain("@page");
  });
});
