import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { invalidateEventWrites } from "../../api/events";
import type { OrderRegisterOut, OrderRegisterRowOut } from "../../api/orderRegister";
import { OrdersPage } from "./OrdersPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in CompanyPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW_A: OrderRegisterRowOut = {
  key: "o1",
  order_id: 1,
  employee_id: 9,
  number_label: "№ 12 / 2026",
  number_muted: false,
  date_label: "2026-03-01",
  employee_name: "Бат Эрдэнэ",
  department: "Санхүү",
  summary: "Ажилд авах",
  state: "registered",
  state_label: "Бүртгэгдсэн",
  chip_class: "chip-registered",
  awaiting: false,
  awaiting_chip: null,
  cancelled: false,
  pickable: true,
  opens: "detail",
};

const ROW_B: OrderRegisterRowOut = {
  ...ROW_A,
  key: "o2",
  order_id: 2,
  employee_id: 10,
  number_label: "№ 13 / 2026",
  employee_name: "Дорж Сүрэн",
};

// A legacy row has no order: it opens the employee page, and is not pickable.
const LEGACY: OrderRegisterRowOut = {
  ...ROW_A,
  key: "legacy:5",
  order_id: null,
  employee_id: 5,
  number_label: "",
  number_muted: true,
  employee_name: "Хуучин Ажилтан",
  state: "legacy",
  state_label: "Хуучин",
  chip_class: "chip-legacy",
  pickable: false,
  opens: "employee",
};

// The row a new search text («Шинэ») answers with.
const ROW_NEW: OrderRegisterRowOut = {
  ...ROW_A,
  key: "o3",
  order_id: 3,
  employee_id: 11,
  number_label: "№ 14 / 2026",
  employee_name: "Шинэ Ажилтан",
};

// The server's sort heads for a sort value: the number column is sortable, the date column shows its arrow.
function sortHeads(sort: string): OrderRegisterOut["sort_heads"] {
  const byNumber = sort === "number" || sort === "-number";
  return {
    number: byNumber
      ? { next: sort === "number" ? "-number" : "number", arrow: sort === "number" ? "↑" : "↓", aria: sort === "number" ? "ascending" : "descending" }
      : { next: "number", arrow: "", aria: "" },
    date: { next: "-date", arrow: sort === "-date" ? "↓" : "", aria: sort === "-date" ? "descending" : "" },
    employee: { next: "employee", arrow: "", aria: "" },
  };
}

// Flags a test overrides on every register answer (report link, print rights).
let flags: Partial<OrderRegisterOut> = {};
// When set, the answer for the search text «Шинэ» waits until it resolves.
let gate: Promise<void> | null = null;
// When set, the answer for the search text «Шинэ» fails (a new key), or the answer for a later batch fails.
let failNew = false;
let failNext = false;

// The register answer for one request: two rows on the first batch, a third (legacy) row on the second. The search text
// «Шинэ» answers one other row.
function registerAnswer(query: Record<string, string>, offset: number): OrderRegisterOut {
  const sort = query.sort || "-date";
  const newSearch = query.q === "Шинэ";
  // The search text «Пусто» answers no row at all.
  const none = query.q === "Пусто";
  // The search text «Ижил» answers the stale row's own key again (the same key, a new batch).
  const same = query.q === "Ижил";
  return {
    all_labels: { year: "Бүх он", order_type: "Бүх төрөл", department: "Бүх хэлтэс", state: "Бүх төлөв" },
    background_from: 11,
    can_manage: true,
    report_link: true,
    options: {
      years: [{ value: "2025", label: "2025" }],
      types: [{ value: "1", label: "Ажилд авах" }],
      departments: [{ value: "4", label: "Санхүү" }],
      states: [{ value: "registered", label: "Бүртгэгдсэн" }],
    },
    query: {
      q: query.q ?? "",
      sort,
      year: query.year ? Number(query.year) : null,
      order_type: null,
      department: null,
      state: query.state ?? "",
    },
    sort_heads: sortHeads(sort),
    rows: none ? [] : newSearch ? [ROW_NEW] : same ? [ROW_A] : offset === 0 ? [ROW_A, ROW_B] : [LEGACY],
    next_offset: !none && !newSearch && offset === 0 ? 2 : null,
    ...flags,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function registerCalls() {
  return h.get.mock.calls.filter((call) => call[0] === "/api/v1/orders/register");
}

// Shows the router's address, so a test can read what the URL became.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderPage(path: string, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/employees/orders/" element={<OrdersPage />} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function rowCheckbox(name: string): HTMLInputElement {
  const row = screen.getByText(name).closest("tr") as HTMLElement;
  return within(row).getByRole("checkbox", { name: "Тушаал сонгох" }) as HTMLInputElement;
}

// Waits until the rows on screen answer the address (no stale batch is shown any more).
async function settle() {
  await waitFor(() => expect(document.getElementById("rows")?.getAttribute("aria-busy") ?? null).toBeNull());
}

function yearSelect(container: HTMLElement): HTMLSelectElement {
  return container.querySelector('[name="year"]') as HTMLSelectElement;
}

describe("OrdersPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    flags = {};
    gate = null;
    failNew = false;
    failNext = false;
    h.get.mockImplementation(async (path: string, init?: { params?: { query?: Record<string, string> } }) => {
      if (path === "/api/v1/orders/register") {
        const query = init?.params?.query ?? {};
        const offset = Number(query.offset ?? 0);
        // 404 is not retried (retryMe), so a failure shows at once.
        if (query.q === "Шинэ" && failNew) return { data: undefined, error: {}, response: { ok: false, status: 404 } };
        if (offset > 0 && failNext) return { data: undefined, error: {}, response: { ok: false, status: 404 } };
        if (gate && query.q && query.q !== "Пусто") await gate;
        return ok(registerAnswer(query, offset));
      }
      // The order detail is not answered here: the test checks the request only (404 is not retried).
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads rows and shows the header links by the server flags", async () => {
    renderPage("/employees/orders/");

    expect(await screen.findByText("Бат Эрдэнэ")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Тушаалын бүртгэл" }).className).toContain("text-xl");
    expect(document.title).toBe("Тушаалын бүртгэл · MACS Human Capital");

    const report = screen.getByRole("link", { name: "Тайлан гаргах" });
    expect(report.getAttribute("href")).toBe("/reports/orders/");
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();

    const print = screen.getByRole("link", { name: "Хэвлэх" });
    expect(print.getAttribute("href")).toBe("/employees/orders/print/");
    expect(print.getAttribute("target")).toBe("_blank");
    expect(print.getAttribute("rel")).toBe("noopener");
  });

  it("without the report link and the print rights the header and the table show no such controls", async () => {
    flags = { report_link: false, can_manage: false };
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    expect(screen.queryByRole("link", { name: "Тайлан гаргах" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Сонгосныг хэвлэх/ })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Тушаал сонгох" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Бүгдийг сонгох" })).toBeNull();
    // The print link is always there.
    expect(screen.getByRole("link", { name: "Хэвлэх" })).toBeTruthy();
  });

  it("restores the document title when the page is left", async () => {
    const { unmount } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");
    expect(document.title).toBe("Тушаалын бүртгэл · MACS Human Capital");

    unmount();
    expect(document.title).toBe("Info HR");
  });

  it("typing in the search box changes the URL and reloads from offset 0", async () => {
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Бат" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/orders/?q=%D0%91%D0%B0%D1%82"));
    await waitFor(() => {
      const last = registerCalls().at(-1);
      expect(last?.[1]?.params?.query).toMatchObject({ q: "Бат", offset: "0" });
    });
  });

  it("a sort click flips the arrow and reloads", async () => {
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(screen.getByRole("link", { name: "Дугаар" }));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("sort=number"));
    await waitFor(() => {
      const header = screen.getByRole("columnheader", { name: /Дугаар/ });
      expect(header.getAttribute("aria-sort")).toBe("ascending");
      expect(within(header).getByText("↑")).toBeTruthy();
    });
    expect(registerCalls().at(-1)?.[1]?.params?.query).toMatchObject({ sort: "number", offset: "0" });
  });

  it("scrolling the pill loads the next batch and keeps the ticks", async () => {
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(rowCheckbox("Бат Эрдэнэ"));
    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));

    expect(await screen.findByText("Хуучин Ажилтан")).toBeTruthy();
    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(true);
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх (1)" })).toBeTruthy();
    expect(registerCalls().at(-1)?.[1]?.params?.query).toMatchObject({ offset: "2" });
  });

  it("changing a filter clears the ticks", async () => {
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(rowCheckbox("Бат Эрдэнэ"));
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх (1)" })).toBeTruthy();

    fireEvent.change(yearSelect(container), { target: { value: "2025" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("year=2025"));
    await settle();
    await screen.findByText("Бат Эрдэнэ");
    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(false);
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();
  });

  it("a filter changed and changed back shows no ticks and no count", async () => {
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(rowCheckbox("Бат Эрдэнэ"));
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх (1)" })).toBeTruthy();

    fireEvent.change(yearSelect(container), { target: { value: "2025" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("year=2025"));
    await settle();
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(yearSelect(container), { target: { value: "" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/orders/"));
    await settle();
    await screen.findByText("Бат Эрдэнэ");

    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(false);
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();
  });

  it("a sort click clears the ticks", async () => {
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(rowCheckbox("Бат Эрдэнэ"));
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх (1)" })).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "Дугаар" }));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("sort=number"));
    await settle();
    await screen.findByText("Бат Эрдэнэ");
    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(false);
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();
  });

  it("while a new key loads the last rows stay on screen, inert; the new batch then replaces them", async () => {
    let release: () => void = () => undefined;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("q="));

    const rowsBox = document.getElementById("rows") as HTMLElement;
    expect(rowsBox.getAttribute("aria-busy")).toBe("true");
    expect(rowsBox.className).toContain("opacity-60");
    expect(rowsBox.className).toContain("pointer-events-none");
    // The stale rows and the table header are still there; no empty row and no «Цааш харуулах» pill.
    expect(screen.getByText("Бат Эрдэнэ")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Дугаар/ })).toBeTruthy();
    expect(screen.queryByText("Тушаал олдсонгүй")).toBeNull();
    expect(screen.queryByRole("button", { name: "Цааш харуулах" })).toBeNull();

    await act(async () => {
      release();
    });
    expect(await screen.findByText("Шинэ Ажилтан")).toBeTruthy();
    expect(screen.queryByText("Бат Эрдэнэ")).toBeNull();
    expect(document.getElementById("rows")?.getAttribute("aria-busy")).toBeNull();
  });

  it("a row opens the detail pop-up for that row's employee", async () => {
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(screen.getByText("Бат Эрдэнэ"));

    await waitFor(() =>
      expect(
        h.get.mock.calls.some(
          (call) =>
            call[0] === "/api/v1/employees/{pk}/orders/{order_id}/detail" &&
            call[1]?.params?.path?.pk === 9 &&
            call[1]?.params?.path?.order_id === 1,
        ),
      ).toBe(true),
    );
  });

  it("a cancel saved from the pop-up refetches the register", async () => {
    // A cancel or a sign saved in a pop-up runs invalidateEventWrites (events.ts), which the register answers by refetching.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderPage("/employees/orders/", client);
    await screen.findByText("Бат Эрдэнэ");
    expect(registerCalls()).toHaveLength(1);

    await act(async () => {
      await invalidateEventWrites(client, 9);
    });

    await waitFor(() => expect(registerCalls()).toHaveLength(2));
  });

  it("a legacy row navigates to the employee page", async () => {
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    fireEvent.click(await screen.findByText("Хуучин Ажилтан"));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/5/"));
  });

  it("the print link carries the filters", async () => {
    renderPage("/employees/orders/?state=registered&year=2025");
    await screen.findByText("Бат Эрдэнэ");

    expect(screen.getByRole("link", { name: "Хэвлэх" }).getAttribute("href")).toBe(
      "/employees/orders/print/?year=2025&state=registered",
    );
  });

  it("shows the load message when the first load fails", async () => {
    // 404 is not retried (retryMe), so the message shows at once; a 500 would be retried for seconds.
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPage("/employees/orders/");

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByText("Тушаал олдсонгүй")).toBeNull();
  });

  it("while a new key loads, a stale row's checkbox and select-all change nothing and the print form carries no ids", async () => {
    let release: () => void = () => undefined;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Ижил" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("q="));

    const rowsBox = document.getElementById("rows") as HTMLElement;
    expect(rowsBox.hasAttribute("inert")).toBe(true);

    fireEvent.click(rowCheckbox("Бат Эрдэнэ"));
    fireEvent.click(document.getElementById("order-pick-all") as HTMLElement);

    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();
    expect(document.querySelectorAll('input[name="ids"]')).toHaveLength(0);

    await act(async () => {
      release();
    });
    // The new batch holds the same key as the stale row. A pick made while stale must not carry over to it: the
    // guards in onPick and onPickAll are what keep the count absent here (remove them and this test fails).
    expect(await screen.findByText("Бат Эрдэнэ")).toBeTruthy();
    await settle();
    expect(rowCheckbox("Бат Эрдэнэ").checked).toBe(false);
    expect(screen.getByRole("button", { name: "Сонгосныг хэвлэх" })).toBeTruthy();
    expect(document.querySelectorAll('input[name="ids"]')).toHaveLength(0);
  });

  it("a new key that fails drops the stale rows, removes aria-busy and shows the alert; the filters stay", async () => {
    failNew = true;
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByText("Бат Эрдэнэ")).toBeNull();
    expect(document.getElementById("rows")).toBeNull();
    expect(container.querySelector('[name="q"]')).toBeTruthy();
  });

  it("a failed next batch keeps the loaded rows and shows the alert", async () => {
    failNext = true;
    renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Бат Эрдэнэ")).toBeTruthy();
    const rowsBox = document.getElementById("rows") as HTMLElement;
    expect(rowsBox.getAttribute("aria-busy")).toBeNull();
    expect(rowsBox.hasAttribute("inert")).toBe(false);
  });

  it("while a new key loads over an empty result, the table header stays and no empty-row message shows", async () => {
    let release: () => void = () => undefined;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderPage("/employees/orders/");
    await screen.findByText("Бат Эрдэнэ");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Пусто" } });
    expect(await screen.findByText("Тушаал олдсонгүй")).toBeTruthy();

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });
    await waitFor(() => expect(document.getElementById("rows")?.getAttribute("aria-busy")).toBe("true"));

    expect(screen.getByRole("columnheader", { name: /Дугаар/ })).toBeTruthy();
    expect(screen.queryByText("Тушаал олдсонгүй")).toBeNull();
    expect(document.querySelectorAll("#rows tbody tr")).toHaveLength(0);

    await act(async () => {
      release();
    });
    expect(await screen.findByText("Шинэ Ажилтан")).toBeTruthy();
  });

  it("a failed next batch is not requested again by scrolling the pill into view; a click retries once", async () => {
    // Every observer reports its element as visible at once, so a sentinel left armed would fetch again and again.
    class AlwaysVisible {
      callback: IntersectionObserverCallback;
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback;
      }
      observe() {
        this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    vi.stubGlobal("IntersectionObserver", AlwaysVisible);
    failNext = true;

    renderPage("/employees/orders/");
    expect(await screen.findByRole("alert")).toBeTruthy();

    const nextBatchRequests = () =>
      registerCalls().filter((call) => call[1]?.params?.query?.offset === "2").length;
    expect(nextBatchRequests()).toBe(1);

    // The pill stays on screen; scrolling it into view (the always-visible observer) does not fire again.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(nextBatchRequests()).toBe(1);
    expect(screen.getByRole("button", { name: "Цааш харуулах" })).toBeTruthy();

    // The click is a manual retry: exactly one more request.
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    await waitFor(() => expect(nextBatchRequests()).toBe(2));
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(nextBatchRequests()).toBe(2);
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});
