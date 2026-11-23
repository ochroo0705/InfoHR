import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { LogEmployeeOut, LogEmployeeRowOut, LogTabsOut } from "../../api/logs";
import { EmployeeLogPage } from "./EmployeeLogPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in OrdersPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW_A: LogEmployeeRowOut = {
  id: 1,
  date: "2026-11-20",
  time: "10:15",
  employee_id: 9,
  employee_name: "Бат Болд",
  employee_code: "E001",
  by_name: "Систем",
  kind: "history",
  kind_label: "Түүх",
  kind_class: "bg-violet-50 text-violet-700",
  is_note: false,
  is_correction: false,
  message: "Цалин өөрчлөгдсөн",
  changes: [],
  order_id: 1,
};

const ROW_B: LogEmployeeRowOut = {
  ...ROW_A,
  id: 2,
  employee_id: 10,
  employee_name: "Дорж Сүрэн",
  message: "Амралт авсан",
  order_id: null,
};

// The second batch of the default address.
const ROW_C: LogEmployeeRowOut = {
  ...ROW_A,
  id: 3,
  employee_id: 5,
  employee_name: "Хуучин Ажилтан",
  message: "Хоёр дахь хуудас",
  order_id: null,
};

// The row a new search text («Шинэ») answers with.
const ROW_NEW: LogEmployeeRowOut = {
  ...ROW_A,
  id: 4,
  employee_id: 11,
  employee_name: "Шинэ Ажилтан",
  message: "Шинэ мессеж",
  order_id: null,
};

// The tabs the API answers with (what the user may open).
let tabs: LogTabsOut = { employee: true, system: true, export: true };
// When set, the answer for the search text «Шинэ» waits until it resolves.
let gate: Promise<void> | null = null;
// When set, the answer for the search text «Шинэ» fails (a new address that fails).
let failNew = false;

// The log answer for one request. The address is the cleaned search text only, as the server would echo it.
function employeeAnswer(query: Record<string, unknown>, offset: number): LogEmployeeOut {
  const q = String(query.q ?? "");
  const employee = query.employee ? Number(query.employee) : null;
  const newSearch = q === "Шинэ";
  // A hidden person's rows never reach the page; the chip for a person the user may not see is never sent.
  const rows = employee === 77 ? [ROW_B] : newSearch ? [ROW_NEW] : offset === 0 ? [ROW_A, ROW_B] : [ROW_C];
  // The API names only the person the user may see (9 here); the hidden person (77) gets no chip.
  return {
    address: q ? new URLSearchParams({ q }).toString() : "",
    chip: employee === 9 ? { id: 9, name: "Бат Болд" } : null,
    next_offset: !newSearch && offset === 0 && employee !== 77 ? 2 : null,
    options: {
      kinds: [{ value: "note", label: "Тэмдэглэл" }],
      areas: [{ value: "salary", label: "Цалин" }],
    },
    query: {
      area: "",
      by: "",
      date_from: "",
      date_to: "",
      emp: "",
      employee: null,
      field: "",
      kinds: [],
      oldest: false,
      q,
      system: false,
    },
    rows,
    tabs,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function logCalls() {
  return h.get.mock.calls.filter((call) => call[0] === "/api/v1/logs/employee");
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
          <Route path="/logs/" element={<EmployeeLogPage />} />
          <Route path="/employees/:pk/" element={<div>employee page</div>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Waits until the rows on screen answer the address (no stale batch is shown any more).
async function settle() {
  await waitFor(() => expect(document.getElementById("rows")?.getAttribute("aria-busy") ?? null).toBeNull());
}

describe("EmployeeLogPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    tabs = { employee: true, system: true, export: true };
    gate = null;
    failNew = false;
    h.get.mockImplementation(async (path: string, init?: { params?: { query?: Record<string, unknown> } }) => {
      if (path === "/api/v1/logs/employee") {
        const query = init?.params?.query ?? {};
        const offset = Number(query.offset ?? 0);
        // 404 is not retried (retryMe), so a failure shows at once.
        if (query.q === "Шинэ" && failNew) return { data: undefined, error: {}, response: { ok: false, status: 404 } };
        if (gate && query.q === "Шинэ") await gate;
        return ok(employeeAnswer(query, offset));
      }
      // The order detail is not answered here: the test checks the request only (404 is not retried).
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads rows and shows only the allowed tabs", async () => {
    tabs = { employee: true, system: false, export: false };
    renderPage("/logs/");

    expect(await screen.findByText("Бат Болд")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ажилтны бүртгэл" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Системийн бүртгэл" })).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
  });

  it("typing in the search box changes the address and reloads from offset 0", async () => {
    const { container } = renderPage("/logs/");
    await screen.findByText("Бат Болд");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Бат" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/logs/?q=%D0%91%D0%B0%D1%82"));
    await waitFor(() => {
      const last = logCalls().at(-1);
      expect(last?.[1]?.params?.query).toMatchObject({ q: "Бат", offset: "0" });
    });
  });

  it("two quick edits request only the last address", async () => {
    const { container } = renderPage("/logs/");
    await screen.findByText("Бат Болд");
    const box = container.querySelector('[name="q"]') as HTMLInputElement;

    vi.useFakeTimers();
    try {
      fireEvent.change(box, { target: { value: "a" } });
      act(() => {
        vi.advanceTimersByTime(100);
      });
      fireEvent.change(box, { target: { value: "ab" } });
      act(() => {
        vi.advanceTimersByTime(300);
      });
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/logs/?q=ab"));
    await settle();
    expect(logCalls().some((call) => call[1]?.params?.query?.q === "a")).toBe(false);
    expect(logCalls().at(-1)?.[1]?.params?.query).toMatchObject({ q: "ab", offset: "0" });
  });

  it("old rows stay inert while the new address loads", async () => {
    let release: () => void = () => undefined;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderPage("/logs/");
    await screen.findByText("Бат Болд");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("q="));

    const rowsBox = document.getElementById("rows") as HTMLElement;
    expect(rowsBox.getAttribute("aria-busy")).toBe("true");
    expect(rowsBox.className).toContain("opacity-60");
    expect(rowsBox.className).toContain("pointer-events-none");
    expect(rowsBox.hasAttribute("inert")).toBe(true);
    // The stale rows and the table header are still there; no «Цааш харуулах» pill while the new key loads.
    expect(screen.getByText("Бат Болд")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Мессеж/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Цааш харуулах" })).toBeNull();

    await act(async () => {
      release();
    });
    expect(await screen.findByText("Шинэ Ажилтан")).toBeTruthy();
    expect(screen.queryByText("Бат Болд")).toBeNull();
    expect(document.getElementById("rows")?.getAttribute("aria-busy")).toBeNull();
  });

  it("the pill loads the next batch", async () => {
    renderPage("/logs/");
    await screen.findByText("Бат Болд");

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));

    expect(await screen.findByText("Хоёр дахь хуудас")).toBeTruthy();
    expect(logCalls().at(-1)?.[1]?.params?.query).toMatchObject({ offset: "2" });
  });

  it("403 shows the forbidden screen", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage("/logs/");

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("the Excel link carries the cleaned address and is hidden without the export right", async () => {
    // The stub builds the address from q alone, as the server does with a junk kind (kind=zzz is never echoed). The real
    // drop of junk values is tested in the API tests (app/api/tests/test_logs_api.py); this checks the page's link.
    const first = renderPage("/logs/?q=test&kind=zzz");
    await screen.findByText("Бат Болд");
    expect(document.getElementById("log-excel")?.getAttribute("href")).toBe("/api/v1/logs/employee/export?q=test");
    first.unmount();

    tabs = { employee: true, system: true, export: false };
    renderPage("/logs/?q=test");
    await screen.findByText("Бат Болд");
    expect(document.getElementById("log-excel")).toBeNull();
  });

  it("a row with an order opens the detail pop-up for that row's employee", async () => {
    renderPage("/logs/");
    await screen.findByText("Бат Болд");

    fireEvent.click(screen.getByText("Цалин өөрчлөгдсөн"));

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

  it("a visible person in the address shows the chip with a remove button", async () => {
    renderPage("/logs/?employee=9");

    expect(await screen.findByText("Ажилтан: Бат Болд")).toBeTruthy();
    expect(screen.getByLabelText("Хасах")).toBeTruthy();
  });

  it("a hidden person in the address draws no chip and shows the other rows", async () => {
    renderPage("/logs/?employee=77");

    // The stub answers chip null for a person the user may not see, and only the other rows.
    expect(await screen.findByText("Дорж Сүрэн")).toBeTruthy();
    expect(logCalls().at(-1)?.[1]?.params?.query).toMatchObject({ employee: "77" });
    expect(screen.queryByText(/Ажилтан:/)).toBeNull();
    expect(screen.queryByLabelText("Хасах")).toBeNull();
    // The hidden name appears nowhere in the page text (a guard: the stub never sends that name).
    expect(document.body.textContent).not.toContain("Нууц");
  });

  it("a first-load failure that is not 403 shows only the alert, with no frame or tabs", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPage("/logs/");

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByRole("navigation", { name: "Бүртгэлийн харагдац" })).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
    expect(document.querySelector("h1")).toBeNull();
  });

  it("a failed new address shows the alert, no rows and no Excel link; the filters stay", async () => {
    failNew = true;
    const { container } = renderPage("/logs/");
    await screen.findByText("Бат Болд");
    expect(document.getElementById("log-excel")).not.toBeNull();

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByText("Бат Болд")).toBeNull();
    expect(document.getElementById("rows")).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
    expect(container.querySelector('[name="q"]')).toBeTruthy();
  });
});
