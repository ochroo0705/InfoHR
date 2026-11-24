import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import type { LeaveCalendarOut } from "../../api/leavePages";
import { LeaveCalendarPage } from "./LeaveCalendarPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

function calendarAnswer(over: Partial<LeaveCalendarOut> = {}): LeaveCalendarOut {
  return {
    can_settings: false,
    days: [
      { date: "2026-03-01", day: 1, off: true, holiday: true, today: false },
      { date: "2026-03-02", day: 2, off: false, holiday: false, today: true },
    ],
    department: null,
    departments: [{ value: 4, label: "Бизнес хөгжил" }],
    lines: [
      {
        employee_id: 7,
        employee_name: "Бат Болд",
        cells: [
          { kind: "", leave_type_id: null, title: "" },
          { kind: "annual", leave_type_id: 5, title: "Жилийн амралт" },
        ],
      },
    ],
    month: "2026-03",
    next: "2026-04",
    not_configured: "",
    prev: "2026-02",
    this_month: "2026-01",
    title: "Багийн хуанли — 2026-03",
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

// The query of the calendar request on the wire.
function queryOf(call: unknown[]): Record<string, string> {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query ?? {};
}

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

function renderPage(path = "/leave/calendar/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/leave/calendar/" element={<LeaveCalendarPage />} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LeaveCalendarPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    answer = () => ok(calendarAnswer());
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (path === "/api/v1/leave/calendar") return answer(queryOf([path, init]));
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the server title, the grid and the page title", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Багийн хуанли — 2026-03" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Бат Болд" })).toBeTruthy();
    expect(document.title).toBe("Чөлөөний хуанли · MACS Human Capital");
  });

  it("sends no month or department when the address has none", async () => {
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(queryOf(h.get.mock.calls[0])).toEqual({});
  });

  it("a junk month in the address is not sent, so the page still loads", async () => {
    renderPage("/leave/calendar/?month=garbage");
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(queryOf(h.get.mock.calls[0])).toEqual({});
  });

  it("sends the month and department of the address", async () => {
    renderPage("/leave/calendar/?month=2026-03&department=4");
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(queryOf(h.get.mock.calls[0])).toEqual({ month: "2026-03", department: "4" });
  });

  it("the prev and next links keep the department", async () => {
    renderPage("/leave/calendar/?month=2026-03&department=4");
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.getByRole("link", { name: "← 2026-02" }).getAttribute("href")).toBe(
      "/leave/calendar/?month=2026-02&department=4",
    );
    expect(screen.getByRole("link", { name: "2026-04 →" }).getAttribute("href")).toBe(
      "/leave/calendar/?month=2026-04&department=4",
    );
  });

  it("the this-month link shows with its href away from the current month, and is absent on it", async () => {
    const { unmount } = renderPage("/leave/calendar/?month=2026-03&department=4");
    const link = await screen.findByRole("link", { name: "Энэ сар" });
    expect(link.getAttribute("href")).toBe("/leave/calendar/?month=2026-01&department=4");
    unmount();
    cleanup();

    answer = () => ok(calendarAnswer({ this_month: "" }));
    renderPage("/leave/calendar/?month=2026-01");
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.queryByRole("link", { name: "Энэ сар" })).toBeNull();
  });

  it("hides the this-month, prev and next links when the server gives none", async () => {
    answer = () => ok(calendarAnswer({ prev: "", next: "", this_month: "" }));
    renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    expect(screen.queryByRole("link", { name: "Энэ сар" })).toBeNull();
    expect(screen.queryByRole("link", { name: /←/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /→/ })).toBeNull();
  });

  it("a department change writes the address with replace and asks for that department", async () => {
    const { container } = renderPage("/leave/calendar/?month=2026-03");
    await screen.findByRole("link", { name: "Бат Болд" });
    const select = container.querySelector<HTMLSelectElement>('select[name="department"]');
    if (!select) throw new Error("no department select");

    fireEvent.change(select, { target: { value: "4" } });

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/leave/calendar/?month=2026-03&department=4"));
    expect(screen.getByTestId("nav").textContent).toBe("REPLACE");
    await waitFor(() => {
      const last = h.get.mock.calls.at(-1);
      expect(last && queryOf(last)).toEqual({ month: "2026-03", department: "4" });
    });
  });

  it("shows the legend with its six items", async () => {
    const { container } = renderPage();
    await screen.findByRole("link", { name: "Бат Болд" });
    const legend = container.querySelector("[data-calendar-legend]");
    expect(legend?.textContent).toContain("Ээлжийн амралт");
    expect(legend?.textContent).toContain("Бусад чөлөө");
    expect(legend?.textContent).toContain("Урт чөлөө");
    expect(legend?.textContent).toContain("Ажлын бус өдөр (амралт, баяр)");
    expect(legend?.textContent).toContain("Өнөөдөр");
    expect(legend?.textContent).toContain("Улаан тоо — баярын өдөр");
  });

  it("the not-configured banner links to the settings only with can_settings", async () => {
    answer = () => ok(calendarAnswer({ not_configured: "Ээлжийн амралтын төрөл тохироогүй байна.", can_settings: true }));
    renderPage();
    const link = await screen.findByRole("link", { name: "Тохируулах" });
    expect(link.getAttribute("href")).toBe("/leave/settings/");
  });

  it("a user who may not view the calendar sees the forbidden page", async () => {
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
