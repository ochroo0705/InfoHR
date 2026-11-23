import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ItemOut, TodayOut, TodayViewOut } from "../../api/today";
import { Landing } from "../../routes/Landing";
import { PalettePanelContext, type PalettePanelApi } from "../../shell/palette/PalettePanelContext";
import { useMeta } from "../../shell/useMeta";
import { TodayPage } from "./TodayPage";

// The API client is replaced by a stub that answers by path, so the real hooks run and the test can see which
// requests were made.
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../../shell/useMeta", () => ({ useMeta: vi.fn() }));

const hiddenItem = {
  key: "contract:9",
  text: "Гэрээ дуусна",
  urgency: 0,
  employee: { id: 9, full_name: "Нэр Нэрт", short_name: "Н. Нэр", code: "E-009" },
  url: "/employees/9/",
  anchor: "#contract",
  clash: false,
  can_dismiss: true,
} as ItemOut;

// A full Today answer. The box has one hidden item, so the Анхаарах box renders (an empty box renders nothing).
function makeToday(over: Partial<TodayOut> = {}): TodayOut {
  return {
    away_today: 1,
    box: {
      tone: "calm",
      urgent_count: 0,
      soon_count: 0,
      gap_count: 0,
      urgent: [],
      soon: [],
      gaps: [],
      hidden: [hiddenItem],
    },
    company: { hires_month: 2, leavers_month: 1 },
    has_own_page: true,
    headcount: 10,
    shortcuts: { add_employee: true, orders: true, record_leave: true },
    show_views: true,
    strip: { cells: [], first: "2026-11-10", last: "2026-11-23", show_leave: true, today_line: "" },
    today: "2026-11-17",
    upcoming: {
      anniversaries: 0,
      birthdays: 0,
      checklist: null,
      holidays: [],
      new_hires: 0,
      open_vacancies: null,
      show_birthdays: true,
    },
    ...over,
  } as TodayOut;
}

const views: TodayViewOut[] = [{ name: "Гэрээ", report: "Ойрын 30 хоног", count: 3, url: "/reports/contracts/" }];

// Answers the requests the page makes: today, the views list, and anything else as a server error.
function stubApi({ today, viewList = [], status = 200 }: { today: TodayOut; viewList?: TodayViewOut[]; status?: number }) {
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/today" && status === 200) {
      return { data: today, response: { ok: true, status: 200 } };
    }
    if (path === "/api/v1/today") {
      return { error: {}, response: { ok: false, status } };
    }
    if (path === "/api/v1/today/views") {
      return { data: viewList, response: { ok: true, status: 200 } };
    }
    return { error: {}, response: { ok: false, status: 500 } };
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // TodayHeader reads the assistant panel from its context; the page tests only need a stand-in for it.
  const palette: PalettePanelApi = { open: vi.fn(), close: vi.fn(), toggle: vi.fn(), isOpen: false, openedByUser: false, session: 0 };
  const result = render(
    <QueryClientProvider client={client}>
      <PalettePanelContext.Provider value={palette}>
        <MemoryRouter>
          <TodayPage />
        </MemoryRouter>
      </PalettePanelContext.Provider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}

function requestedPaths(): string[] {
  return h.get.mock.calls.map((call) => call[0] as string);
}

// True when `first` comes before `second` in the document.
function before(first: Element, second: Element): boolean {
  return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

describe("TodayPage", () => {
  beforeEach(() => {
    h.get.mockReset();
  });

  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("shows the sections in the template's order", async () => {
    stubApi({ today: makeToday(), viewList: views });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-shortcuts]")).not.toBeNull());
    await waitFor(() => expect(container.querySelector("[data-today-views]")).not.toBeNull());

    const order = [
      container.querySelector("h1"),
      container.querySelector("[data-shortcuts]"),
      container.querySelector("[data-tile='headcount']"),
      container.querySelector("#attention"),
      container.querySelector("[data-today-views]"),
      container.querySelector("[data-away-strip]"),
      container.querySelector("[data-upcoming]"),
      container.querySelector("[data-today-company]"),
    ];
    for (const el of order) expect(el).not.toBeNull();
    for (let i = 0; i < order.length - 1; i++) {
      expect(before(order[i] as Element, order[i + 1] as Element)).toBe(true);
    }
  });

  it("keeps the sections and shows an alert when a refetch fails after data loaded", async () => {
    stubApi({ today: makeToday() });
    const { container, client } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-shortcuts]")).not.toBeNull());

    // The next /api/v1/today answer is refused (403, not retried); the cached data stays.
    stubApi({ today: makeToday(), status: 403 });
    await act(async () => {
      await client.refetchQueries({ queryKey: ["today"], exact: true });
    });

    expect(container.querySelector("[data-shortcuts]")).not.toBeNull();
    expect(container.querySelector("#attention")).not.toBeNull();
    expect(container.querySelector("[data-away-strip]")).not.toBeNull();
    const alert = container.querySelector("[role='alert']");
    expect(alert?.textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
  });

  it("shows no company line when company is null", async () => {
    stubApi({ today: makeToday({ company: null }) });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-shortcuts]")).not.toBeNull());
    expect(container.querySelector("[data-today-company]")).toBeNull();
  });

  it("links the company line to the company page", async () => {
    stubApi({ today: makeToday() });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-today-company]")).not.toBeNull());
    const link = container.querySelector("[data-today-company] a");
    expect(link?.getAttribute("href")).toBe("/employees/company/");
    expect(container.querySelector("[data-today-company]")?.textContent).toContain(
      "Энэ сард орсон 2 · Гарсан 1 · Компанийн байдал →",
    );
  });

  it("never requests the views when show_views is false", async () => {
    stubApi({ today: makeToday({ show_views: false }), viewList: views });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-shortcuts]")).not.toBeNull());
    expect(requestedPaths()).not.toContain("/api/v1/today/views");
    expect(container.querySelector("[data-today-views]")).toBeNull();
  });

  it("requests the views on mount when show_views is true", async () => {
    stubApi({ today: makeToday(), viewList: views });
    renderPage();
    await waitFor(() => expect(requestedPaths()).toContain("/api/v1/today/views"));
  });

  it("renders nothing for an empty views list", async () => {
    stubApi({ today: makeToday(), viewList: [] });
    const { container } = renderPage();
    await waitFor(() => expect(requestedPaths()).toContain("/api/v1/today/views"));
    expect(container.querySelector("[data-today-views]")).toBeNull();
  });

  it("sets the document title", async () => {
    stubApi({ today: makeToday() });
    renderPage();
    expect(document.title).toBe("Өнөөдөр · MACS Human Capital");
  });

  it("renders the Forbidden page on a 403", async () => {
    stubApi({ today: makeToday(), status: 403 });
    renderPage();
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("renders the NotFound page on a 404", async () => {
    stubApi({ today: makeToday(), status: 404 });
    renderPage();
    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
  });
});

describe("Landing route", () => {
  afterEach(() => {
    cleanup();
    vi.mocked(useMeta).mockReset();
  });

  it("lands a ported landing (/me/) on the My page route", async () => {
    vi.mocked(useMeta).mockReturnValue({ data: { user: { landing: "/me/" } } } as unknown as ReturnType<typeof useMeta>);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/me/" element={<p>Миний хуудас тест</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Миний хуудас тест")).toBeTruthy();
  });
});
