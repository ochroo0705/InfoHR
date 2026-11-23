import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { LogSystemOut, LogSystemRowOut, LogTabsOut } from "../../api/logs";
import { SystemLogPage } from "./SystemLogPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in OrdersPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW_A: LogSystemRowOut = {
  id: 1,
  date: "2026-11-20",
  time: "09:00",
  actor_name: "Систем",
  action_label: "Нэвтрэлт",
  category_label: "Нэвтрэлт",
  target_label: "",
  target_type: "",
  ip: "10.0.0.1",
  message: "Нэвтэрсэн",
  changes: [],
};

const ROW_B: LogSystemRowOut = { ...ROW_A, id: 2, message: "Гарсан" };

// The second batch of the default address.
const ROW_C: LogSystemRowOut = { ...ROW_A, id: 3, message: "Хоёр дахь хуудас" };

// The row a new search text («Шинэ») answers with.
const ROW_NEW: LogSystemRowOut = { ...ROW_A, id: 4, message: "Шинэ систем мессеж" };

// The tabs the API answers with (what the user may open).
let tabs: LogTabsOut = { employee: true, system: true, export: true };
// When set, the answer for the search text «Шинэ» waits until it resolves.
let gate: Promise<void> | null = null;
// When set, the answer for the search text «Шинэ» fails (a new address that fails).
let failNew = false;

// The log answer for one request. The address is the cleaned search text only, as the server would echo it.
function systemAnswer(query: Record<string, unknown>, offset: number): LogSystemOut {
  const q = String(query.q ?? "");
  const newSearch = q === "Шинэ";
  const rows = newSearch ? [ROW_NEW] : offset === 0 ? [ROW_A, ROW_B] : [ROW_C];
  return {
    address: q ? new URLSearchParams({ q }).toString() : "",
    next_offset: !newSearch && offset === 0 ? 2 : null,
    options: {
      actions: [{ value: "login", label: "Нэвтрэлт" }],
      categories: [{ value: "auth", label: "Нэвтрэлт" }],
    },
    query: {
      action: "",
      by: "",
      categories: [],
      date_from: "",
      date_to: "",
      ip: "",
      oldest: false,
      q,
      target: "",
    },
    rows,
    tabs,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function logCalls() {
  return h.get.mock.calls.filter((call) => call[0] === "/api/v1/logs/system");
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
          <Route path="/logs/system/" element={<SystemLogPage />} />
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

describe("SystemLogPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    tabs = { employee: true, system: true, export: true };
    gate = null;
    failNew = false;
    h.get.mockImplementation(async (path: string, init?: { params?: { query?: Record<string, unknown> } }) => {
      if (path === "/api/v1/logs/system") {
        const query = init?.params?.query ?? {};
        const offset = Number(query.offset ?? 0);
        // 404 is not retried (retryMe), so a failure shows at once.
        if (query.q === "Шинэ" && failNew) return { data: undefined, error: {}, response: { ok: false, status: 404 } };
        if (gate && query.q === "Шинэ") await gate;
        return ok(systemAnswer(query, offset));
      }
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
    tabs = { employee: false, system: true, export: false };
    renderPage("/logs/system/");

    expect(await screen.findByText("Нэвтэрсэн")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Системийн бүртгэл" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Ажилтны бүртгэл" })).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
  });

  it("typing in the search box changes the address and reloads from offset 0", async () => {
    const { container } = renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Бат" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/logs/system/?q=%D0%91%D0%B0%D1%82"));
    await waitFor(() => {
      const last = logCalls().at(-1);
      expect(last?.[1]?.params?.query).toMatchObject({ q: "Бат", offset: "0" });
    });
  });

  it("two quick edits request only the last address", async () => {
    const { container } = renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");
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

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/logs/system/?q=ab"));
    await settle();
    expect(logCalls().some((call) => call[1]?.params?.query?.q === "a")).toBe(false);
    expect(logCalls().at(-1)?.[1]?.params?.query).toMatchObject({ q: "ab", offset: "0" });
  });

  it("old rows stay inert while the new address loads", async () => {
    let release: () => void = () => undefined;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("q="));

    const rowsBox = document.getElementById("rows") as HTMLElement;
    expect(rowsBox.getAttribute("aria-busy")).toBe("true");
    expect(rowsBox.className).toContain("opacity-60");
    expect(rowsBox.className).toContain("pointer-events-none");
    expect(rowsBox.hasAttribute("inert")).toBe(true);
    expect(screen.getByText("Нэвтэрсэн")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Цааш харуулах" })).toBeNull();

    await act(async () => {
      release();
    });
    expect(await screen.findByText("Шинэ систем мессеж")).toBeTruthy();
    expect(screen.queryByText("Нэвтэрсэн")).toBeNull();
    expect(document.getElementById("rows")?.getAttribute("aria-busy")).toBeNull();
  });

  it("the pill loads the next batch", async () => {
    renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));

    expect(await screen.findByText("Хоёр дахь хуудас")).toBeTruthy();
    expect(logCalls().at(-1)?.[1]?.params?.query).toMatchObject({ offset: "2" });
  });

  it("403 shows the forbidden screen", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage("/logs/system/");

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("the Excel link carries the cleaned address and is hidden without the export right", async () => {
    // The typed ip is junk: the server drops it, so the address and the Excel link keep only q.
    const first = renderPage("/logs/system/?q=test&ip=zzz-not-an-ip");
    await screen.findByText("Нэвтэрсэн");
    expect(document.getElementById("log-excel")?.getAttribute("href")).toBe("/api/v1/logs/system/export?q=test");
    first.unmount();

    tabs = { employee: true, system: true, export: false };
    renderPage("/logs/system/?q=test");
    await screen.findByText("Нэвтэрсэн");
    expect(document.getElementById("log-excel")).toBeNull();
  });

  it("a first-load failure that is not 403 shows only the alert, with no frame or tabs", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPage("/logs/system/");

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByRole("navigation", { name: "Бүртгэлийн харагдац" })).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
    expect(document.querySelector("h1")).toBeNull();
  });

  it("a failed new address shows the alert, no rows and no Excel link; the filters stay", async () => {
    failNew = true;
    const { container } = renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");
    expect(document.getElementById("log-excel")).not.toBeNull();

    fireEvent.change(container.querySelector('[name="q"]') as HTMLInputElement, { target: { value: "Шинэ" } });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByText("Нэвтэрсэн")).toBeNull();
    expect(document.getElementById("rows")).toBeNull();
    expect(document.getElementById("log-excel")).toBeNull();
    expect(container.querySelector('[name="q"]')).toBeTruthy();
  });

  it("system page has no pop-ups: a row click sends no order request", async () => {
    renderPage("/logs/system/");
    await screen.findByText("Нэвтэрсэн");

    fireEvent.click(screen.getByText("Нэвтэрсэн"));

    expect(h.get.mock.calls.some((call) => String(call[0]).includes("/orders/"))).toBe(false);
    expect(h.get.mock.calls.every((call) => call[0] === "/api/v1/logs/system")).toBe(true);
  });
});
