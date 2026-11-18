import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { anyUnsaved, isUnsaved, LEAVE_MESSAGE, LEAVE_OK, setUnsaved } from "../../lib/unsaved";
import { TLink } from "../../lib/viewTransition";
import { confirm } from "../../widgets/confirm";
import { MainWidthContext } from "../../shell/mainWidth";
import { EmployeePage } from "./EmployeePage";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

vi.mock("../../widgets/confirm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../widgets/confirm")>();
  return { ...actual, confirm: vi.fn() };
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

  it("a viewer without the manage rights renders no save bar and asks for no page form", async () => {
    answerHead(200, head());
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    expect(container.querySelector("#save-bar")).toBeNull();
    const askedForPageForm = fetchMock.mock.calls.some((call) => {
      const input = call[0] as Request | string;
      return (typeof input === "string" ? input : input.url).endsWith("/page-form");
    });
    expect(askedForPageForm).toBe(false);
  });

  it("a manager gets the page form and the save bar, hidden until a box changes", async () => {
    const pageForm = { loaded: "L1", si_loaded: "", fields: [] };
    fetchMock.mockImplementation(async (input: Request | string) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/page-form")) return jsonResponse(200, pageForm);
      if (url.endsWith("/work")) return jsonResponse(200, emptyWork());
      if (url.endsWith("/salary")) return jsonResponse(200, emptySalary());
      if (url.endsWith("/personal")) return jsonResponse(200, emptyPersonal());
      return jsonResponse(200, head({ can: { ...head().can, manage: true } }));
    });
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    await waitFor(() => expect(container.querySelector("#save-bar")).not.toBeNull());
    expect(container.querySelector("#save-bar")?.classList.contains("hidden")).toBe(true);
    await waitFor(() => {
      const askedForPageForm = fetchMock.mock.calls.some((call) => {
        const input = call[0] as Request | string;
        return (typeof input === "string" ? input : input.url).endsWith("/page-form");
      });
      expect(askedForPageForm).toBe(true);
    });
  });

  it("a manager edit in the header shows the save bar, and a submit of the page saves once", async () => {
    const box = {
      name: "work_phone", label: "Ажлын утас", kind: "text", value: "7700-1234", choice: "", checked: false, choices: [],
      combo: false, errors: [], help: "", max_length: null, placeholder: "—", required: false,
    };
    const pageForm = { loaded: "L1", si_loaded: "", fields: [box] };
    fetchMock.mockImplementation(async (input: Request | string) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/page-form")) return jsonResponse(200, pageForm);
      if (url.endsWith("/save")) {
        return jsonResponse(200, { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "" });
      }
      if (url.endsWith("/work")) return jsonResponse(200, emptyWork());
      if (url.endsWith("/salary")) return jsonResponse(200, emptySalary());
      if (url.endsWith("/personal")) return jsonResponse(200, emptyPersonal());
      return jsonResponse(200, head({ can: { ...head().can, manage: true } }));
    });
    const { container } = renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });
    await waitFor(() => expect((screen.getByLabelText("Ажлын утас") as HTMLInputElement).readOnly).toBe(false));

    fireEvent.change(screen.getByLabelText("Ажлын утас"), { target: { value: "7700-5555" } });
    const bar = container.querySelector("#save-bar") as HTMLElement;
    expect(bar.classList.contains("flex")).toBe(true);

    const pageFormEl = container.querySelector("#emp-form") as HTMLFormElement;
    // The page form is empty: the boxes and the section forms are not inside it; the box posts with form="emp-form".
    expect(pageFormEl.childElementCount).toBe(0);
    expect(screen.getByLabelText("Ажлын утас").getAttribute("form")).toBe("emp-form");
    fireEvent.submit(pageFormEl);
    fireEvent.submit(pageFormEl);

    await waitFor(() => expect(bar.classList.contains("hidden")).toBe(true));
    const saves = fetchMock.mock.calls.filter((call) => {
      const input = call[0] as Request | string;
      return (typeof input === "string" ? input : input.url).endsWith("/save");
    });
    expect(saves).toHaveLength(1);
  });
});

// ---- Unsaved edits: the page's beforeunload guard and the in-app leave check (unsaved.ts, viewTransition.ts) ----

const WORK_PHONE = "Ажлын утас";
const STORED_PHONE = "7700-1234";

// A manager's page: the page form has one box (the work phone), so a typed change is a real page edit (PageForm owns it).
function setManagerFetch() {
  const box = {
    name: "work_phone", label: WORK_PHONE, kind: "text", value: STORED_PHONE, choice: "", checked: false, choices: [],
    combo: false, errors: [], help: "", max_length: null, placeholder: "—", required: false,
  };
  const pageForm = { loaded: "L1", si_loaded: "", fields: [box] };
  fetchMock.mockImplementation(async (input: Request | string) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.endsWith("/page-form")) return jsonResponse(200, pageForm);
    if (url.endsWith("/save")) {
      return jsonResponse(200, { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "" });
    }
    if (url.endsWith("/work")) return jsonResponse(200, emptyWork());
    if (url.endsWith("/salary")) return jsonResponse(200, emptySalary());
    if (url.endsWith("/personal")) return jsonResponse(200, emptyPersonal());
    return jsonResponse(200, head({ can: { ...head().can, manage: true } }));
  });
}

// Types a page edit into the work phone box and waits for the page to take it.
async function editWorkPhone(value: string) {
  fireEvent.change(await screen.findByLabelText(WORK_PHONE), { target: { value } });
  await waitFor(() => expect(isUnsaved("page")).toBe(true));
}

// The employee page with links that leave it (/me/), stay on its path (a hash, a query) or open another employee.
function renderWithLinks(path: string, client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MainWidthContext.Provider value={() => undefined}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/employees/:pk/"
              element={
                <>
                  <EmployeePage />
                  <TLink to="/me/">go-me</TLink>
                  <TLink to="/employees/7/#personal-edu">same-page</TLink>
                  <TLink to="/employees/7/?tab=work">same-query</TLink>
                  <TLink to="/employees/8/">to-eight</TLink>
                </>
              }
            />
            <Route path="/me/" element={<p>me route</p>} />
          </Routes>
        </MemoryRouter>
      </MainWidthContext.Provider>
    </QueryClientProvider>,
  );
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("EmployeePage unsaved edits", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.mocked(confirm).mockReset();
    setManagerFetch();
  });

  afterEach(() => {
    cleanup();
    act(() => {
      setUnsaved("page", false);
      setUnsaved("section:identity", false);
    });
  });

  it("a dirty section makes beforeunload prevented, and a clean page does not", async () => {
    renderAt("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });

    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    act(() => setUnsaved("section:identity", true));
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("a page edit makes beforeunload prevented", async () => {
    renderAt("/employees/7/", newClient());
    await editWorkPhone("55555555");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("leaving the page while dirty asks; declining keeps the page, the edit and the unsaved flag", async () => {
    vi.mocked(confirm).mockResolvedValue(false);
    renderWithLinks("/employees/7/", newClient());
    await editWorkPhone("55555555");

    fireEvent.click(screen.getByText("go-me"));

    await waitFor(() => expect(confirm).toHaveBeenCalledWith(LEAVE_MESSAGE, { ok: LEAVE_OK }));
    await tick();
    expect(screen.queryByText("me route")).toBeNull();
    expect(screen.getByRole("heading", { name: "Ажил" })).toBeTruthy();
    expect(anyUnsaved()).toBe(true);
    expect((screen.getByLabelText(WORK_PHONE) as HTMLInputElement).value).toBe("55555555");
  });

  it("leaving the page while dirty asks; accepting leaves", async () => {
    vi.mocked(confirm).mockResolvedValue(true);
    renderWithLinks("/employees/7/", newClient());
    await editWorkPhone("55555555");

    fireEvent.click(screen.getByText("go-me"));

    expect(await screen.findByText("me route")).toBeTruthy();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("a double click on a leave link while the question is open asks once and navigates at most once", async () => {
    let answer: (ok: boolean) => void = () => undefined;
    vi.mocked(confirm).mockImplementation(() => new Promise<boolean>((resolve) => (answer = resolve)));
    renderWithLinks("/employees/7/", newClient());
    await editWorkPhone("55555555");

    fireEvent.click(screen.getByText("go-me"));
    fireEvent.click(screen.getByText("go-me"));
    expect(confirm).toHaveBeenCalledTimes(1);

    answer(true);
    expect(await screen.findByText("me route")).toBeTruthy();
    await tick();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("a link that stays on the same page while dirty does not ask (hash or query)", async () => {
    renderWithLinks("/employees/7/", newClient());
    await editWorkPhone("55555555");

    fireEvent.click(screen.getByText("same-page"));
    fireEvent.click(screen.getByText("same-query"));

    await tick();
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Ажил" })).toBeTruthy();
    expect(anyUnsaved()).toBe(true);
  });

  it("leaving the page with nothing unsaved does not ask", async () => {
    renderWithLinks("/employees/7/", newClient());
    await screen.findByRole("heading", { name: "Ажил" });

    fireEvent.click(screen.getByText("go-me"));

    expect(await screen.findByText("me route")).toBeTruthy();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("another employee on the same route starts clean: the last employee's edit does not carry over", async () => {
    vi.mocked(confirm).mockResolvedValue(true);
    renderWithLinks("/employees/7/", newClient());
    await editWorkPhone("55555555");

    fireEvent.click(screen.getByText("to-eight"));

    await waitFor(() => expect((screen.getByLabelText(WORK_PHONE) as HTMLInputElement).value).toBe(STORED_PHONE));
    expect(anyUnsaved()).toBe(false);
  });
});
