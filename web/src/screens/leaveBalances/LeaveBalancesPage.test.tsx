import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { LeaveBalanceListOut, LeaveBalanceRowOut } from "../../api/leavePages";
import { LeaveBalancesPage } from "./LeaveBalancesPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const PERIOD = { start: "2026-01-01", end: "2026-12-31", granted: 15, taken: 3, left: 12 };

const BAT: LeaveBalanceRowOut = { employee_id: 7, employee_name: "Бат Болд", period: PERIOD, waiting: null };
const DORJ: LeaveBalanceRowOut = {
  employee_id: 8,
  employee_name: "Дорж Сарна",
  period: { ...PERIOD, granted: 10, taken: 12, left: -2 },
  waiting: "2026-06-01",
};
const NONE: LeaveBalanceRowOut = { employee_id: 9, employee_name: "Төмөр Эрдэнэ", period: null, waiting: null };
const ZERO: LeaveBalanceRowOut = {
  employee_id: 10,
  employee_name: "Оюун Цэцэг",
  period: { ...PERIOD, granted: 5, taken: 5, left: 0 },
  waiting: null,
};

function batchAnswer(over: Partial<LeaveBalanceListOut> = {}): LeaveBalanceListOut {
  return {
    can_settings: false,
    empty_text: "Ажилтан алга",
    next_offset: null,
    not_configured: "",
    rows: [BAT, DORJ, NONE, ZERO],
    today: "2026-03-10",
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

// The query of the balances request on the wire.
function queryOf(call: unknown[]): Record<string, string> {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query ?? {};
}

let answer: (query: Record<string, string>) => unknown;

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderPage(path = "/leave/balances/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/leave/balances/" element={<LeaveBalancesPage />} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByRole("link", { name }).closest("tr");
  if (!row) throw new Error("no row");
  return row;
}

describe("LeaveBalancesPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    answer = () => ok(batchAnswer());
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (path === "/api/v1/leave/balances") return answer(queryOf([path, init]));
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the title, the rows and the page title", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Амралтын үлдэгдэл" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Бат Болд" })).toBeTruthy();
    expect(screen.getByText("Ээлжийн амралтын хоног: одоогийн ажлын жилээр (2026-03-10 байдлаар). Үлдэгдлийг өөр систем бүртгэнэ, энд зөвхөн харна.")).toBeTruthy();
    expect(document.title).toBe("Амралтын үлдэгдэл · MACS Human Capital");
  });

  it("colours the left days by sign and prints whole numbers without .0", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    const positive = rowOf("Бат Болд").querySelectorAll("td")[4].querySelector("span");
    expect(positive?.textContent).toBe("12");
    expect(positive?.className).toContain("bg-emerald-100");
    const negative = rowOf("Дорж Сарна").querySelectorAll("td")[4].querySelector("span");
    expect(negative?.textContent).toBe("-2");
    expect(negative?.className).toContain("bg-red-100");
    const zero = rowOf("Оюун Цэцэг").querySelectorAll("td")[4].querySelector("span");
    expect(zero?.textContent).toBe("0");
    expect(zero?.className).toContain("bg-slate-100");
  });

  it("shows the period and the granted and taken days right-aligned", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    const cells = rowOf("Бат Болд").querySelectorAll("td");
    expect(cells[1].textContent).toBe("2026-01-01 – 2026-12-31");
    expect(cells[2].className).toContain("text-right");
    expect(cells[2].textContent).toBe("15");
    expect(cells[3].textContent).toBe("3");
  });

  it("shows the waiting chip with its date while the right has not started", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Дорж Сарна" });
    const chip = rowOf("Дорж Сарна").querySelector("[data-waiting]");
    expect(chip?.textContent).toBe("Эрх 2026-06-01-аас");
    expect(chip?.getAttribute("title")).toBe("Ажилд орсноос хойш хангалттай сар болоогүй");
    expect(rowOf("Бат Болд").querySelector("[data-waiting]")).toBeNull();
  });

  it("says the person has no period in the current working year, across four columns", async () => {
    renderPage();
    const text = await screen.findByText("Одоогийн ажлын жилд эрх бүртгэгдээгүй");
    expect(text.getAttribute("colspan")).toBe("4");
    expect(text.className).toContain("text-slate-500");
  });

  it("says no one is listed when the batch is empty", async () => {
    answer = () => ok(batchAnswer({ rows: [], next_offset: null }));
    renderPage();
    const empty = await screen.findByText("Ажилтан алга");
    expect(empty.className).toContain("text-slate-500");
  });

  it("loads the next batch from the more pill and appends its rows", async () => {
    answer = (query) =>
      query.offset === "0"
        ? ok(batchAnswer({ rows: [BAT], next_offset: 60 }))
        : ok(batchAnswer({ rows: [NONE], next_offset: null }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(await screen.findByRole("link", { name: "Төмөр Эрдэнэ" })).toBeTruthy();
    expect(queryOf(h.get.mock.calls.at(-1) ?? [])).toMatchObject({ offset: "60" });
    expect(screen.queryByRole("button", { name: "Цааш харуулах" })).toBeNull();
  });

  it("shows the not-configured banner, and its settings link only to who may manage settings", async () => {
    answer = () => ok(batchAnswer({ not_configured: "Ээлжийн амралтын төрөл тохироогүй байна.", can_settings: true }));
    renderPage();
    expect(await screen.findByText("Ээлжийн амралтын төрөл тохироогүй байна.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Тохируулах" }).getAttribute("href")).toBe("/leave/settings/");
  });

  it("hides the settings link from a user who may not manage settings", async () => {
    answer = () => ok(batchAnswer({ not_configured: "Ээлжийн амралтын төрөл тохироогүй байна.", can_settings: false }));
    renderPage();
    expect(await screen.findByText("Ээлжийн амралтын төрөл тохироогүй байна.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Тохируулах" })).toBeNull();
  });

  it("Enter on a row opens the employee page; the name link is a link of its own", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    const row = rowOf("Бат Болд");
    expect(row.getAttribute("role")).toBeNull();
    expect(row.tabIndex).toBe(0);
    fireEvent.keyDown(row, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/7/"));
  });

  it("Space on a row opens the employee page too", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Дорж Сарна" });
    fireEvent.keyDown(rowOf("Дорж Сарна"), { key: " " });
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/8/"));
  });

  it("a user who may not view balances sees the forbidden page", async () => {
    answer = () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } });
    renderPage();
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("a failed load says so", async () => {
    answer = () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } });
    renderPage();
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
