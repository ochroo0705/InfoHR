import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeWorkOut, WorkFieldOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { PageFormElement, PageFormProvider } from "./PageForm";
import { SaveBar } from "./SaveBar";
import { WorkFacts } from "./WorkFacts";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// The «өөрчлөх» chips call the event opener from the provider. The test renders WorkFacts alone, so the hook returns stubs.
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
// Header.test.tsx and PageForm.test.tsx. The page form (`/page-form`) and the save (`/save`) are answered here.
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
const BRANCHES = [
  { value: "", label: "" },
  { value: "1", label: "Улаанбаатар" },
  { value: "2", label: "Дархан" },
];

// The work boxes as the page form sends them (the names and labels of the work form). `branch` is a quick-add box (combo).
const PAGE_FORM = {
  loaded: "L1",
  si_loaded: "",
  fields: [
    pageField({ name: "branch", label: "Салбар", kind: "select", combo: true, value: "1", choice: "Улаанбаатар", choices: BRANCHES }),
    pageField({
      name: "job_type",
      label: "Ажлын төрөл",
      kind: "select",
      value: "NonSesional",
      choice: "Тогтмол",
      choices: [
        { value: "", label: "" },
        { value: "NonSesional", label: "Тогтмол" },
        { value: "Sesional", label: "Улирлын" },
      ],
    }),
    pageField({ name: "sector_years", label: "Салбарт ажилласан жил", kind: "number", value: "3" }),
    pageField({ name: "probation_end", label: "Туршилтын хугацаа дуусах", kind: "date", value: "" }),
  ],
};

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "work" };

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

function routeFetch() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const path = new URL(urlOf(input)).pathname;
    if (path.endsWith("/page-form")) return jsonResponse(200, pageForm);
    if (path.endsWith("/save")) {
      const next = saveAnswers.shift() ?? { status: 200, body: OK_RESULT };
      return jsonResponse(next.status, next.body);
    }
    throw new Error(`unexpected request ${path}`);
  });
}

// The Work tab's boxes inside the page's form context (PageFormProvider), with the save bar and the page form element
// as EmployeePage renders them. `enabled` is the page's manage right (the page-form request).
function renderWithPage(ui: ReactElement, enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PageFormProvider pk={7} enabled={enabled} section="work">
        <PageFormElement />
        <SaveBar />
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

// Picks an option of a quick-add (combo) box: focus opens its list, then the option is clicked.
function pick(label: string, option: string) {
  act(() => screen.getByLabelText(label).focus());
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
}

// Waits until the page form has loaded: the number box is then editable (it is read-only until then).
async function loaded() {
  await waitFor(() => expect((screen.getByLabelText("Салбарт ажилласан жил") as HTMLInputElement).readOnly).toBe(false));
}

function bar(): HTMLElement {
  return document.getElementById("save-bar") as HTMLElement;
}

// Soft fields as the API sends them: a select with its current option, a date or a number box, and the read-only text.
// `name` is the form field's HTML name; `aria` is its accessible name (the API's aria_label), the name the tests query by.
// A plain select (a choice list): drawn as a native select. Its blank option has an empty label.
const select = (name: string, aria: string, value = "", choice = "", text = "—"): WorkFieldOut => ({
  name,
  kind: "select",
  value,
  choice,
  combo: false,
  text,
  aria_label: aria,
});
// A foreign key with a quick-add list: Django draws it as a combo text box showing the current option's text.
const fk = (name: string, aria: string, value = "", choice = "", text = "—"): WorkFieldOut => ({
  name,
  kind: "select",
  value,
  choice,
  combo: true,
  text,
  aria_label: aria,
});
const date = (name: string, aria: string, value = "", text = "—"): WorkFieldOut => ({
  name,
  kind: "date",
  value,
  choice: "",
  combo: false,
  text,
  aria_label: aria,
});
const number = (name: string, aria: string, value: string): WorkFieldOut => ({
  name,
  kind: "number",
  value,
  choice: "",
  combo: false,
  text: value,
  aria_label: aria,
});

// A work payload as the API sends it.
function work(overrides: Partial<EmployeeWorkOut> = {}): EmployeeWorkOut {
  return {
    can_manage: false,
    transfer_chip: false,
    contract_chip: false,
    position: "Мэргэжилтэн",
    department: "Хүний нөөц",
    manager: "—",
    second_position: fk("second_position", "Албан тушаал (хавсарсан)"),
    office: fk("office", "Алба"),
    section: fk("section", "Хэсэг"),
    branch: fk("branch", "Салбар"),
    employee_type: "Үндсэн ажилтан",
    contract_type: "Тодорхой хугацаатай",
    contract_no: "Г-12",
    contract_start: "2026-01-05",
    contract_end: "2027-01-04",
    contract_end_label: "2027-01-04",
    probation_end: date("probation_end", "Туршилтын хугацаа дуусах"),
    first_hire_date: null,
    job_type: select("job_type", "Ажлын төрөл", "NonSesional", "Тогтмол", "Тогтмол"),
    job_figure: select("job_figure", "Ажлын хэлбэр", "Main", "Үндсэн", "Үндсэн"),
    work_conditions: select("work_conditions", "Ажлын нөхцөл", "1", "Хэвийн", "Хэвийн"),
    work_schedule: fk("work_schedule", "Ажлын цагийн хуваарь"),
    sector_years: number("sector_years", "Салбарт ажилласан жил", "3"),
    macs_contract_no: "—",
    macs_contract_period: "— – ",
    macs_taken_leave: "—",
    macs_leave_type: "—",
    macs_probation_months: "—",
    macs_last_order_no: "—",
    macs_last_order_text: "—",
    ...overrides,
  } as EmployeeWorkOut;
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
  Object.values(popups).forEach((open) => open.mockClear());
  fetchMock.mockReset();
  meta.perms = null;
  pageForm = PAGE_FORM;
  saveAnswers = [];
  routeFetch();
  appendSpy = vi.spyOn(FormData.prototype, "append");
});

afterEach(() => {
  cleanup();
  appendSpy.mockRestore();
});

// The field (dd) that sits next to a label (dt), found by its label.
function valueOf(label: string): HTMLElement {
  const dt = screen.getByText(label, { selector: "dt" });
  return dt.nextElementSibling as HTMLElement;
}

describe("WorkFacts", () => {
  it("draws the four headings in the template's order", () => {
    const { container } = renderWithPage(<WorkFacts work={work()} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent);
    expect(headings).toEqual(["Албан тушаал, байршил", "Гэрээ", "Ажлын нөхцөл, цаг", "Хуучин системээс (MACS)"]);
  });

  it("shows the job values as text, and the contract end label", () => {
    renderWithPage(<WorkFacts work={work()} />);
    expect(valueOf("Албан тушаал").textContent).toContain("Мэргэжилтэн");
    expect(valueOf("Гэрээ дуусах").textContent).toBe("2027-01-04");
    expect(screen.getByText("2027-01-04", { selector: "span" }).getAttribute("data-field")).toBe("contract_end");
  });

  it("the «өөрчлөлт» chips follow the transfer and contract flags, carry the template title and open the event form", () => {
    renderWithPage(<WorkFacts work={work({ transfer_chip: true, contract_chip: true })} />);
    const chips = screen.getAllByRole("button", { name: "өөрчлөх" });
    expect(chips).toHaveLength(4); // position, department, manager, contract
    expect(chips[0].getAttribute("title")).toBe("Өөрчлөлт бүртгэж солино (тушаалтай)");
    fireEvent.click(chips[0]);
    expect(popups.openEvent).toHaveBeenCalledWith("transfer");
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("the position, department and manager chips open the transfer event; the contract chip opens the contract event", () => {
    renderWithPage(<WorkFacts work={work({ transfer_chip: true, contract_chip: true })} />);
    const chips = screen.getAllByRole("button", { name: "өөрчлөх" });
    fireEvent.click(chips[0]);
    fireEvent.click(chips[1]);
    fireEvent.click(chips[2]);
    expect(popups.openEvent.mock.calls).toEqual([["transfer"], ["transfer"], ["transfer"]]);
    fireEvent.click(chips[3]);
    expect(popups.openEvent).toHaveBeenLastCalledWith("contract");
    expect(popups.openEvent).toHaveBeenCalledTimes(4);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("no chip is drawn when neither flag is set", () => {
    renderWithPage(<WorkFacts work={work()} />);
    expect(screen.queryByRole("button", { name: "өөрчлөх" })).toBeNull();
  });

  it("without the manage right the fields are plain text: no soft box, no hire date", () => {
    const { container } = renderWithPage(<WorkFacts work={work({ can_manage: false })} />);
    expect(container.querySelectorAll("input, select")).toHaveLength(0);
    expect(screen.queryByText("Анх ажилд орсон огноо")).toBeNull();
    expect(valueOf("Ажлын нөхцөл").textContent).toBe("Хэвийн");
  });

  it("a foreign-key field is a combo text box showing its current option, as Django's select.js draws it", () => {
    const { container } = renderWithPage(
      <WorkFacts work={work({ can_manage: true, office: fk("office", "Алба", "4", "Удирдлагын алба") })} />,
    );
    const office = screen.getByLabelText("Алба") as HTMLInputElement;
    expect(office.tagName).toBe("INPUT");
    expect(office.value).toBe("Удирдлагын алба");
    expect(office.getAttribute("role")).toBe("combobox");
    expect(office.className).toContain("sel-combo");
    // second, office, section, branch, schedule are combos; type, figure, conditions stay native selects.
    expect(container.querySelectorAll('input[role="combobox"]')).toHaveLength(5);
    expect(container.querySelectorAll("select")).toHaveLength(3);
  });

  it("a plain select draws only its current option, and its mousedown is stopped so it does not open", () => {
    renderWithPage(
      <WorkFacts
        work={work({ can_manage: true, job_type: select("job_type", "Ажлын төрөл", "NonSesional", "Тогтмол", "Тогтмол") })}
      />,
    );
    const jobType = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(jobType.options).toHaveLength(1);
    expect(jobType.options[0].textContent).toBe("Тогтмол");
    expect(jobType.className).toContain("f-soft");
    expect(jobType.disabled).toBe(false);
    expect(fireEvent.mouseDown(jobType)).toBe(false);
    expect(fireEvent.keyDown(jobType, { key: "ArrowDown" })).toBe(false);
  });

  it("an empty foreign key is an empty text box, and an empty plain select keeps an empty option", () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true, job_type: select("job_type", "Ажлын төрөл") })} />);
    expect((screen.getByLabelText("Алба") as HTMLInputElement).value).toBe("");
    const jobType = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(jobType.value).toBe("");
    expect(jobType.options[0].textContent).toBe("");
  });

  it("date and number boxes are read-only inputs of their type, with the placeholder for an empty value", () => {
    renderWithPage(
      <WorkFacts
        work={work({
          can_manage: true,
          first_hire_date: date("first_hire_date", "Анх ажилд орсон огноо", "2026-01-05"),
          probation_end: date("probation_end", "Туршилтын хугацаа дуусах", ""),
        })}
      />,
    );
    const hire = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(hire.type).toBe("text"); // datepicker.js draws a text box in a dp-wrap (Django parity)
    expect(hire.parentElement?.className).toBe("dp-wrap");
    expect(hire.value).toBe("2026-01-05");
    expect(hire.readOnly).toBe(true);
    const probation = screen.getByLabelText("Туршилтын хугацаа дуусах") as HTMLInputElement;
    expect(probation.type).toBe("text");
    expect(probation.value).toBe("");
    expect(probation.placeholder).toBe("—");
    const years = screen.getByLabelText("Салбарт ажилласан жил") as HTMLInputElement;
    expect(years.type).toBe("number");
    expect(years.value).toBe("3");
    expect(years.className).toContain("w-20");
  });

  it("the hire-date box is drawn only when the API sends it", () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true, first_hire_date: null })} />);
    expect(screen.queryByText("Анх ажилд орсон огноо")).toBeNull();
  });

  it("the MACS block shows the legacy values as sent", () => {
    renderWithPage(<WorkFacts work={work({ macs_taken_leave: "Тийм", macs_last_order_text: "Ажилд авах" })} />);
    expect(valueOf("Урт амралттай").textContent).toBe("Тийм");
    expect(valueOf("Сүүлийн тушаалын агуулга").textContent).toBe("Ажилд авах");
  });
});

describe("WorkFacts: boxes bound to the page form", () => {
  it("a loaded box is bound to the page form: form attribute, name and the server's choices", async () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    const jobType = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(jobType.name).toBe("job_type");
    expect(jobType.getAttribute("form")).toBe("emp-form");
    expect(Array.from(jobType.options).map((o) => o.textContent)).toEqual(["", "Тогтмол", "Улирлын"]);
    expect(jobType.value).toBe("NonSesional");
  });

  it("editing branch marks the page dirty and the save sends its pk", async () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    expect(bar().classList.contains("hidden")).toBe(true);
    pick("Салбар", "Дархан");
    expect(bar().classList.contains("flex")).toBe(true);
    saveNow();
    await waitFor(() => expect(savedValues()).toEqual({ branch: "2", loaded: "L1" }));
  });

  it("a field error shows under the box and sets aria-invalid on it", async () => {
    saveAnswers.push({
      status: 200,
      body: { ...OK_RESULT, ok: false, field_errors: { branch: ["Салбараа сонгоно уу."] }, loaded: "L2" },
    });
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    pick("Салбар", "Дархан");
    saveNow();
    await waitFor(() => expect(screen.getByText("Салбараа сонгоно уу.")).toBeTruthy());
    expect(screen.getByLabelText("Салбар").getAttribute("aria-invalid")).toBe("true");
  });

  it("a clash shows the stored choice under the box; the picked resolve is sent with the save", async () => {
    saveAnswers.push({
      status: 200,
      body: { ...OK_RESULT, ok: false, conflicts: { branch: "Дархан" }, loaded: "L2" },
    });
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    pick("Салбар", "Дархан");
    saveNow();
    await waitFor(() => expect(screen.getByText("«Дархан» хэвээр үлдээх")).toBeTruthy());
    const mine = document.querySelector('input[name="resolve-branch"][value="mine"]') as HTMLInputElement;
    expect(mine.checked).toBe(true);
    fireEvent.click(document.querySelector('input[name="resolve-branch"][value="theirs"]') as HTMLInputElement);
    saveNow();
    await waitFor(() => expect(savedValues()["resolve-branch"]).toBe("theirs"));
  });

  it("a viewer without the manage right gets no box and no page-form request", () => {
    const { container } = renderWithPage(<WorkFacts work={work({ can_manage: false })} />, false);
    expect(container.querySelectorAll("input, select, textarea")).toHaveLength(0);
    expect(callsTo("/page-form")).toBe(0);
  });

  it("an emptied number box sends an empty value", async () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    fireEvent.change(screen.getByLabelText("Салбарт ажилласан жил"), { target: { value: "" } });
    saveNow();
    await waitFor(() => expect(savedValues()).toEqual({ sector_years: "", loaded: "L1" }));
  });

  it("a date box edit sends the typed ISO date", async () => {
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    fireEvent.change(screen.getByLabelText("Туршилтын хугацаа дуусах"), { target: { value: "2027-03-01" } });
    saveNow();
    await waitFor(() => expect(savedValues()).toEqual({ probation_end: "2027-03-01", loaded: "L1" }));
  });

  it("with canAdd (lists.manage_lists) a combo box still draws no add row, since no box has a quick-add URL", async () => {
    meta.perms = ["lists.manage_lists"];
    renderWithPage(<WorkFacts work={work({ can_manage: true })} />);
    await loaded();
    act(() => screen.getByLabelText("Салбар").focus());
    const list = screen.getByRole("listbox");
    expect(within(list).getByRole("option", { name: "Дархан" })).toBeTruthy();
    expect(within(list).queryByText(/нэмэх/)).toBeNull();
  });
});
