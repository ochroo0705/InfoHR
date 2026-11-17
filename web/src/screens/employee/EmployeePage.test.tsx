import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { MainWidthContext } from "../../shell/mainWidth";
import { EmployeePage } from "./EmployeePage";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created). Relative URLs
// resolve against the page, as in api/employee.test.tsx.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// A header as the API sends it. Each test overrides only what it checks.
function head(overrides: Partial<EmployeeHeadOut> = {}): EmployeeHeadOut {
  return {
    activity_count: 12,
    can: {
      create_login: false,
      manage: false,
      manage_salary: false,
      record_leave: false,
      view_personal: true,
      view_salary: true,
    },
    code: "E-001",
    email: "",
    event_menu: [],
    facts: {
      contract_end: "",
      department: "Хүний нөөц",
      employee_type: "Үндсэн ажилтан",
      first_hire_date: "2024-01-01",
      manager: "Сарнай Дорж",
      manager_label: "E-002 Сарнай Дорж",
      position: "Мэргэжилтэн",
      position_line: "Мэргэжилтэн · Хүний нөөц",
      work_phone: "7700-1234",
    },
    family_name: "Бат",
    full_name: "Бат Болд",
    given_initial: "Б",
    given_name: "Болд",
    latest_activity: null,
    leave_left: null,
    next_event: null,
    one_time_login: null,
    photo_srcset: "",
    photo_url: "",
    pk: 7,
    setup: null,
    state: { key: "active", label: "Ажиллаж байгаа", tone: "state-active" },
    ...overrides,
  } as EmployeeHeadOut;
}

// The Work tab's payload with every field the Work components read, all empty. The page tests check the header and rail.
function emptyWork() {
  const field = { kind: "text", value: "", choice: "", text: "—" };
  const none = { visible: false, configured: false, start_missing: false, periods: [], old_count: 0, fold_old: false, fold_show_label: "", fold_hide_label: "", no_year_started: false, nowhere: [], old_absences: [], can_record: false, can_manage_settings: false, settings_url: "", all_leaves_url: "" };
  return {
    order_warning: "", can_manage: false, transfer_chip: false, contract_chip: false,
    position: "", department: "", manager: "", second_position: field, office: field, section: field, branch: field,
    employee_type: "", contract_type: "", contract_no: "", contract_start: "", contract_end: "", contract_end_label: "",
    probation_end: field, first_hire_date: null, job_type: field, job_figure: field, work_conditions: field,
    work_schedule: field, sector_years: field, macs_contract_no: "", macs_contract_period: "", macs_taken_leave: "",
    macs_leave_type: "", macs_probation_months: "", macs_last_order_no: "", macs_last_order_text: "", waiting: [],
    jobs: [], orders_count: 0, orders: [], leave: none, checklist_visible: false, checklists: [],
  };
}

// The Salary payload with no pay, no history and an empty bank block (the Salary request gets it).
function emptySalary() {
  return {
    current: null, missing_label: "тогтоогоогүй", rows: [], has_rows: false, can_set: false, set_label: "",
    editable: false, bank_fields: [],
  };
}

// Answers GET /api/v1/employees/<pk> with the given status and body. The Work request gets the empty Work payload.
function answerHead(status: number, body: unknown) {
  fetchMock.mockImplementation(async (input: Request | string) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.endsWith("/work")) return jsonResponse(200, emptyWork());
    if (url.endsWith("/salary")) return jsonResponse(200, emptySalary());
    if (url.endsWith("/personal")) return jsonResponse(200, emptyPersonal());
    return jsonResponse(status, body);
  });
}

function emptyPersonal() {
  return { editable: false, groups: [], counts: {}, sections: [], lists: [] };
}

function renderAt(path: string, client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MainWidthContext.Provider value={() => undefined}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/employees/:pk/" element={<EmployeePage />} />
            <Route path="*" element={<p>other route</p>} />
          </Routes>
        </MemoryRouter>
      </MainWidthContext.Provider>
    </QueryClientProvider>,
  );
}

function newClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("EmployeePage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.mocked(openLegacyEmployee).mockClear();
    document.title = "Initial";
  });

  afterEach(() => {
    cleanup();
  });

  it("a 404 from the API renders the 404 screen", async () => {
    answerHead(404, { form_errors: ["Not found"], code: "not_found" });
    renderAt("/employees/7/", newClient());
    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
  });

  it("a non-numeric pk renders the 404 screen without asking the API", () => {
    renderAt("/employees/abc/", newClient());
    expect(screen.getByText("Хуудас олдсонгүй")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sets the document title to the employee's full name", async () => {
    answerHead(200, head());
    renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(document.title).toBe("Бат Болд · MACS Human Capital");
  });

  it("the employee query has gcTime 0 and no refetch on window focus", async () => {
    answerHead(200, head());
    const client = newClient();
    renderAt("/employees/7/", client);
    await screen.findByRole("heading", { name: "Ажил" });
    const query = client.getQueryCache().find({ queryKey: ["employee", 7] });
    expect(query?.options.gcTime).toBe(0);
    expect((query?.options as { refetchOnWindowFocus?: unknown } | undefined)?.refetchOnWindowFocus).toBe(false);
  });

  it("renders the one-time login card with the username", async () => {
    answerHead(200, head({ one_time_login: { username: "bat.bold", password: "Tmp-123" } }));
    renderAt("/employees/7/", newClient());
    const card = await screen.findByText("bat.bold");
    expect(card.closest("#one-time-login")).not.toBeNull();
  });

  it("keeps the one-time login card after a refetch that returns null", async () => {
    answerHead(200, head({ one_time_login: { username: "bat.bold", password: "Tmp-123" } }));
    const client = newClient();
    renderAt("/employees/7/", client);
    await screen.findByText("bat.bold");

    answerHead(200, head({ one_time_login: null }));
    await act(async () => {
      await client.refetchQueries({ queryKey: ["employee", 7], exact: true });
    });
    // Four requests before the refetch (the header, the Work, Salary and Personal tabs), one more for the header.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    expect(screen.getByText("bat.bold")).toBeTruthy();
  });

  it("the card is removed only by its close button", async () => {
    answerHead(200, head({ one_time_login: { username: "bat.bold", password: "Tmp-123" } }));
    renderAt("/employees/7/", newClient());
    await screen.findByText("bat.bold");
    fireEvent.click(screen.getByRole("button", { name: "Ойлголоо, хаах" }));
    expect(screen.queryByText("bat.bold")).toBeNull();
  });

  it("without the personal right there is no #tab-personal", async () => {
    answerHead(200, head({ can: { ...head().can, view_personal: false } }));
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(container.querySelector("#tab-personal")).toBeNull();
    expect(container.querySelector("#tab-salary")).not.toBeNull();
  });

  it("without the salary right there is no #tab-salary", async () => {
    answerHead(200, head({ can: { ...head().can, view_salary: false } }));
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(container.querySelector("#tab-salary")).toBeNull();
    expect(container.querySelector("#tab-personal")).not.toBeNull();
  });

  it("the event menu item calls openLegacyEmployee with the pk", async () => {
    answerHead(200, head({ event_menu: [{ value: "transfer", label: "Албан тушаал солих" }] }));
    renderAt("/employees/7/", newClient());
    fireEvent.click(await screen.findByText("Өөрчлөлт бүртгэх ▾"));
    fireEvent.click(screen.getByRole("button", { name: "Албан тушаал солих" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("a 403 from the API renders the 403 screen", async () => {
    answerHead(403, { code: "forbidden" });
    renderAt("/employees/7/", newClient());
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("restores the previous document title on unmount", async () => {
    answerHead(200, head());
    const { unmount } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(document.title).toBe("Бат Болд · MACS Human Capital");
    unmount();
    expect(document.title).toBe("Initial");
  });

  it("marks exactly one narrow-bar tab with tab-on and aria-current", async () => {
    answerHead(200, head());
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    const tabs = Array.from(container.querySelectorAll("nav a.tab"));
    expect(tabs.length).toBe(3);
    const marked = tabs.filter((a) => a.classList.contains("tab-on"));
    expect(marked.length).toBe(1);
    expect(marked[0].getAttribute("aria-current")).toBe("page");
    for (const a of tabs.filter((x) => x !== marked[0])) {
      expect(a.getAttribute("aria-current")).toBeNull();
    }
  });

  it("an address #salary marks the salary tab and rail link even when the scroll does not move", async () => {
    window.location.hash = "#salary";
    // jsdom has no layout: the scroll is a no-op, so only the mark can show the section.
    Element.prototype.scrollIntoView = vi.fn();
    answerHead(200, head());
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    const tab = container.querySelector('nav a.tab[href="#salary"]');
    expect(tab?.classList.contains("tab-on")).toBe(true);
    expect(tab?.getAttribute("aria-current")).toBe("page");
    expect(container.querySelector('a.rtab[href="#salary"]')?.getAttribute("aria-current")).toBe("page");
    window.location.hash = "";
  });

  it("a hash target is scrolled to again when its section grows, until the reader first scrolls", async () => {
    const observers: { cb: ResizeObserverCallback; targets: Element[]; connected: boolean }[] = [];
    class FakeResizeObserver {
      entry = { cb: null as unknown as ResizeObserverCallback, targets: [] as Element[], connected: true };
      constructor(cb: ResizeObserverCallback) {
        this.entry.cb = cb;
        observers.push(this.entry);
      }
      observe(el: Element) {
        this.entry.targets.push(el);
      }
      unobserve() {}
      disconnect() {
        this.entry.connected = false;
      }
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.location.hash = "#personal-edu";
    answerHead(200, head());
    renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(scroll).toHaveBeenCalled();

    // The personal body arrives and grows the section: the target is scrolled to again.
    // The spy also observes the sections; the hash watch is the one created after it.
    const personal = observers.filter((o) => o.targets.some((el) => el.id === "tab-personal")).pop();
    expect(personal).toBeDefined();
    scroll.mockClear();
    act(() => {
      personal?.cb([], {} as ResizeObserver);
    });
    expect(scroll).toHaveBeenCalled();

    // The reader scrolls: the watch ends, and a later layout change leaves the position alone.
    scroll.mockClear();
    act(() => {
      window.dispatchEvent(new Event("wheel"));
    });
    // A disconnected observer no longer calls back, so no further scroll is made.
    expect(personal?.connected).toBe(false);
    expect(scroll).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
    window.location.hash = "";
  });
});
