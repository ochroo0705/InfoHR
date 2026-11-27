// The harness is imported first: it stubs fetch before ../../api/client (and so ../../api/reports) load.
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType, useNavigate, type NavigateFunction } from "react-router";
import { setCsrf } from "../../api/client";
import type { components } from "../../api/schema";
import { legacyOrigin } from "../../lib/AppLink";
import { ReportPage } from "./ReportPage";

// The ECharts modules are replaced, so no canvas is needed (as ChartLayout.test does).
const mocks = vi.hoisted(() => {
  const instance = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
  return { instance, init: vi.fn(() => instance), use: vi.fn() };
});
vi.mock("echarts/core", () => ({ init: mocks.init, use: mocks.use }));
vi.mock("echarts/charts", () => ({ BarChart: {}, LineChart: {}, PieChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  ToolboxComponent: {},
}));
vi.mock("echarts/renderers", () => ({ SVGRenderer: {} }));

type ReportPageOut = components["schemas"]["ReportPageOut"];
type ReportBarOut = components["schemas"]["ReportBarOut"];
type ReportHeadOut = components["schemas"]["ReportHeadOut"];
type ReportLayoutPageOut = components["schemas"]["ReportLayoutPageOut"];
type ReportLayoutCardOut = components["schemas"]["ReportLayoutCardOut"];

const opt = (value: string, label: string) => ({ value, label });

// The bar as the API sends it (the same shape as ReportPage.test's fixture).
function barFixture(overrides: Partial<ReportBarOut> = {}): ReportBarOut {
  return {
    adds: [],
    clear_url: "/reports/staff/?view=plain",
    column_chips: [],
    columns_query: "cols=name",
    items: [],
    picker: [],
    options: {
      absence_types: [],
      attributes: [],
      branches: [opt("5", "Улаанбаатар"), opt("6", "Дархан")],
      change_kinds: [],
      contact_types: [],
      departments: [],
      discipline_types: [],
      emptypes: [opt("1", "Ажилчид"), opt("2", "Гадаад нөөц")],
      genders: [opt("M", "Эрэгтэй"), opt("F", "Эмэгтэй")],
      group_choices: [],
      group_text: "",
      leave_states: [],
      leave_types: [],
      no_working_state: [opt("2", "Гадаад нөөц")],
      order_types: [],
      people: [],
      period_from: "2026-01-01",
      period_to: "2026-12-31",
      positions: [],
      present_types: [],
      quarter: null,
      reasons: [],
      states: [opt("working", "Ажиллаж байгаа"), opt("all", "Бүгд")],
      training_types: [],
      year: null,
    },
    ...overrides,
  } as ReportBarOut;
}

function headFixture(overrides: Partial<ReportHeadOut> = {}): ReportHeadOut {
  return {
    excel_url: "",
    layouts: [
      { current: true, label: "Хүснэгт", name: "table", url: "/reports/staff/" },
      { current: false, label: "Карт", name: "cards", url: "/reports/staff/?layout=cards" },
    ],
    print_url: "",
    saved: null,
    selectable: false,
    selection_urls: {},
    staff_actions: false,
    title: "Ажилчдын жагсаалт",
    tools: { columns: false, rules: false, format: false },
    ...overrides,
  } as ReportHeadOut;
}

function card(title: string): ReportLayoutCardOut {
  return {
    extras: [],
    href: "",
    mark: "",
    photo_initial: "",
    photo_srcset: "",
    photo_url: "",
    subtitle: "",
    title,
  };
}

// One payload per kind, the smallest that draws a text the test can find.
function payloadFor(kind: string): Partial<ReportLayoutPageOut> {
  switch (kind) {
    case "cards":
      return { cards: { items: [card("Карт нэг")], next_offset: null, total: 1 } };
    case "board":
      return {
        board: {
          cap: 200,
          lanes: [{ cards: [card("Лане карт")], count: 1, figure: "", href: "", label: "Санхүү" }],
          shown: 1,
          total: 1,
          value_label: "",
        },
      };
    case "calendar":
      return {
        calendar: {
          days: [],
          heading: "2026 оны 5-р сар",
          keep: [],
          mode: "month",
          month_value: "2026-05",
          next_href: "",
          prev_href: "",
          switch_href: "",
          today_href: "",
          total: 1,
          undated: 0,
          weeks: [],
        },
      };
    case "timeline":
      return {
        timeline: {
          all_href: "",
          cap: 100,
          clipped: false,
          enter_href: "",
          first: "2026-01-01",
          groups: [
            {
              bars: [
                {
                  href: "",
                  label: "Ажил: 2026-03-01 – 2026-03-10",
                  left_pct: 10,
                  mark: "",
                  tip: "2026-03-01 – 2026-03-10 · 10 өдөр",
                  tip_title: "Ажил",
                  title: "Ажил",
                  width_pct: 25,
                },
              ],
              count: 1,
              label: "",
            },
          ],
          last: "2026-12-31",
          off_axis: 0,
          over_cap: 0,
          ticks: [{ label: "2026-04", left_pct: 25 }],
          today_pct: null,
          total: 1,
          undated: 0,
          year: 2026,
          year_next_href: "",
          year_prev_href: "",
          years: 5,
        },
      };
    case "chart":
      return {
        chart: {
          category_label: "Алба",
          hrefs: [],
          kind: "bar",
          kind_label: "Баганан",
          labels: ["Санхүү", "Ажил"],
          masked: false,
          money: false,
          note: "",
          percent: false,
          rows: [
            { label: "Санхүү", href: "", cells: [], total: "3,000₮" },
            { label: "Ажил", href: "", cells: [], total: "1,000₮" },
          ],
          series: [],
          series_labels: [],
          value_label: "Нийлбэр",
          values: [3000, 1000],
        },
      };
    case "pivot":
      return {
        pivot: {
          grids: [
            {
              caption: "Цалин",
              col_heads: [],
              col_totals: [],
              corner_label: "Алба",
              empty: false,
              grand: "",
              masked: false,
              note: "",
              rows: [],
            },
          ],
        },
      };
    default:
      return {};
  }
}

// A layout answer: the kind's payload, the page-level fields the page reads, and the given overrides.
function layoutPage(kind: string, overrides: Partial<ReportLayoutPageOut> = {}): ReportLayoutPageOut {
  return {
    bar: { keep: [], layout: kind, selects: [] },
    board: null,
    calendar: null,
    cards: null,
    chart: null,
    clear_rules_url: "/reports/staff/?q=a&rules=",
    count: 1,
    kind,
    note: "",
    pivot: null,
    query: "q=a",
    rules_text: "",
    shows_count: true,
    timeline: null,
    ...payloadFor(kind),
    ...overrides,
  } as ReportLayoutPageOut;
}

// A page answer for a non-table layout.
function layoutAnswer(kind: string, layout: Partial<ReportLayoutPageOut> = {}, bar: ReportBarOut | null = barFixture()): ReportPageOut {
  return {
    bar,
    head: headFixture(),
    layout: kind,
    layout_page: layoutPage(kind, layout),
    redirect: "",
    table: null,
    title: "Ажилчдын жагсаалт",
  };
}

// Answers every request by its URL. The page is `/api/v1/reports/<key>`.
type Responder = (url: URL) => Response | Promise<Response>;
function answer(responder: Responder) {
  fetchMock.mockImplementation((input: Request) => Promise.resolve(responder(new URL(input.url))));
}

// The page requests made so far, as the URLs they were sent to.
function pageUrls(): URL[] {
  return fetchMock.mock.calls
    .map((call) => new URL((call[0] as Request).url))
    .filter((url) => url.pathname === "/api/v1/reports/staff");
}

// Shows the router's address and how it got there, so a test can read where a click went and how many times.
function Probe() {
  const location = useLocation();
  const type = useNavigationType();
  return (
    <>
      <div data-testid="loc">{location.pathname + location.search}</div>
      <div data-testid="nav">{type}</div>
    </>
  );
}

// Hands the router's navigate to the test, so it can move to another address of the same report.
let navigateTo: NavigateFunction | null = null;
function Capture() {
  navigateTo = useNavigate();
  return null;
}

let client: QueryClient;

beforeEach(() => {
  resetFetch();
  setCsrf("");
  client = newClient();
  navigateTo = null;
});

afterEach(() => {
  cleanup();
  resetObservers();
  localStorage.clear();
});

function renderPage(entry: string) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/reports/:key/" element={<ReportPage />} />
        </Routes>
        <Probe />
        <Capture />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function where(): string {
  return screen.getByTestId("loc").textContent ?? "";
}

describe("ReportPage layouts", () => {
  it.each([
    ["cards", "Карт нэг"],
    ["board", "Лане карт"],
    ["calendar", "2026 оны 5-р сар"],
    ["timeline", "2026-04"],
    ["chart", "Нийлбэр"],
    ["pivot", "Цалин"],
  ])("each kind renders its layout: %s", async (kind, marker) => {
    answer(() => jsonResponse(200, layoutAnswer(kind)));
    renderPage(`/reports/staff/?layout=${kind}`);

    expect((await screen.findAllByText(marker)).length).toBeGreaterThan(0);
    // The table layout is not mounted (it is the only one that asks for rows), and the Django link is not the page.
    expect(fetchMock.mock.calls.some((call) => new URL((call[0] as Request).url).pathname.endsWith("/rows"))).toBe(false);
    expect(screen.queryByText("Энэ харагдацыг хуучин хуудсанд нээх")).toBeNull();
  });

  it("the filter bar and rules line stay live while a new layout address loads", async () => {
    let releaseB: (response: Response) => void = () => {};
    const pendingB = new Promise<Response>((resolve) => {
      releaseB = resolve;
    });
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.searchParams.get("q") === "b") return pendingB;
      return Promise.resolve(jsonResponse(200, layoutAnswer("board", { rules_text: "Бүртгэлийн огноо" })));
    });

    renderPage("/reports/staff/?layout=board&q=a");
    const search = (await screen.findByLabelText("Тайлангаас хайх")) as HTMLInputElement;
    const rulesText = document.querySelector("[data-rules-text]") as HTMLElement;
    expect(rulesText.textContent).toBe("Бүртгэлийн огноо");
    search.focus();

    act(() => navigateTo?.("/reports/staff/?layout=board&q=b"));

    // The layout is inert while b loads; the search box and the rules line are not, and keep the focus.
    expect(screen.getByText("Лане карт").closest("[inert]")).not.toBeNull();
    expect(search.closest("[inert]")).toBeNull();
    expect(rulesText.closest("[inert]")).toBeNull();
    expect(document.activeElement).toBe(search);

    await act(async () => {
      releaseB(jsonResponse(200, layoutAnswer("board", { query: "q=b" })));
    });
    expect(await screen.findByText("Лане карт")).toBeTruthy();
    expect(document.querySelector("[inert]")).toBeNull();
  });

  it("a layout change navigates once and shows the new layout", async () => {
    const withSelect = barFixture();
    const layoutBar = {
      keep: [["q", "a"]],
      layout: "board",
      selects: [
        {
          label: "Ангилал",
          name: "lby",
          selected: "dept",
          options: [opt("dept", "Алба"), opt("branch", "Салбар")],
        },
      ],
    };
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.pathname !== "/api/v1/reports/staff") return Promise.resolve(jsonResponse(404, {}));
      if (url.searchParams.get("lby") === "branch") {
        const board = layoutPage("board", { bar: { ...layoutBar, selects: [{ ...layoutBar.selects[0], selected: "branch" }] } });
        const next = {
          ...board,
          board: {
            cap: 200,
            lanes: [{ cards: [card("Салбарын карт")], count: 1, figure: "", href: "", label: "Улаанбаатар" }],
            shown: 1,
            total: 1,
            value_label: "",
          },
        };
        return Promise.resolve(jsonResponse(200, { ...layoutAnswer("board"), bar: withSelect, layout_page: next }));
      }
      return Promise.resolve(jsonResponse(200, { ...layoutAnswer("board"), bar: withSelect, layout_page: layoutPage("board", { bar: layoutBar }) }));
    });

    renderPage("/reports/staff/?layout=board&q=a");
    await screen.findByText("Лане карт");
    fireEvent.change(document.querySelector('select[name="lby"]') as HTMLSelectElement, { target: { value: "branch" } });

    expect(where()).toBe("/reports/staff/?q=a&lby=branch");
    expect(screen.getByTestId("nav").textContent).toBe("PUSH");
    expect(await screen.findByText("Салбарын карт")).toBeTruthy();
    expect(screen.queryByText("Лане карт")).toBeNull();
    // The new address was asked once.
    expect(pageUrls().filter((url) => url.searchParams.get("lby") === "branch").length).toBe(1);
  });

  it("the back button restores the previous layout", async () => {
    // A board with a layout bar: the select's value is the address's lby parameter, so each address has its own board.
    const selectBar = (selected: string) => ({
      keep: [["q", "a"]],
      layout: "board",
      selects: [{ label: "Ангилал", name: "lby", selected, options: [opt("dept", "Алба"), opt("branch", "Салбар")] }],
    });
    const boardWith = (title: string) => ({
      cap: 200,
      lanes: [{ cards: [card(title)], count: 1, figure: "", href: "", label: "Санхүү" }],
      shown: 1,
      total: 1,
      value_label: "",
    });
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      if (url.searchParams.get("lby") === "branch") {
        return jsonResponse(
          200,
          layoutAnswer("board", { bar: selectBar("branch"), board: boardWith("Салбарын карт"), query: "layout=board&q=a&lby=branch" }),
        );
      }
      return jsonResponse(
        200,
        layoutAnswer("board", { bar: selectBar("dept"), board: boardWith("Лане карт"), query: "layout=board&q=a" }),
      );
    });

    renderPage("/reports/staff/?layout=board&q=a");
    await screen.findByText("Лане карт");
    fireEvent.change(document.querySelector('select[name="lby"]') as HTMLSelectElement, { target: { value: "branch" } });
    expect(await screen.findByText("Салбарын карт")).toBeTruthy();
    expect(where()).toBe("/reports/staff/?layout=board&q=a&lby=branch");

    // The back button: a POP to the address before the change, which shows its own layout again.
    act(() => navigateTo?.(-1));
    await waitFor(() => expect(where()).toBe("/reports/staff/?layout=board&q=a"));
    expect(screen.getByTestId("nav").textContent).toBe("POP");
    expect(await screen.findByText("Лане карт")).toBeTruthy();
    expect(screen.queryByText("Салбарын карт")).toBeNull();
  });

  it("table layout is unchanged: the table, its rules line and no layout bar", async () => {
    answer(() =>
      jsonResponse(200, {
        bar: barFixture(),
        head: headFixture(),
        layout: "table",
        layout_page: null,
        redirect: "",
        table: {
          address: "/reports/staff/",
          check_css: "",
          check_style: "",
          clear_rules_url: "/reports/staff/?q=a&rules=",
          count: 1,
          footer: null,
          groups: [{ label: "", count: 1, rows: [[{ value: "Бат", text: "Бат", money: false, href: "", css: "", style: "", person: 0 }]] }],
          heads: [{ label: "Нэр", href: "/reports/staff/?sort=name", append_href: "", arrow: "", css: "", sticky_left: "" }],
          next_offset: null,
          note: "",
          pin: 0,
          query: "q=a",
          rules_text: "Бүртгэлийн огноо",
          selectable: false,
          shows_count: true,
          table_span: 1,
        },
        title: "Ажилчдын жагсаалт",
      }),
    );
    renderPage("/reports/staff/?q=a");

    expect(await screen.findByText("Бат")).toBeTruthy();
    expect(document.querySelector("[data-rules-text]")?.textContent).toBe("Бүртгэлийн огноо");
    expect(screen.queryByRole("form", { name: "Харагдацын багана" })).toBeNull();
    expect(screen.queryByText("Энэ харагдацыг хуучин хуудсанд нээх")).toBeNull();
  });

  it("unknown kind and a missing payload render the Django link fallback", async () => {
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      if (url.searchParams.get("layout") === "heatmap") {
        return jsonResponse(200, layoutAnswer("heatmap", {}, null));
      }
      // A known kind whose payload is missing (its board is null).
      return jsonResponse(200, { ...layoutAnswer("board"), layout_page: layoutPage("board", { board: null }) });
    });

    renderPage("/reports/staff/?layout=heatmap&q=a");
    const link = await screen.findByText("Энэ харагдацыг хуучин хуудсанд нээх");
    expect(link.closest("a")?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/?layout=heatmap&q=a");

    // The same fallback for a known kind without its payload.
    cleanup();
    renderPage("/reports/staff/?layout=board&q=a");
    const again = await screen.findByText("Энэ харагдацыг хуучин хуудсанд нээх");
    expect(again.closest("a")?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/?layout=board&q=a");
  });

  it("rules text and note come from layout_page", async () => {
    answer(() =>
      jsonResponse(
        200,
        layoutAnswer("pivot", {
          rules_text: "Огнооны муж",
          note: "Тэмдэглэл: зөвхөн идэвхтэй",
          count: 9,
          clear_rules_url: "/reports/staff/?q=a&rules=&layout=pivot",
        }),
      ),
    );
    renderPage("/reports/staff/?layout=pivot&q=a");

    expect(await screen.findByText("Тэмдэглэл: зөвхөн идэвхтэй")).toBeTruthy();
    const rulesLine = (document.querySelector("[data-rules-text]") as HTMLElement).closest("p");
    expect(rulesLine?.textContent).toBe("Нөхцөл: Огнооны муж · Засах · Цэвэрлэх");
    expect(rulesLine?.querySelector("a")?.getAttribute("href")).toBe("/reports/staff/?q=a&rules=&layout=pivot");
    expect(screen.getByText("Нийт: 9")).toBeTruthy();
  });
});

// The same-report links (the address of this report, not the person or entry pages) stay inside the app: none is sent to
// the legacy origin. The Django fallback is the control: it does go there.
describe("same-report links", () => {
  const legacy = "http://legacy.test";

  function hrefs(): string[] {
    return Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
  }

  it("same-report links stay inside the app", async () => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", legacy);
    try {
      const day = {
        entries: [],
        in_month: true,
        is_today: false,
        iso: "2026-05-04",
        more: 2,
        more_href: "/reports/staff/?layout=calendar&lday=2026-05-04",
        number: 4,
      };
      const cases: Array<[string, Partial<ReportLayoutPageOut>, string]> = [
        [
          "calendar",
          {
            calendar: {
              ...payloadFor("calendar").calendar!,
              prev_href: "/reports/staff/?layout=calendar&lmonth=2026-04",
              next_href: "/reports/staff/?layout=calendar&lmonth=2026-06",
              today_href: "/reports/staff/?layout=calendar",
              switch_href: "/reports/staff/?layout=calendar&lweek=2026-05-04",
              weeks: [[day]],
            },
          },
          "/reports/staff/?layout=calendar&lmonth=2026-04",
        ],
        [
          "timeline",
          {
            timeline: {
              ...payloadFor("timeline").timeline!,
              all_href: "/reports/staff/?layout=timeline&lyear=all",
              enter_href: "/reports/staff/?layout=timeline&lyear=2026",
              year_prev_href: "/reports/staff/?layout=timeline&lyear=2025",
              year_next_href: "/reports/staff/?layout=timeline&lyear=2027",
            },
          },
          "/reports/staff/?layout=timeline&lyear=2025",
        ],
        [
          "board",
          {
            board: {
              cap: 200,
              lanes: [
                {
                  cards: [card("Карт")],
                  count: 1,
                  figure: "",
                  href: "/reports/staff/?layout=board&lby=branch",
                  label: "Санхүү",
                },
              ],
              shown: 1,
              total: 1,
              value_label: "",
            },
          },
          "/reports/staff/?layout=board&lby=branch",
        ],
        [
          "chart",
          {
            chart: {
              ...payloadFor("chart").chart!,
              rows: [{ label: "Санхүү", href: "/reports/staff/?lby=dept&lby_v=fin", cells: [], total: "3,000₮" }],
            },
          },
          "/reports/staff/?lby=dept&lby_v=fin",
        ],
        [
          "pivot",
          {
            pivot: {
              grids: [
                {
                  caption: "Цалин",
                  col_heads: [{ label: "2026", href: "/reports/staff/?layout=pivot&lcol=2026" }],
                  col_totals: [],
                  corner_label: "Алба",
                  empty: false,
                  grand: "",
                  masked: false,
                  note: "",
                  rows: [
                    {
                      label: "Санхүү",
                      href: "/reports/staff/?layout=pivot&lrow=fin",
                      cells: [{ text: "5", href: "/reports/staff/?layout=pivot&lcell=fin" }],
                      total: "5",
                    },
                  ],
                },
              ],
            },
          },
          "/reports/staff/?layout=pivot&lrow=fin",
        ],
      ];

      for (const [kind, override, expected] of cases) {
        cleanup();
        answer(() => jsonResponse(200, layoutAnswer(kind, override)));
        renderPage(`/reports/staff/?layout=${kind}&q=a`);
        await waitFor(() => expect(hrefs()).toContain(expected));
        // No anchor on the page goes to the legacy origin: the report's own addresses are relative.
        expect(hrefs().filter((href) => href.startsWith(legacy))).toEqual([]);
      }
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("the Django fallback link does go to the legacy origin (control)", async () => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", legacy);
    try {
      answer(() => jsonResponse(200, layoutAnswer("heatmap", {}, null)));
      renderPage("/reports/staff/?layout=heatmap&q=a");
      const link = await screen.findByText("Энэ харагдацыг хуучин хуудсанд нээх");
      expect(link.closest("a")?.getAttribute("href")?.startsWith(legacy + "/")).toBe(true);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
