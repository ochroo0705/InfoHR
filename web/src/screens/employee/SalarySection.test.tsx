import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEmployeeSalary } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { QuickAddProvider } from "../lists/QuickAddHost";
import { PageFormElement, PageFormProvider } from "./PageForm";
import { SalarySection } from "./SalarySection";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// A row's «Цуцлах» calls the event cancel opener from the provider. The test renders SalarySection alone, so the hook
// returns stubs.
const popups = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
}));
vi.mock("./EmployeePopups", () => ({ useEmployeePopups: () => popups }));

// The meta query: no user is signed in unless a test sets `perms` (the signed-in user's permission list).
const meta = vi.hoisted(() => ({ perms: null as string[] | null }));
vi.mock("../../shell/useMeta", () => ({
  useMeta: () => ({ data: meta.perms === null ? undefined : { user: { perms: meta.perms } } }),
}));

// fetch and Request are stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// Header.test.tsx. The page form (`/page-form`) and the save (`/save`) are answered here.
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

function pageField(overrides: Record<string, unknown>) {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    kind: "text",
    label: "",
    max_length: null,
    name: "",
    placeholder: "—",
    required: false,
    value: "",
    ...overrides,
  };
}

// The blank entry's label is "" (the server sends the empty option with an empty label).
const BANKS = [
  { value: "", label: "" },
  { value: "4", label: "Хаан банк" },
  { value: "5", label: "Голомт банк" },
];

// The accountant's page form: the «Банк, даатгал» boxes only (the work boxes are not on it), and si-loaded.
const PAGE_FORM_SI = {
  loaded: "",
  si_loaded: "S1",
  fields: [
    pageField({ name: "si-bank", label: "Банк", kind: "select", value: "4", choice: "Хаан банк", choices: BANKS }),
    pageField({ name: "si-account_no", label: "Дансны дугаар", kind: "text", value: "5001234567" }),
    pageField({ name: "si-has_disability", label: "Хөгжлийн бэрхшээлтэй", kind: "checkbox", value: "", checked: false }),
  ],
};

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "", si_loaded: "S2", tab: "salary" };

let pageForm: unknown;
let appendSpy: { mock: { calls: unknown[][] }; mockRestore: () => void };
let saveAnswers: { status: number; body: unknown }[];

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function urlOf(input: unknown): string {
  return typeof input === "string" ? input : (input as Request).url;
}

function callsTo(suffix: string): number {
  return fetchMock.mock.calls.filter((call) => new URL(urlOf(call[0])).pathname.endsWith(suffix)).length;
}

// The correction pop-ups (Task 16a): the form of «Цалин тогтоох» and «Цалин засварлах», and the status of the form load.
let correctionForm: unknown;
let correctionStatus: number;

function routeFetch() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(urlOf(input)).pathname;
    if (path.endsWith("/page-form")) return jsonResponse(200, pageForm);
    if (path.endsWith("/save")) {
      const next = saveAnswers.shift() ?? { status: 200, body: OK_RESULT };
      return jsonResponse(next.status, next.body);
    }
    if (request.method === "GET" && path.endsWith("/form")) {
      return jsonResponse(correctionStatus, correctionStatus === 200 ? correctionForm : {});
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The «Цалин засварлах» pop-up's form (the amount box and the required reason).
const CORRECT_SALARY_FORM = {
  title: "Цалин засварлах",
  fields: [
    pageField({ name: "amount", label: "Цалин", kind: "money", value: "2500000" }),
    pageField({ name: "reason", label: "Шалтгаан", kind: "text", value: "", required: true }),
  ],
  hidden: {},
  empty_lists: [],
  can_delete: false,
};

// The salary section inside the page form context (PageFormProvider), as EmployeePage renders it. `enabled` is the page's
// manage or salary right (the page-form request). The save bar is not drawn here: the section's own text is tested.
function renderWithPage(ui: ReactElement, enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PageFormProvider pk={7} enabled={enabled} section="salary">
        <PageFormElement />
        {ui}
      </PageFormProvider>
    </QueryClientProvider>,
  );
}

// The values the last save sent (values_json of the multipart body).
function savedValues(): Record<string, string> {
  const calls = appendSpy.mock.calls.filter((call) => call[0] === "values_json");
  return JSON.parse(String(calls[calls.length - 1][1]));
}

// «Хадгалах» submits #emp-form (a browser does this through form="emp-form"); jsdom does not follow that attribute for a
// submit button, so the test submits the form the same way.
function saveNow() {
  fireEvent.submit(document.getElementById("emp-form") as HTMLFormElement);
}

// Waits until the page form has loaded: the account box is then editable (it is read-only until then).
async function loaded() {
  await waitFor(() => expect((screen.getByLabelText("Дансны дугаар") as HTMLInputElement).readOnly).toBe(false));
}

vi.mock("../../api/employee", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/employee")>();
  return { ...actual, useEmployeeSalary: vi.fn() };
});

type EmployeeSalaryOut = components["schemas"]["EmployeeSalaryOut"];
type EmployeeBankFieldOut = components["schemas"]["EmployeeBankFieldOut"];
type Row = EmployeeSalaryOut["rows"][number];

// A text box as the API sends it: its raw value and the read-only text.
function text(name: string, label: string, value = "", shown = "—", aria = label): EmployeeBankFieldOut {
  return { name, label, aria_label: aria, kind: "text", value, choice: "", text: shown, checked: false };
}

// The bank block in template order, empty, as a user with no bank on file gets it.
function bankFields(overrides: Partial<Record<string, EmployeeBankFieldOut>> = {}): EmployeeBankFieldOut[] {
  const base: EmployeeBankFieldOut[] = [
    { name: "si-bank", label: "Банк", aria_label: "Банк", kind: "select", value: "", choice: "---------", text: "—", checked: false },
    text("si-account_no", "Дансны дугаар"),
    text("si-social_insurance_no", "НДД", "", "—", "НДД-ийн дугаар"),
    text("si-health_insurance_no", "ЭМДД", "", "—", "ЭМДД-ийн дугаар"),
    {
      name: "si-insured_category",
      label: "Даатгуулагчийн төрөл",
      aria_label: "Даатгуулагчийн төрөл",
      kind: "select",
      value: "",
      choice: "---------",
      text: "—",
      checked: false,
    },
    text("si-taxpayer_no", "ТТД", "", "—", "Татвар төлөгчийн дугаар"),
    {
      name: "si-has_disability",
      label: "Хөгжлийн бэрхшээл",
      aria_label: "Хөгжлийн бэрхшээлтэй",
      kind: "checkbox",
      value: "",
      choice: "",
      text: "Үгүй",
      checked: false,
    },
  ];
  return base.map((field) => overrides[field.label] ?? field);
}

// A salary payload as the API sends it: today's pay, the history rows and the bank block.
function salary(overrides: Partial<EmployeeSalaryOut> = {}): EmployeeSalaryOut {
  return {
    current: "2,500,000₮",
    missing_label: "",
    rows: [],
    has_rows: false,
    can_set: false,
    set_label: "",
    editable: false,
    bank_fields: bankFields(),
    ...overrides,
  } as EmployeeSalaryOut;
}

// One history row as the API sends it.
function row(overrides: Partial<Row> = {}): Row {
  return {
    pk: 1,
    event_id: null,
    period_text: "2026-01-05 – одоо",
    amount: "2,500,000₮",
    label: "Анхны цалин",
    scheduled: false,
    scheduled_label: "",
    cancellable: false,
    correctable: true,
    action_label: "Засвар",
    action_class: "text-violet-700 hover:underline",
    ...overrides,
  };
}

function mockSalary(data: EmployeeSalaryOut | undefined, error: unknown = null) {
  vi.mocked(useEmployeeSalary).mockReturnValue({ data, error } as unknown as ReturnType<typeof useEmployeeSalary>);
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
  Object.values(popups).forEach((open) => open.mockClear());
  fetchMock.mockReset();
  meta.perms = null;
  pageForm = PAGE_FORM_SI;
  saveAnswers = [];
  correctionForm = CORRECT_SALARY_FORM;
  correctionStatus = 200;
  routeFetch();
  appendSpy = vi.spyOn(FormData.prototype, "append");
});

afterEach(() => {
  cleanup();
  appendSpy.mockRestore();
});

describe("SalarySection", () => {
  it("draws nothing before the salary data arrives", () => {
    mockSalary(undefined);
    const { container } = renderWithPage(<SalarySection pk={7} />);
    expect(container.textContent).toBe("");
  });

  it("shows the failed-request line when the salary request fails", () => {
    mockSalary(undefined, new Error("boom"));
    renderWithPage(<SalarySection pk={7} />);
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
  });

  it("draws the pay heading, the current pay and the bank heading in the template's order", () => {
    mockSalary(salary());
    const { container } = renderWithPage(<SalarySection pk={7} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent);
    expect(headings).toEqual(["Үндсэн цалин", "Банк, даатгал"]);
    expect(screen.getByText("Одоогийн").nextElementSibling?.textContent).toBe("2,500,000₮");
    expect(screen.getByText("2,500,000₮").className).toBe("text-2xl font-semibold");
  });

  it("current: null shows «тогтоогоогүй» beside the heading and no current pay", () => {
    mockSalary(salary({ current: null, missing_label: "тогтоогоогүй" }));
    const { container } = renderWithPage(<SalarySection pk={7} />);
    expect(screen.getByText("тогтоогоогүй").className).toBe("ml-1 text-sm font-normal text-slate-400");
    expect(container.querySelector("h3")?.textContent).toBe("Үндсэн цалин тогтоогоогүй");
    expect(screen.queryByText("Одоогийн")).toBeNull();
  });

  it("a set pay shows no «тогтоогоогүй» note", () => {
    mockSalary(salary());
    renderWithPage(<SalarySection pk={7} />);
    expect(screen.queryByText("тогтоогоогүй")).toBeNull();
  });

  it("the history table has its four columns, and no table without rows", () => {
    mockSalary(salary());
    const { container } = renderWithPage(<SalarySection pk={7} />);
    expect(container.querySelector(".ptable")).toBeNull();
    cleanup();
    mockSalary(salary({ rows: [row()], has_rows: true }));
    const { container: withRows } = renderWithPage(<SalarySection pk={7} />);
    const heads = Array.from(withRows.querySelectorAll("th")).map((th) => th.textContent);
    expect(heads).toEqual(["Хугацаа", "Цалин", "Төрөл", ""]);
  });

  it("a scheduled row has the «Төлөвлөсөн» badge, a closed row none", () => {
    mockSalary(
      salary({
        rows: [
          row({ pk: 1, period_text: "2030-01-01 –", scheduled: true, scheduled_label: "Төлөвлөсөн", label: "Өсөлт" }),
          row({ pk: 2, period_text: "2026-01-05 – 2029-12-31", label: "Анхны цалин", action_label: "", action_class: "" }),
        ],
        has_rows: true,
      }),
    );
    renderWithPage(<SalarySection pk={7} />);
    const badge = screen.getByText("Төлөвлөсөн");
    expect(badge.className).toBe("rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800");
    expect(badge.closest("tr")?.textContent).toContain("Өсөлт");
    expect(screen.getAllByText("Төлөвлөсөн")).toHaveLength(1);
  });

  it("a period text is drawn as the API gives it", () => {
    mockSalary(
      salary({
        rows: [
          row({ pk: 1, period_text: "2030-01-01 –", scheduled: true, scheduled_label: "Төлөвлөсөн" }),
          row({ pk: 2, period_text: "2026-01-05 – одоо" }),
        ],
        has_rows: true,
      }),
    );
    renderWithPage(<SalarySection pk={7} />);
    expect(screen.getByText("2030-01-01 –")).toBeTruthy();
    expect(screen.getByText("2026-01-05 – одоо")).toBeTruthy();
  });

  it("«Цалин тогтоох» shows when the API sends set_label, and opens the set-salary pop-up (not the legacy page)", async () => {
    mockSalary(salary({ can_set: true, set_label: "Цалин тогтоох" }));
    correctionForm = { ...CORRECT_SALARY_FORM, title: "Цалин тогтоох" };
    renderWithPage(<SalarySection pk={7} />);
    const button = screen.getByRole("button", { name: "Цалин тогтоох" });
    expect(button.className).toBe("ml-auto rounded px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-50");
    fireEvent.click(button);
    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    expect(callsTo("/salary/set/form")).toBe(1);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a row's «Засвар» opens the correction pop-up of that salary record (not the legacy page)", async () => {
    mockSalary(salary({ rows: [row({ pk: 5 })], has_rows: true }));
    renderWithPage(<SalarySection pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Засвар" }));
    await screen.findByRole("heading", { name: "Цалин засварлах" });
    expect(callsTo("/salary/5/correct/form")).toBe(1);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a stale row whose correction the server refuses (403) shows the load failure in the pop-up", async () => {
    correctionStatus = 403;
    mockSalary(salary({ rows: [row({ pk: 5 })], has_rows: true }));
    renderWithPage(<SalarySection pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Засвар" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(within(dialog).getByText("Хаах", { selector: "button:not([data-modal-x])" })).toBeTruthy();
  });

  it("no «Цалин тогтоох» without set_label", () => {
    mockSalary(salary({ rows: [row()], has_rows: true }));
    renderWithPage(<SalarySection pk={7} />);
    expect(screen.queryByRole("button", { name: "Цалин тогтоох" })).toBeNull();
  });

  it("a row's action button takes its label and class from the API, and «Цуцлах» calls openEventCancel with the event id", () => {
    mockSalary(
      salary({
        rows: [
          row({
            pk: 1,
            event_id: 21,
            period_text: "2030-01-01 –",
            scheduled: true,
            scheduled_label: "Төлөвлөсөн",
            cancellable: true,
            correctable: false,
            action_label: "Цуцлах",
            action_class: "rounded px-2 py-1 text-red-600 hover:bg-red-50",
          }),
        ],
        has_rows: true,
      }),
    );
    renderWithPage(<SalarySection pk={7} />);
    const cancel = screen.getByRole("button", { name: "Цуцлах" });
    expect(cancel.className).toBe("rounded px-2 py-1 text-red-600 hover:bg-red-50");
    fireEvent.click(cancel);
    expect(popups.openEventCancel).toHaveBeenCalledWith(21);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a cancellable row with no event id (null) calls no opener", () => {
    mockSalary(
      salary({
        rows: [row({ pk: 1, event_id: null, cancellable: true, correctable: false, action_label: "Цуцлах" })],
        has_rows: true,
      }),
    );
    renderWithPage(<SalarySection pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(popups.openEventCancel).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a correctable row's button still opens the correction pop-up, never the cancel opener", async () => {
    mockSalary(salary({ rows: [row({ pk: 5, event_id: 21, correctable: true })], has_rows: true }));
    renderWithPage(<SalarySection pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Засвар" }));
    await screen.findByRole("heading", { name: "Цалин засварлах" });
    expect(popups.openEventCancel).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a row without an action label draws no button in its last cell", () => {
    mockSalary(salary({ rows: [row({ action_label: "", action_class: "", correctable: false })], has_rows: true }));
    const { container } = renderWithPage(<SalarySection pk={7} />);
    const lastCell = container.querySelector("tbody tr td:last-child");
    expect(lastCell?.className).toBe("text-right whitespace-nowrap");
    expect(lastCell?.querySelector("button")).toBeNull();
  });

  it("read-only bank block: the printed text, «—» for empty, Тийм / Үгүй for the flag", () => {
    mockSalary(
      salary({
        editable: false,
        bank_fields: bankFields({
          "Дансны дугаар": text("si-account_no", "Дансны дугаар", "5001234567", "5001234567"),
          "Хөгжлийн бэрхшээл": { name: "si-has_disability", label: "Хөгжлийн бэрхшээл", aria_label: "Хөгжлийн бэрхшээлтэй", kind: "checkbox", value: "", choice: "", text: "Тийм", checked: true },
        }),
      }),
    );
    const { container } = renderWithPage(<SalarySection pk={7} />);
    expect(container.querySelectorAll("input, select")).toHaveLength(0);
    expect(screen.getByText("Дансны дугаар").nextElementSibling?.textContent).toBe("5001234567");
    expect(screen.getByText("Банк").nextElementSibling?.textContent).toBe("—");
    expect(screen.getByText("Хөгжлийн бэрхшээл").nextElementSibling?.textContent).toBe("Тийм");
  });

  it("editable bank block: selects with their option only, text boxes with the placeholder, a read-only checkbox", () => {
    mockSalary(
      salary({
        editable: true,
        bank_fields: bankFields({
          Банк: { name: "si-bank", label: "Банк", aria_label: "Банк", kind: "select", value: "4", choice: "Хаан банк", text: "Хаан банк", checked: false },
          "Дансны дугаар": text("si-account_no", "Дансны дугаар", "5001234567"),
          "Хөгжлийн бэрхшээл": { name: "si-has_disability", label: "Хөгжлийн бэрхшээл", aria_label: "Хөгжлийн бэрхшээлтэй", kind: "checkbox", value: "", choice: "", text: "Тийм", checked: true },
        }),
      }),
    );
    renderWithPage(<SalarySection pk={7} />);
    expect(document.querySelectorAll("select")).toHaveLength(2); // bank and insured category
    const bank = screen.getByLabelText("Банк") as HTMLSelectElement;
    expect(bank.className).toContain("f-soft");
    expect(bank.options).toHaveLength(1);
    expect(bank.options[0].textContent).toBe("Хаан банк");
    expect(bank.value).toBe("4");
    expect(fireEvent.mouseDown(bank)).toBe(false);
    expect(fireEvent.keyDown(bank, { key: "ArrowDown" })).toBe(false);
    const account = screen.getByLabelText("Дансны дугаар") as HTMLInputElement;
    expect(account.type).toBe("text");
    expect(account.value).toBe("5001234567");
    expect(account.readOnly).toBe(true);
    const empty = screen.getByLabelText("НДД-ийн дугаар") as HTMLInputElement;
    expect(empty.value).toBe("");
    expect(empty.placeholder).toBe("—");
    const disability = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(disability.type).toBe("checkbox");
    expect(disability.checked).toBe(true);
    expect(disability.className).toBe("h-4 w-4 accent-violet-600");
  });
});

describe("SalarySection: bank boxes bound to the page form", () => {
  it("the bank select lists the choices from the page form and carries the form attribute", async () => {
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    const bank = screen.getByLabelText("Банк") as HTMLSelectElement;
    expect(Array.from(bank.options).map((o) => o.textContent)).toEqual(["", "Хаан банк", "Голомт банк"]);
    expect(bank.value).toBe("4");
    expect(bank.getAttribute("form")).toBe("emp-form");
  });

  it("an accountant's edit to an si- box sends si- names only, with si-loaded", async () => {
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    fireEvent.change(screen.getByLabelText("Дансны дугаар"), { target: { value: "5009" } });
    saveNow();
    await waitFor(() => expect(savedValues()).toEqual({ "si-account_no": "5009", "si-loaded": "S1" }));
  });

  it("the disability checkbox is controlled: a click turns it on, a second click back to empty, and the save sends on", async () => {
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    const box = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    saveNow();
    await waitFor(() => expect(savedValues()["si-has_disability"]).toBe("on"));
  });

  it("a field error shows under the account box and sets aria-invalid on it", async () => {
    saveAnswers.push({
      status: 200,
      body: { ...OK_RESULT, ok: false, field_errors: { "si-account_no": ["Дансны дугаар буруу байна."] } },
    });
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    fireEvent.change(screen.getByLabelText("Дансны дугаар"), { target: { value: "5009" } });
    saveNow();
    await waitFor(() => expect(screen.getByText("Дансны дугаар буруу байна.")).toBeTruthy());
    expect(screen.getByLabelText("Дансны дугаар").getAttribute("aria-invalid")).toBe("true");
  });

  it("a clash shows the stored bank under the select; the save keeps the chosen resolve", async () => {
    saveAnswers.push({
      status: 200,
      body: { ...OK_RESULT, ok: false, conflicts: { "si-bank": "Голомт банк" } },
    });
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "5" } });
    saveNow();
    await waitFor(() => expect(screen.getByText("«Голомт банк» хэвээр үлдээх")).toBeTruthy());
    expect((document.querySelector('input[name="resolve-si-bank"][value="mine"]') as HTMLInputElement).checked).toBe(true);
    saveNow();
    await waitFor(() => expect(savedValues()["resolve-si-bank"]).toBe("mine"));
  });

  it("a viewer without the salary right gets no box and no page-form request", () => {
    mockSalary(salary({ editable: false }));
    const { container } = renderWithPage(<SalarySection pk={7} />, false);
    expect(container.querySelectorAll("input, select, textarea")).toHaveLength(0);
    expect(callsTo("/page-form")).toBe(0);
  });

  it("a stored true disability flag is checked before the page form loads (API) and after it loads (page form)", async () => {
    pageForm = {
      ...PAGE_FORM_SI,
      fields: PAGE_FORM_SI.fields.map((f) => (f.name === "si-has_disability" ? { ...f, value: "on", checked: true } : f)),
    };
    const bankBlock = bankFields({
      "Хөгжлийн бэрхшээл": {
        name: "si-has_disability",
        label: "Хөгжлийн бэрхшээл",
        aria_label: "Хөгжлийн бэрхшээлтэй",
        kind: "checkbox",
        value: "on",
        choice: "",
        text: "Тийм",
        checked: true,
      },
    });
    mockSalary(salary({ editable: true, bank_fields: bankBlock }));
    renderWithPage(<SalarySection pk={7} />);
    const before = (screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement).checked;
    await loaded();
    const after = (screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement).checked;
    expect(before).toBe(true);
    expect(after).toBe(true);
  });

  it("a bank select that carries add shows the add line for a user with lists.manage_lists", async () => {
    // The page form draws the bank box as a combo (the typing box of select.js); the API sends the bank's add info.
    pageForm = {
      ...PAGE_FORM_SI,
      fields: PAGE_FORM_SI.fields.map((f) => (f.name === "si-bank" ? { ...f, combo: true } : f)),
    };
    const bankBlock = bankFields({
      Банк: {
        name: "si-bank",
        label: "Банк",
        aria_label: "Банк",
        kind: "select",
        value: "4",
        choice: "Хаан банк",
        text: "Хаан банк",
        checked: false,
        add: { slug: "bank", modal: false, parent: null },
      },
    });
    meta.perms = ["lists.manage_lists"];
    mockSalary(salary({ editable: true, bank_fields: bankBlock }));
    renderWithPage(
      <QuickAddProvider>
        <SalarySection pk={7} />
      </QuickAddProvider>,
    );
    await loaded();
    const box = screen.getByRole("combobox", { name: "Банк" }) as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ банк" } });
    expect(screen.getByText('+ "Шинэ банк" нэмэх')).toBeTruthy();
  });

  it("with lists.manage_lists a bank select without add info draws no add row: the add line shows only for a field that carries add", async () => {
    meta.perms = ["lists.manage_lists"];
    mockSalary(salary({ editable: true }));
    renderWithPage(<SalarySection pk={7} />);
    await loaded();
    fireEvent.mouseDown(screen.getByLabelText("Банк"));
    const list = screen.getByRole("listbox");
    expect(within(list).getByRole("option", { name: "Хаан банк" })).toBeTruthy();
    expect(within(list).queryByText(/нэмэх/)).toBeNull();
  });
});
