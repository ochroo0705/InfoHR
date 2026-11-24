import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import type { LeaveListOut, LeaveRowOut } from "../../api/leave";
import { LeavePage } from "./LeavePage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in SlotsPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW: LeaveRowOut = {
  id: 1,
  employee_id: 7,
  employee_name: "Бат Болд",
  leave_type: "Жилийн амралт",
  state: "Бүртгэсэн",
  state_chip: false,
  start: "2026-03-01",
  end: "2026-03-03",
  days: 3,
  comment: "Гэр бүл",
  counts: true,
  cancel_label: "Цуцлах",
};

const CANCELLED: LeaveRowOut = {
  ...ROW,
  id: 2,
  employee_id: 8,
  employee_name: "Дорж Сарна",
  state: "Цуцалсан",
  counts: false,
  cancel_label: null,
};

function listAnswer(over: Partial<LeaveListOut> = {}): LeaveListOut {
  return {
    filters: { date_from: "", date_to: "", employee: null, q: "", status: "recorded", type_id: null },
    rows: [ROW, CANCELLED],
    next_offset: null,
    can_record: true,
    report_url: null,
    not_configured: "",
    missing_holidays: [],
    types: [{ value: 1, label: "Жилийн амралт" }],
    empty_text: "Чөлөө бүртгэгдээгүй",
    can_settings: false,
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

// The query of the list request on the wire.
function queryOf(call: unknown[]): Record<string, string> {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query ?? {};
}

// The pop-ups' first answers: the add options, the edit values and the cancel info of leave 1 (Бат Болд's row).
const OPTIONS = {
  assisted: null,
  employees: [{ value: 7, label: "Бат Болд" }],
  initial: { employee: 7, end_date: "2026-03-03", leave_type: 1, start_date: "2026-03-01" },
  not_configured: "",
  types: [{ value: 1, label: "Жилийн амралт" }],
};

const LOADED = { adays: 3, comment: null, date1: "2026-03-01", date2: "2026-03-03", leave_type: 1, status: 1 };

const EDIT = {
  id: 1,
  employees: OPTIONS.employees,
  initial: {
    employee: 7,
    end_date: "2026-03-03",
    leave_type: 1,
    note: "Гэр бүл",
    override_reason: "",
    start_date: "2026-03-01",
  },
  loaded: LOADED,
  not_configured: "",
  types: OPTIONS.types,
};

const CANCEL_INFO = {
  end: "2026-03-03",
  label: "Жилийн амралт",
  loaded: LOADED,
  mistake: false,
  restores_balance: false,
  start: "2026-03-01",
};

let answer: (query: Record<string, string>) => unknown;

function Probe() {
  const location = useLocation();
  const navType = useNavigationType();
  return (
    <>
      <div data-testid="loc">{location.pathname + location.search}</div>
      <div data-testid="nav">{navType}</div>
    </>
  );
}

function renderPage(path = "/leave/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/leave/" element={<LeavePage />} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return view;
}

// The page root is the parent of the page's h1 (the root carries data-modal; React drops the attribute when absent).
function root(): HTMLElement {
  return screen.getByRole("heading", { level: 1, name: "Чөлөө, амралт" }).parentElement as HTMLElement;
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByRole("link", { name }).closest("tr");
  if (!row) throw new Error("no row");
  return row;
}

describe("LeavePage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    answer = () => ok(listAnswer());
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (path === "/api/v1/leave") return answer(queryOf([path, init]));
      if (path === "/api/v1/leave/options") return ok(OPTIONS);
      if (path === "/api/v1/leave/{pk}") return ok(EDIT);
      if (path === "/api/v1/leave/{pk}/cancel") return ok(CANCEL_INFO);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    // The live check of an open form: a valid, empty answer (the pop-ups' check line is not under test here).
    h.post.mockImplementation(async () =>
      ok({ balance_after: null, errors: [], period: null, valid: true, warnings: [], working_days: 3 }),
    );
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the title, the rows and the default filter", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: "Бат Болд" })).toBeTruthy();
    expect(document.title).toBe("Чөлөө, амралт · MACS Human Capital");
    expect(h.get.mock.calls[0][1]).toMatchObject({ params: { query: { status: "recorded", offset: "0" } } });
    expect(rowOf("Дорж Сарна").className).toContain("line-through");
  });

  it("the address values reach the list request", async () => {
    renderPage("/leave/?q=%D0%91%D0%B0%D1%82&status=all&from=2026-01-01&type=1");
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(h.get.mock.calls[0][1]).toMatchObject({
      params: { query: { q: "Бат", status: "all", from: "2026-01-01", type: "1", offset: "0" } },
    });
  });

  it("a filter change writes the address with replace and sends the new filter", async () => {
    const { container } = renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    const status = container.querySelector<HTMLSelectElement>('select[name="status"]');
    if (!status) throw new Error("no status select");

    fireEvent.change(status, { target: { value: "cancelled" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/leave/?status=cancelled"));
    expect(screen.getByTestId("nav").textContent).toBe("REPLACE");
    await waitFor(() => {
      const last = h.get.mock.calls.at(-1);
      expect(last && queryOf(last)).toMatchObject({ status: "cancelled", offset: "0" });
    });
  });

  it("a read-only user sees no add or cancel button, and a row click goes to the employee page", async () => {
    answer = () => ok(listAnswer({ can_record: false }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.queryByRole("button", { name: "Чөлөө бүртгэх" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Цуцлах" })).toBeNull();

    expect(root().getAttribute("data-modal")).toBeNull();
    fireEvent.click(rowOf("Бат Болд"));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/7/"));
  });

  it("the add button, a row click and the cancel button set the modal state on the page root", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(root().getAttribute("data-modal")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Чөлөө бүртгэх" }));
    expect(root().getAttribute("data-modal")).toBe("add");

    fireEvent.click(rowOf("Бат Болд"));
    expect(root().getAttribute("data-modal")).toBe("edit:1");

    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(root().getAttribute("data-modal")).toBe("cancel:1");
  });

  it("shows the report link only when the API gives one", async () => {
    const { unmount } = renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.queryByRole("link", { name: "Тайлан гаргах" })).toBeNull();
    unmount();

    answer = () => ok(listAnswer({ report_url: "/reports/annual-leave/" }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByRole("link", { name: "Тайлан гаргах" }).getAttribute("href")).toBe("/reports/annual-leave/");
  });

  it("shows the not-configured notice with the setup link only to who may change the settings", async () => {
    answer = () => ok(listAnswer({ not_configured: "Жилийн амралтын төрөл тохируулаагүй байна.", can_settings: false }));
    const first = renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByText("Жилийн амралтын төрөл тохируулаагүй байна.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Тохируулах" })).toBeNull();
    first.unmount();

    answer = () => ok(listAnswer({ not_configured: "Жилийн амралтын төрөл тохируулаагүй байна.", can_settings: true }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByRole("link", { name: "Тохируулах" }).getAttribute("href")).toBe("/leave/settings/");
  });

  it("shows the missing-holiday line with the register link only when the user may register", async () => {
    answer = () => ok(listAnswer({ missing_holidays: [{ year: 2027, can_register: true }] }));
    const first = renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByText(/2027 оны баярын өдөр бүртгээгүй байна/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Бүртгэх" }).getAttribute("href")).toBe("/leave/holidays/?year=2027");
    first.unmount();

    answer = () => ok(listAnswer({ missing_holidays: [{ year: 2027, can_register: false }] }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByText(/2027 оны баярын өдөр бүртгээгүй байна/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Бүртгэх" })).toBeNull();
  });

  it("the more button asks for the next batch at its offset", async () => {
    answer = (query) => (query.offset === "0" ? ok(listAnswer({ next_offset: 50 })) : ok(listAnswer({ rows: [], next_offset: null })));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    await waitFor(() => {
      const last = h.get.mock.calls.at(-1);
      expect(last && queryOf(last)).toMatchObject({ offset: "50" });
    });
  });

  it("shows the empty text when the list has no rows", async () => {
    answer = () => ok(listAnswer({ rows: [], empty_text: "Чөлөө бүртгэгдээгүй" }));
    renderPage();
    expect(await screen.findByText("Чөлөө бүртгэгдээгүй")).toBeTruthy();
  });

  it("a refused list (403) shows the forbidden screen", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage();
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("the search box shows the name the server sends for the employee link, and typing drops the link", async () => {
    answer = (query) =>
      query.employee === "7"
        ? ok(
            listAnswer({
              filters: { date_from: "", date_to: "", employee: 7, q: "Бат Болд", status: "recorded", type_id: null },
              rows: [ROW],
            }),
          )
        : ok(listAnswer());
    const { container } = renderPage("/leave/?employee=7");
    await screen.findByRole("link", { name: "Бат Болд" });
    const search = container.querySelector<HTMLInputElement>('input[name="q"]');
    if (!search) throw new Error("no search box");
    expect(search.value).toBe("Бат Болд");

    fireEvent.change(search, { target: { value: "Дорж" } });

    await waitFor(() => {
      const last = h.get.mock.calls.at(-1);
      expect(last && queryOf(last)).toMatchObject({ q: "Дорж", offset: "0" });
    });
    const last = h.get.mock.calls.at(-1);
    expect(last && queryOf(last)).not.toHaveProperty("employee");
  });

  it("the add button opens the add pop-up", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Чөлөө бүртгэх" }));

    expect(await screen.findByRole("heading", { name: "Чөлөө бүртгэх" })).toBeTruthy();
    expect(root().getAttribute("data-modal")).toBe("add");
  });

  it("a row opens the edit pop-up for that leave", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });

    fireEvent.click(rowOf("Бат Болд"));

    expect(await screen.findByRole("heading", { name: "Чөлөө засах" })).toBeTruthy();
    expect(root().getAttribute("data-modal")).toBe("edit:1");
    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/{pk}", { params: { path: { pk: 1 } } });
  });

  it("the cancel button opens the cancel pop-up and not the edit pop-up", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));

    expect(await screen.findByRole("heading", { name: "Чөлөө цуцлах" })).toBeTruthy();
    expect(root().getAttribute("data-modal")).toBe("cancel:1");
    expect(screen.queryByRole("heading", { name: "Чөлөө засах" })).toBeNull();
    expect(h.get).not.toHaveBeenCalledWith("/api/v1/leave/{pk}", expect.anything());
  });

  it("closing a pop-up returns to no pop-up", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    // Waits for the loaded form (the loading shell is a dialog too, with no buttons).
    fireEvent.click(await screen.findByRole("button", { name: "Болих" }));

    await waitFor(() => expect(root().getAttribute("data-modal")).toBeNull());
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
