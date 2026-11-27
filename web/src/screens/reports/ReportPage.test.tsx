// The harness is imported first: it stubs fetch before ../../api/client (and so ../../api/reports) load.
import { fetchMock, jsonResponse, metaBody, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useNavigationType,
  type NavigateFunction,
} from "react-router";
import { setCsrf } from "../../api/client";
import type { components } from "../../api/schema";
import { legacyOrigin } from "../../lib/AppLink";
import { ReportPage } from "./ReportPage";

// The rules and saved-view pop-ups are stubbed: each stub names the pop-up, the address or target it got, and closes.
vi.mock("./popups/RulesModal", async () => {
  const { createElement } = await import("react");
  return {
    RulesModal: (props: { query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "rules", "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/SavedViewModal", async () => {
  const { createElement } = await import("react");
  return {
    SavedViewModal: (props: { target: unknown; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "saved", "data-target": JSON.stringify(props.target) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});

// The columns pop-up is stubbed: its stub applies by navigating to a new address, then closing, as the real pop-up does.
vi.mock("./popups/ColumnsModal", async () => {
  const { createElement } = await import("react");
  const { useNavigate } = await import("react-router");
  return {
    ColumnsModal: (props: { onClose: () => void }) => {
      const navigate = useNavigate();
      return createElement(
        "div",
        { role: "dialog", "data-pop": "columns" },
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              navigate("/reports/staff/?cols=name");
              props.onClose();
            },
          },
          "stub-apply",
        ),
      );
    },
  };
});

type ReportPageOut = components["schemas"]["ReportPageOut"];
type ReportBarOut = components["schemas"]["ReportBarOut"];
type ReportHeadOut = components["schemas"]["ReportHeadOut"];
type ReportTableOut = components["schemas"]["ReportTableOut"];
type ReportCellOut = components["schemas"]["ReportCellOut"];

const opt = (value: string, label: string) => ({ value, label });

// The bar as the API sends it (the option lists the filter controls read; the same shape as FilterBar.test).
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

function cell(value: string): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0, edit: null };
}

function tableFixture(overrides: Partial<ReportTableOut> = {}): ReportTableOut {
  return {
    address: "/reports/staff/",
    check_css: "",
    check_style: "",
    clear_rules_url: "/reports/staff/?q=a&rules=",
    count: 1,
    footer: null,
    groups: [{ label: "", count: 1, rows: [[cell("Бат")]] }],
    heads: [{ label: "Нэр", href: "/reports/staff/?sort=name", append_href: "", arrow: "", css: "", sticky_left: "" }],
    next_offset: null,
    note: "",
    pin: 0,
    query: "q=a",
    rules_text: "",
    selectable: false,
    shows_count: true,
    table_span: 1,
    ...overrides,
  } as ReportTableOut;
}

// A page answer for a table layout, with the rows and the cleaned query given.
function tablePage(table: Partial<ReportTableOut> = {}, head: Partial<ReportHeadOut> = {}): ReportPageOut {
  return {
    bar: barFixture(),
    head: headFixture(head),
    layout: "table",
    layout_page: null,
    redirect: "",
    table: tableFixture(table),
    title: "Ажилчдын жагсаалт",
  };
}

// Answers every request by its URL. The page is `/api/v1/reports/<key>`; its rows are `/api/v1/reports/<key>/rows`.
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

// Shows the router's address, so a test can read where a redirect or a click went.
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

describe("ReportPage", () => {
  it("redirect_navigates_once_and_view_plain_does_not_loop", async () => {
    // A bare address with a default saved view is answered with the view's address. The view's own address is held
    // until the test releases it, so the page can be seen while it follows the redirect.
    let releaseView: (response: Response) => void = () => {};
    const heldView = new Promise<Response>((resolve) => {
      releaseView = resolve;
    });
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.pathname !== "/api/v1/reports/staff") return Promise.resolve(jsonResponse(404, {}));
      if (!url.searchParams.has("view")) {
        return Promise.resolve(
          jsonResponse(200, { ...tablePage(), redirect: "/reports/staff/?view=5", table: null, head: null, bar: null }),
        );
      }
      return heldView;
    });

    const first = renderPage("/reports/staff/");
    await waitFor(() => expect(where()).toBe("/reports/staff/?view=5"));
    // The redirect replaced the bare address (no new history entry), and nothing is drawn while its target loads.
    expect(screen.getByTestId("nav").textContent).toBe("REPLACE");
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByText("Бат")).toBeNull();

    await act(async () => {
      releaseView(jsonResponse(200, tablePage()));
    });
    await waitFor(() => expect(screen.getByText("Бат")).toBeTruthy());
    // The bare address was asked once: the redirect was followed once, not again.
    expect(pageUrls().filter((url) => !url.searchParams.has("view")).length).toBe(1);
    first.unmount();

    // view=plain is answered with the table (the server gives no redirect for it): the address stays where it is.
    resetFetch();
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      return jsonResponse(200, tablePage({ query: "view=plain" }));
    });
    renderPage("/reports/staff/?view=plain");
    await waitFor(() => expect(screen.getByText("Бат")).toBeTruthy());
    expect(where()).toBe("/reports/staff/?view=plain");
    expect(pageUrls().length).toBe(1);
  });

  it("other_layout_shows_notice_and_legacy_link", async () => {
    answer(() =>
      jsonResponse(200, {
        bar: barFixture(),
        head: headFixture({ tools: { columns: false, rules: false, format: false } }),
        layout: "cards",
        redirect: "",
        table: null,
        title: "Ажилчдын жагсаалт",
      }),
    );
    renderPage("/reports/staff/?layout=cards");

    const link = await screen.findByText("Энэ харагдацыг хуучин хуудсанд нээх");
    expect(link.closest("a")?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/?layout=cards");
    expect(screen.queryByText("Бат")).toBeNull();
  });

  it("404_shows_not_found", async () => {
    answer(() => jsonResponse(404, { code: "not_found" }));
    renderPage("/reports/nope/");
    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
  });

  it("403_shows_forbidden", async () => {
    answer(() => jsonResponse(403, { code: "forbidden" }));
    renderPage("/reports/staff/");
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("stale_rows_inert_while_new_query_loads", async () => {
    let releaseB: (response: Response) => void = () => {};
    const pendingB = new Promise<Response>((resolve) => {
      releaseB = resolve;
    });
    // The address b waits until the test releases it; a answers at once.
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.searchParams.get("q") === "b") return pendingB;
      return Promise.resolve(jsonResponse(200, tablePage({ query: "q=a" })));
    });

    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    act(() => navigateTo?.("/reports/staff/?q=b"));
    // While b loads, a's row stays on screen, inert and busy.
    const stale = screen.getByText("Бат").closest("[aria-busy]");
    expect(stale?.getAttribute("aria-busy")).toBe("true");
    expect(stale?.hasAttribute("inert")).toBe(true);

    await act(async () => {
      releaseB(
        jsonResponse(
          200,
          tablePage({
            query: "q=b",
            count: 1,
            groups: [{ label: "", count: 1, rows: [[cell("Сарнай")]] }],
          }),
        ),
      );
    });
    expect(await screen.findByText("Сарнай")).toBeTruthy();
    expect(screen.queryByText("Бат")).toBeNull();
    expect(document.querySelector("[inert]")).toBeNull();
    expect(document.querySelector("[aria-busy]")).toBeNull();
  });

  it("filter_bar_stays_live_while_a_new_address_loads", async () => {
    let releaseB: (response: Response) => void = () => {};
    const pendingB = new Promise<Response>((resolve) => {
      releaseB = resolve;
    });
    const groupBar = barFixture({
      options: { ...barFixture().options, group_choices: [opt("name", "Нэр")] },
    } as Partial<ReportBarOut>);
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.searchParams.get("q") === "b") return pendingB;
      return Promise.resolve(jsonResponse(200, { ...tablePage({ query: "q=a" }), bar: groupBar }));
    });

    renderPage("/reports/staff/?q=a");
    const search = (await screen.findByLabelText("Тайлангаас хайх")) as HTMLInputElement;
    const group = document.querySelector('select[name="group"]');
    expect(group).not.toBeNull();
    search.focus();

    act(() => navigateTo?.("/reports/staff/?q=b"));

    // The table is inert while b loads; the search box, the group select and the form are not, and keep the focus.
    expect(screen.getByText("Бат").closest("[inert]")).not.toBeNull();
    expect(search.closest("[inert]")).toBeNull();
    expect(group?.closest("[inert]")).toBeNull();
    expect(document.querySelector("#report-filters")?.closest("[inert]")).toBeNull();
    expect(document.activeElement).toBe(search);

    await act(async () => {
      releaseB(jsonResponse(200, { ...tablePage({ query: "q=b" }), bar: groupBar }));
    });
    expect(await screen.findByText("Бат")).toBeTruthy();
  });

  it("edits_compose_while_a_new_address_loads", async () => {
    // The branch change is held: the page is loading its address while the state change is made.
    let releaseBranch: (response: Response) => void = () => {};
    const heldBranch = new Promise<Response>((resolve) => {
      releaseBranch = resolve;
    });
    const filtersBar = barFixture({ items: [{ name: "branch", remove: "" }, { name: "state", remove: "" }] });
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.searchParams.get("branch") === "6") return heldBranch;
      return Promise.resolve(jsonResponse(200, { ...tablePage({ query: "q=a" }), bar: filtersBar }));
    });

    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");
    fireEvent.change(screen.getByLabelText("Салбар"), { target: { value: "6" } });
    expect(where()).toBe("/reports/staff/?q=a&branch=6");

    // The branch address has not answered yet: the state change still keeps the branch.
    fireEvent.change(screen.getByLabelText("Төлөв"), { target: { value: "all" } });
    expect(where()).toBe("/reports/staff/?q=a&branch=6&state=all");

    await act(async () => {
      releaseBranch(jsonResponse(200, { ...tablePage({ query: "q=a" }), bar: filtersBar }));
    });
  });

  it("rules_line_shows_text_and_clear_link", async () => {
    answer(() => jsonResponse(200, tablePage({ rules_text: "Бүртгэлийн огноо" })));
    renderPage("/reports/staff/?q=a");

    // The sticky strip repeats the rules text as a chip, so the line's own text is picked by its data attribute.
    await screen.findAllByText("Бүртгэлийн огноо");
    const text = document.querySelector("[data-rules-text]") as HTMLElement;
    expect(text.textContent).toBe("Бүртгэлийн огноо");
    const rulesLine = text.closest("p");
    expect(rulesLine?.textContent).toBe("Нөхцөл: Бүртгэлийн огноо · Засах · Цэвэрлэх");
    // «Засах» on the line opens the same rules pop-up as the ribbon's «Шүүлтүүр», with the page's address.
    const edit = within(rulesLine as HTMLElement).getByText("Засах");
    expect(edit.tagName).toBe("BUTTON");
    fireEvent.click(edit);
    expect(document.querySelector('[data-pop="rules"]')?.getAttribute("data-query")).toBe("q=a");
    fireEvent.click(screen.getByText("stub-close"));
    expect(document.querySelector('[data-pop="rules"]')).toBeNull();

    // The filter bar has its own «Цэвэрлэх»; the rules line's one is the link inside the line.
    const clear = within(rulesLine as HTMLElement).getByText("Цэвэрлэх");
    expect(clear.getAttribute("href")).toBe("/reports/staff/?q=a&rules=");
    fireEvent.click(clear);
    expect(where()).toBe("/reports/staff/?q=a&rules=");
  });

  it("note_and_count_lines", async () => {
    answer(() => jsonResponse(200, tablePage({ note: "Тайлбар: зөвхөн идэвхтэй ажилчид", count: 7 })));
    renderPage("/reports/staff/?q=a");

    expect(await screen.findByText("Тайлбар: зөвхөн идэвхтэй ажилчид")).toBeTruthy();
    expect(screen.getByText("Нийт: 7")).toBeTruthy();
  });

  it("filter_bar_receives_cleaned_query", async () => {
    // The address says «Бар»; the API's cleaned query says «Бат». The search box shows the cleaned value.
    answer(() => jsonResponse(200, tablePage({ query: "q=%D0%91%D0%B0%D1%82" })));
    renderPage("/reports/staff/?q=%D0%91%D0%B0%D1%80");

    const search = (await screen.findByLabelText("Тайлангаас хайх")) as HTMLInputElement;
    expect(search.value).toBe("Бат");
  });

  it("redirect_has_priority_over_memory", async () => {
    // The user has a remembered setup. A plain visit to the bare address is answered with the default view's address:
    // the page follows that redirect, and the remembered setup is not applied on top of it.
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.pathname === "/api/v1/meta") {
        return Promise.resolve(jsonResponse(200, { ...metaBody(""), user: { id: 7 } }));
      }
      if (url.pathname !== "/api/v1/reports/staff") return Promise.resolve(jsonResponse(404, {}));
      // The page request always carries offset=0, so the bare address is the one with no view and no search.
      if (!url.searchParams.has("view") && !url.searchParams.has("q")) {
        return Promise.resolve(
          jsonResponse(200, { ...tablePage(), redirect: "/reports/staff/?view=5", table: null, head: null, bar: null }),
        );
      }
      return Promise.resolve(jsonResponse(200, tablePage()));
    });

    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");
    localStorage.setItem("hr.reportQuery.u7.staff", "?order_type=1");
    act(() => navigateTo?.("/reports/staff/"));

    await waitFor(() => expect(where()).toBe("/reports/staff/?view=5"));
    await screen.findByText("Бат");
    const asked = fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url));
    expect(asked.some((url) => url.searchParams.has("order_type"))).toBe(false);
    expect(where()).toBe("/reports/staff/?view=5");
  });

  it("remembered_address_replaces_bare_answer_without_drawing_it", async () => {
    // The bare address answers with no redirect and the user has a remembered setup. The unfiltered rows are never
    // drawn: the remembered address is requested and replaces the bare address once.
    fetchMock.mockImplementation((input: Request) => {
      const url = new URL(input.url);
      if (url.pathname === "/api/v1/meta") {
        return Promise.resolve(jsonResponse(200, { ...metaBody(""), user: { id: 7 } }));
      }
      if (url.pathname !== "/api/v1/reports/staff") return Promise.resolve(jsonResponse(404, {}));
      if (url.searchParams.has("order_type")) {
        return Promise.resolve(
          jsonResponse(200, tablePage({ query: "order_type=1", groups: [{ label: "", count: 1, rows: [[cell("Сарнай")]] }] })),
        );
      }
      if (url.searchParams.has("q")) {
        return Promise.resolve(
          jsonResponse(200, tablePage({ query: "q=a", groups: [{ label: "", count: 1, rows: [[cell("Анх")]] }] })),
        );
      }
      // The bare address: its own rows, which must not be drawn while the restore is pending.
      return Promise.resolve(jsonResponse(200, tablePage()));
    });

    renderPage("/reports/staff/?q=a");
    await screen.findByText("Анх");
    localStorage.setItem("hr.reportQuery.u7.staff", "?order_type=1");

    let bareDrawn = false;
    const locations: string[] = [];
    const observer = new MutationObserver(() => {
      if ((document.body.textContent ?? "").includes("Бат")) bareDrawn = true;
      if (locations[locations.length - 1] !== where()) locations.push(where());
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });

    act(() => navigateTo?.("/reports/staff/"));
    await screen.findByText("Сарнай");
    await waitFor(() => expect(where()).toBe("/reports/staff/?order_type=1"));
    observer.disconnect();
    if (locations[locations.length - 1] !== where()) locations.push(where());

    expect(bareDrawn).toBe(false);
    // The bare address is shown only as the address the router moved through, then the remembered one replaces it.
    expect(locations).toEqual(["/reports/staff/", "/reports/staff/?order_type=1"]);
    // The bare address was asked once; the remembered address once.
    const asked = pageUrls();
    expect(asked.filter((url) => !url.searchParams.has("order_type") && !url.searchParams.has("q")).length).toBe(1);
    expect(asked.filter((url) => url.searchParams.has("order_type")).length).toBe(1);
  });

  it("bare_without_saved_query_draws_its_answer_at_once", async () => {
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      if (url.searchParams.has("q")) {
        return jsonResponse(200, tablePage({ groups: [{ label: "", count: 1, rows: [[cell("Анх")]] }] }));
      }
      return jsonResponse(200, tablePage());
    });
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Анх");
    act(() => navigateTo?.("/reports/staff/"));
    // The bare answer ("Бат") is drawn at once, and nothing replaces the address.
    expect(await screen.findByText("Бат")).toBeTruthy();
    expect(where()).toBe("/reports/staff/");
  });

  it("apply_in_modal_changes_address_and_closes", async () => {
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      return jsonResponse(200, tablePage({}, { tools: { columns: true, rules: false, format: false } }));
    });
    renderPage("/reports/staff/?q=a&offset=40");
    await screen.findByText("Бат");

    // The strip has a «Багана» button too (hidden until scrolled): the ribbon's one is the page's tool.
    fireEvent.click(document.querySelector<HTMLButtonElement>('button[data-tool="columns"]')!);
    expect(document.querySelector('[data-pop="columns"]')).not.toBeNull();

    fireEvent.click(screen.getByText("stub-apply"));
    expect(where()).toBe("/reports/staff/?cols=name");
    expect(document.querySelector('[data-pop="columns"]')).toBeNull();
  });

  it("save_on_a_non_table_layout_gets_the_address_query", async () => {
    // A cards layout has no table, so the table's cleaned query is absent: «Хадгалах» saves the address without offset.
    const saved = {
      can_edit_view: false,
      current_view: null,
      options: [],
      plain_url: "/reports/staff/",
      template_current: false,
      templates: [],
    };
    answer((url) => {
      if (url.pathname !== "/api/v1/reports/staff") return jsonResponse(404, {});
      return jsonResponse(200, {
        bar: barFixture(),
        head: headFixture({ saved }),
        layout: "cards",
        redirect: "",
        table: null,
        title: "Ажилчдын жагсаалт",
      });
    });
    renderPage("/reports/staff/?q=a&offset=40");
    fireEvent.click(await screen.findByText("Хадгалах", { selector: "button" }));

    expect(JSON.parse(document.querySelector('[data-pop="saved"]')?.getAttribute("data-target") ?? "null")).toEqual({
      mode: "new",
      query: "q=a",
    });
  });
});

// A person cell: the first cell of a row carries the person id the selection ticks.
function personCell(text: string, person: number): ReportCellOut {
  return { value: text, text, money: false, href: "", css: "", style: "", person, edit: null };
}

// The head of a selectable report: the selection urls and cap the API sends, and the export links.
function selectableHead(overrides: Partial<ReportHeadOut> = {}): Partial<ReportHeadOut> {
  return {
    excel_url: "/api/v1/reports/staff/excel?q=a",
    print_url: "/reports/staff/print/?q=a",
    selectable: true,
    selection_max: 500,
    selection_urls: { excel: "/x/excel", csv: "/x/csv", print: "/x/print", copy: "/x/copy", checklist: "" },
    ...overrides,
  };
}

// A table of two people (ids 7 and 9), with a batch still to come when `next` is given.
function peopleTable(overrides: Partial<ReportTableOut> = {}): Partial<ReportTableOut> {
  return {
    selectable: true,
    count: 2,
    groups: [
      {
        label: "",
        count: 2,
        rows: [[personCell("Бат", 7)], [personCell("Номин", 9)]],
      },
    ],
    ...overrides,
  };
}

function toggle(): HTMLElement | null {
  return screen.queryByText("Сонгох", { selector: "button" });
}

function rowBox(index: number): HTMLInputElement {
  return document.querySelectorAll<HTMLInputElement>("input[data-select-row]")[index];
}

function pickedCount(): string {
  return document.querySelector("#selection-bar [data-count]")?.textContent ?? "";
}

describe("ReportPage row selection", () => {
  it("select_toggle_only_when_the_report_is_selectable", async () => {
    answer(() => jsonResponse(200, tablePage()));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");
    expect(toggle()).toBeNull();
  });

  it("the_toggle_shows_the_bar_and_checkboxes", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    fireEvent.click(toggle()!);
    expect(toggle()!.getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector("#selection-bar")).not.toBeNull();
    expect(pickedCount()).toBe("0");
    expect(document.querySelectorAll("input[data-select-row]").length).toBe(2);
    expect(document.body.dataset.selecting).toBe("1");
  });

  it("the_second_press_turns_the_mode_off_and_clears_the_picks", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    fireEvent.click(toggle()!);
    fireEvent.click(rowBox(0));
    expect(pickedCount()).toBe("1");

    fireEvent.click(toggle()!);
    expect(toggle()!.getAttribute("aria-pressed")).toBe("false");
    expect(document.querySelector("#selection-bar")).toBeNull();
    expect(document.querySelectorAll("tbody tr.is-picked").length).toBe(0);
    expect(document.body.dataset.selecting).toBeUndefined();

    fireEvent.click(toggle()!);
    expect(pickedCount()).toBe("0");
  });

  it("a_filter_change_ends_the_mode_and_clears_the_picks", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    fireEvent.click(toggle()!);
    fireEvent.click(rowBox(1));
    expect(pickedCount()).toBe("1");

    act(() => navigateTo!("/reports/staff/?q=b"));
    await waitFor(() => expect(toggle()!.getAttribute("aria-pressed")).toBe("false"));
    expect(document.querySelector("#selection-bar")).toBeNull();
    expect(document.querySelector("tbody tr[data-person='9']")!.classList.contains("is-picked")).toBe(false);
  });

  it("loading_the_next_batch_keeps_the_picks", async () => {
    answer((url) => {
      if (url.pathname === "/api/v1/reports/staff/rows") {
        return jsonResponse(200, { groups: [{ label: "", count: 1, rows: [[personCell("Дорж", 11)]] }], next_offset: null });
      }
      return jsonResponse(200, tablePage(peopleTable({ count: 3, next_offset: 2 }), selectableHead()));
    });
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    fireEvent.click(toggle()!);
    fireEvent.click(rowBox(0));
    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));

    await screen.findByText("Дорж");
    expect(document.querySelector("tbody tr[data-person='7']")!.classList.contains("is-picked")).toBe(true);
    expect(pickedCount()).toBe("1");
  });

  it("the_print_link_opens_in_a_new_tab_with_the_address_query", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    const print = screen.getByText("Хэвлэх").closest("a");
    expect(print?.getAttribute("href")).toBe("/reports/staff/print/?q=a");
    expect(print?.getAttribute("target")).toBe("_blank");
    expect(print?.getAttribute("rel")).toBe("noopener");
  });

  it("the_excel_link_points_at_the_api_with_the_same_query", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");

    expect(screen.getByText("Excel").closest("a")?.getAttribute("href")).toBe("/api/v1/reports/staff/excel?q=a");
  });

  it("no_toggle_on_a_non_table_layout", async () => {
    answer(() =>
      jsonResponse(200, {
        bar: barFixture(),
        head: headFixture({ selectable: true, selection_max: 500, selection_urls: {} }),
        layout: "cards",
        redirect: "",
        table: null,
        title: "Ажилчдын жагсаалт",
      }),
    );
    renderPage("/reports/staff/?layout=cards");
    await screen.findByText("Энэ харагдацыг хуучин хуудсанд нээх");
    expect(toggle()).toBeNull();
    expect(document.querySelector("input[data-select-row]")).toBeNull();
  });

  it("the_report_page_id_is_on_the_page_once", async () => {
    answer(() => jsonResponse(200, tablePage(peopleTable(), selectableHead())));
    renderPage("/reports/staff/?q=a");
    await screen.findByText("Бат");
    expect(document.querySelectorAll("#report-page").length).toBe(1);
  });
});
