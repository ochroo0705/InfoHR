import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEmployeePersonal } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { PersonalSection } from "./PersonalSection";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// PageForm.test.tsx. The on-the-spot saves answer through this stub.
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

// The section editing needs the query client (its save is a mutation): every render is inside one.
let client: QueryClient;
function wrap(ui: ReactNode) {
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}
function renderPersonal(ui: ReactNode) {
  return render(wrap(ui));
}

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

vi.mock("../../api/employee", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/employee")>();
  return { ...actual, useEmployeePersonal: vi.fn() };
});

type PersonalOut = components["schemas"]["EmployeePersonalOut"];
type ListOut = PersonalOut["lists"][number];

const CHIP_TONE =
  "inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700 tabular-nums has-[.invisible]:hidden";

// The personal data as the API sends it for a viewer who can see and manage the employee (editable) or only read.
function personal(editable: boolean): PersonalOut {
  const plainCol = { field: "", head_class: "", cell_class: "" };
  return {
    editable,
    groups: [
      {
        key: "basic",
        title: "Үндсэн мэдээлэл",
        open_by_default: true,
        chips: [
          { key: "contact", label: "Холбоо барих, хаяг", count_text: "2", visible: true, tone: CHIP_TONE },
          { key: "family", label: "Гэр бүл", count_text: "2", visible: true, tone: CHIP_TONE },
          { key: "relative", label: "Хамаатан садан", count_text: "0", visible: false, tone: CHIP_TONE },
        ],
      },
      {
        key: "edu",
        title: "Боловсрол, туршлага",
        open_by_default: false,
        chips: [{ key: "education", label: "Боловсрол", count_text: "1", visible: true, tone: CHIP_TONE }],
      },
      {
        key: "award",
        title: "Шагнал, сахилга",
        open_by_default: false,
        chips: [],
      },
      {
        key: "health",
        title: "Эрүүл мэнд, цэрэг",
        open_by_default: false,
        chips: [{ key: "body", label: "Эрүүл мэндийн үзлэг", count_text: "0", visible: false, tone: CHIP_TONE }],
      },
      {
        key: "other",
        title: "Бусад",
        open_by_default: false,
        chips: [{ key: "other", label: "Бусад мэдээлэл", count_text: "3/12", visible: true, tone: CHIP_TONE }],
      },
    ],
    counts: { address: "2", family: "2", education: "1", other: "3/12" },
    sections: [
      {
        name: "identity",
        title: "Хувийн мэдээлэл",
        group: "basic",
        editable,
        rows: [
          { label: "Регистрийн дугаар", display: "УБ99112233", empty: false },
          { label: "Төрсөн огноо", display: "—", empty: true },
        ],
        loaded: "",
        fields: editable
          ? [
              {
                name: "register_no",
                label: "Регистрийн дугаар",
                required: true,
                kind: "text",
                value: "УБ99112233",
                checked: false,
                placeholder: "—",
                choice: "",
                combo: false,
                choices: [],
              },
              {
                name: "gender",
                label: "Хүйс",
                required: false,
                kind: "select",
                value: "F",
                checked: false,
                placeholder: "",
                choice: "Эмэгтэй",
                combo: false,
                choices: [
                  { value: "", label: "" },
                  { value: "F", label: "Эмэгтэй" },
                ],
              },
              {
                name: "birth_city",
                label: "Төрсөн аймаг, хот",
                required: false,
                kind: "select",
                value: "1",
                checked: false,
                placeholder: "Аймаг, хот…",
                choice: "Улаанбаатар",
                combo: true,
                choices: [
                  { value: "", label: "" },
                  { value: "1", label: "Улаанбаатар" },
                ],
              },
            ]
          : [],
      },
      {
        name: "contact",
        title: "Холбоо барих, хаяг",
        group: "basic",
        editable,
        rows: [{ label: "Утас", display: "99112233", empty: false }],
        loaded: "",
        fields: [],
      },
      {
        name: "education",
        title: "Боловсрол",
        group: "edu",
        editable,
        rows: [{ label: "Боловсрол", display: "Бакалавр", empty: false }],
        loaded: "",
        fields: [],
      },
      {
        name: "other",
        title: "Бусад мэдээлэл",
        group: "other",
        editable,
        rows: [{ label: "Нэмэлт", display: "—", empty: true }],
        loaded: "",
        fields: [],
      },
    ],
    lists: [
      {
        kind: "address",
        title: "Хаяг",
        group: "basic",
        parent: "contact",
        inline: false,
        editable,
        count: 1,
        empty_label: "",
        columns: [
          { header: "Аймаг, хот", ...plainCol },
          { header: "Сум, дүүрэг", ...plainCol },
          { header: "Хаяг", ...plainCol },
        ],
        rows: [{ key: "3", cells: ["Улаанбаатар", "Баянзүрх", "1-р хороо"] }],
      },
      {
        kind: "contact",
        title: "Яаралтай үед холбогдох",
        group: "basic",
        parent: "contact",
        inline: true,
        editable,
        count: 0,
        empty_label: "бүртгэгдээгүй",
        columns: [{ header: "Нэр", ...plainCol, field: "name" }],
        rows: [],
      },
      familyList(editable),
      {
        kind: "relative",
        title: "Хамаатан садан",
        group: "basic",
        parent: null,
        inline: false,
        editable,
        count: 0,
        empty_label: "бүртгэгдээгүй",
        columns: [{ header: "Нэр", ...plainCol }],
        rows: [],
      },
      {
        kind: "education",
        title: "Сурсан сургууль",
        group: "edu",
        parent: "education",
        inline: false,
        editable,
        count: 1,
        empty_label: "",
        columns: [
          { header: "Сургууль", ...plainCol },
          { header: "Он", field: "", head_class: "", cell_class: "whitespace-nowrap" },
        ],
        rows: [{ key: "7", cells: ["ХИС", "2010–2014"] }],
      },
      {
        kind: "body",
        title: "Эрүүл мэндийн үзлэг",
        group: "health",
        parent: null,
        inline: false,
        editable,
        count: 0,
        empty_label: "бүртгэгдээгүй",
        columns: [{ header: "Огноо", ...plainCol }],
        rows: [],
      },
    ],
  };
}

// The family list: an inline list with API column order and two rows.
function familyList(editable: boolean): ListOut {
  const plainCol = { field: "", head_class: "", cell_class: "" };
  return {
    kind: "family",
    title: "Гэр бүл",
    group: "basic",
    parent: null,
    inline: true,
    editable,
    count: 2,
    empty_label: "",
    columns: [
      { header: "Нэр", ...plainCol, field: "given_name" },
      { header: "Хамаатан", ...plainCol, field: "relation" },
      { header: "Төрсөн он", ...plainCol, field: "birth_date" },
    ],
    rows: [
      { key: "11", cells: ["Бат", "Хүү", "2015"] },
      { key: "12", cells: ["Сара", "—", "—"] },
    ],
  };
}

function mockPersonal(data: PersonalOut | undefined, error = false) {
  vi.mocked(useEmployeePersonal).mockReturnValue({ data, error: error ? new Error("x") : null } as never);
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.mocked(openLegacyEmployee).mockClear();
  // jsdom has no layout: the group scroll is only checked for its call.
  Element.prototype.scrollIntoView = vi.fn();
  // Reset the hash so each test starts on the same address.
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
});

function groupEl(key: string): HTMLDetailsElement {
  const el = document.querySelector<HTMLDetailsElement>(`details[data-pgroup="${key}"]`);
  if (!el) throw new Error(`no group ${key}`);
  return el;
}

describe("PersonalSection", () => {
  it("a group header shows its chips' count text", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    expect(document.querySelector("#menu-count-contact")?.textContent).toBe("2");
    expect(document.querySelector("#menu-count-contact")?.parentElement?.textContent).toBe("Холбоо барих, хаяг 2");
    expect(document.querySelector("#menu-count-family")?.textContent).toBe("2");
    expect(groupEl("basic").querySelector("summary")?.textContent).toContain("Холбоо барих, хаяг");
  });

  it("toggling a group flips aria-expanded and its open state", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    const summary = groupEl("edu").querySelector("summary") as HTMLElement;
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    expect(groupEl("edu").open).toBe(false);

    fireEvent.click(summary);
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    expect(groupEl("edu").open).toBe(true);

    fireEvent.click(summary);
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    expect(groupEl("edu").open).toBe(false);
  });

  it("an empty list shows its empty text beside its title", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    const section = document.getElementById("sec-body");
    expect(section?.querySelector("h3")?.textContent).toBe("Эрүүл мэндийн үзлэг бүртгэгдээгүй");
    expect(section?.querySelector("table")).toBeNull();
  });

  it("the family list renders the API values in the API column order", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    const rows = Array.from(document.querySelectorAll("#list-family tbody tr"));
    expect(rows.map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => td.textContent))).toEqual([
      ["Бат", "Хүү", "2015"],
      ["Сара", "—", "—"],
    ]);
  });

  it("the «Бусад мэдээлэл» count shows filled/total", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    expect(document.querySelector("#menu-count-other")?.textContent).toBe("3/12");
  });

  it("a chip with visible false keeps its number hidden with invisible", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    const relative = document.querySelector("#menu-count-relative");
    expect(relative?.classList.contains("invisible")).toBe(true);
    expect(relative?.parentElement?.className).toBe(CHIP_TONE);
    expect(document.querySelector("#menu-count-contact")?.classList.contains("invisible")).toBe(false);
  });

  it("a reader gets read rows, no soft boxes, no add button and no row clicks", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    expect(document.querySelector("[data-on-spot]")).toBeNull();
    expect(screen.queryByText("+ нэмэх")).toBeNull();
    expect(document.querySelector("#sec-identity dl")?.textContent).toContain("Регистрийн дугаар");
    const nullCell = document.querySelector("#sec-identity dd span.text-slate-300");
    expect(nullCell?.textContent).toBe("—");
    fireEvent.click(document.querySelector("#list-family tbody tr") as HTMLElement);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a manager gets soft boxes, and the add button opens the add pop-up (not the Django page)", () => {
    mockPersonal(personal(true));
    renderPersonal(<PersonalSection pk={7} />);
    expect(document.querySelector("#sec-identity-form[data-on-spot]")).not.toBeNull();
    expect(document.querySelector("#fields-identity")).not.toBeNull();
    const required = screen.getByText((_, el) => el?.tagName === "DT" && el.textContent === "Регистрийн дугаар *");
    expect(required).toBeTruthy();
    const gender = screen.getByLabelText("Хүйс") as HTMLSelectElement;
    expect(gender.value).toBe("F");
    expect(gender.options[1].textContent).toBe("Эмэгтэй");
    fireEvent.click(screen.getAllByText("+ нэмэх")[0]);
    // A pop-up list opens its own RowModal (RowModal.test.tsx covers it); the Django page is not opened.
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a select with a quick-add list or 8+ options is a combo text box with its current text", () => {
    mockPersonal(personal(true));
    renderPersonal(<PersonalSection pk={7} />);
    const city = screen.getByLabelText("Төрсөн аймаг, хот") as HTMLInputElement;
    expect(city.tagName).toBe("INPUT");
    expect(city.getAttribute("role")).toBe("combobox");
    expect(city.value).toBe("Улаанбаатар");
    expect(city.className).toContain("sel-combo");
    expect((screen.getByLabelText("Хүйс") as HTMLSelectElement).tagName).toBe("SELECT");
  });

  it("the address list sits in the contact section, and the education list in its section", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    const contact = document.getElementById("sec-contact") as HTMLElement;
    const address = contact.querySelector("section.mt-6") as HTMLElement;
    expect(address.textContent).toContain("Улаанбаатар");
    expect(address.querySelector("#list-contact")).toBeNull();
    const emergency = contact.querySelector("div.mt-6") as HTMLElement;
    expect(emergency.querySelector("#list-contact")).not.toBeNull();
    expect(emergency.textContent).toContain("бүртгэгдээгүй");
    expect(contact.querySelector("#list-family")).toBeNull();
    const education = document.getElementById("sec-education")?.querySelector("div.mt-5") as HTMLElement;
    expect(education.textContent).toContain("ХИС");
    expect(education.querySelector("table")).not.toBeNull();
    expect(document.getElementById("sec-family")).not.toBeNull();
    expect(document.getElementById("sec-relative")).not.toBeNull();
  });

  it("openGroup opens that group at mount", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} openGroup="edu" />);
    expect(groupEl("edu").open).toBe(true);
    expect(groupEl("award").open).toBe(false);
    expect(groupEl("basic").open).toBe(true);
  });

  it("a hash change to a group opens it and scrolls it into view", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    expect(groupEl("award").open).toBe(false);
    window.location.hash = "#personal-award";
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(groupEl("award").open).toBe(true);
    expect(groupEl("award").querySelector("summary")?.getAttribute("aria-expanded")).toBe("true");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    window.location.hash = "";
  });

  it("printing opens every closed group and closing the print restores the closed ones", () => {
    mockPersonal(personal(false));
    renderPersonal(<PersonalSection pk={7} />);
    expect(groupEl("edu").open).toBe(false);
    expect(groupEl("basic").open).toBe(true);
    act(() => {
      window.dispatchEvent(new Event("beforeprint"));
    });
    expect(groupEl("edu").open).toBe(true);
    expect(groupEl("award").open).toBe(true);
    expect(groupEl("basic").open).toBe(true);
    act(() => {
      window.dispatchEvent(new Event("afterprint"));
    });
    expect(groupEl("edu").open).toBe(false);
    expect(groupEl("award").open).toBe(false);
    expect(groupEl("basic").open).toBe(true);
  });

  it("shows the error line and nothing else when the request fails", () => {
    mockPersonal(undefined, true);
    renderPersonal(<PersonalSection pk={7} />);
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(document.querySelector("details[data-pgroup]")).toBeNull();
  });
});

// ---- On-the-spot editing of a field section (step 3b, task 14a) ----

type PersonalFieldOut = components["schemas"]["EmployeePersonalFieldOut"];

// The queued answers of the section posts. A `gate` holds the answer until the test releases it (a save in flight).
let sectionAnswers: { status: number; body: unknown; gate?: Promise<void> }[] = [];

const OK = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "" };

function refused(overrides: Record<string, unknown>) {
  return { ...OK, ok: false, ...overrides };
}

function textField(name: string, label: string, value: string): PersonalFieldOut {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    kind: "text",
    label,
    name,
    placeholder: "",
    required: false,
    value,
  };
}

// The personal data with every section's snapshot set (a save needs it).
function withLoaded(data: PersonalOut, loaded: string): PersonalOut {
  return { ...data, sections: data.sections.map((section) => ({ ...section, loaded })) };
}

// The personal data with the fields of one section replaced.
function withFields(data: PersonalOut, name: string, fields: PersonalFieldOut[]): PersonalOut {
  return { ...data, sections: data.sections.map((section) => (section.name === name ? { ...section, fields } : section)) };
}

// The personal data with one stored value changed, as a refetch brings it.
function withStored(data: PersonalOut, name: string, value: string): PersonalOut {
  return {
    ...data,
    sections: data.sections.map((section) => ({
      ...section,
      fields: section.fields.map((field) => (field.name === name ? { ...field, value } : field)),
    })),
  };
}

function urlOf(input: unknown): string {
  return typeof input === "string" ? input : (input as Request).url;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function routeSections() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const path = new URL(urlOf(input)).pathname;
    if (!path.includes("/personal/sections/")) throw new Error(`unexpected request ${path}`);
    const next = sectionAnswers.shift();
    if (!next) throw new Error("no section answer queued");
    if (next.gate) await next.gate;
    return jsonResponse(next.status, next.body);
  });
}

function sectionCalls(section: string) {
  return fetchMock.mock.calls.filter(([input]) =>
    new URL(urlOf(input)).pathname.endsWith(`/personal/sections/${section}`),
  );
}

// The JSON bodies of one section's posts, in order.
async function postedBodies(section: string): Promise<unknown[]> {
  return Promise.all(sectionCalls(section).map(([input]) => (input as Request).json()));
}

function identityForm(): HTMLFormElement {
  const form = document.querySelector<HTMLFormElement>("#sec-identity-form");
  if (!form) throw new Error("no identity form");
  return form;
}

function stripOf(form: HTMLElement): HTMLElement {
  const strip = form.querySelector<HTMLElement>("[data-strip]");
  if (!strip) throw new Error("no strip");
  return strip;
}

const registerBox = () => screen.getByLabelText("Регистрийн дугаар") as HTMLInputElement;
const editRegister = (value: string) => fireEvent.change(registerBox(), { target: { value } });
const pressSave = (form: HTMLElement) => fireEvent.click(within(form).getByText("Хадгалах"));

describe("on-the-spot editing of a field section", () => {
  beforeEach(() => {
    sectionAnswers = [];
    fetchMock.mockReset();
    routeSections();
  });

  it("typing shows the strip and the changed mark; setting the stored value back hides both", () => {
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    expect(stripOf(form).hidden).toBe(true);
    expect(form.hasAttribute("data-dirty")).toBe(false);
    expect(registerBox().getAttribute("form")).toBe("sec-identity-form");

    editRegister("УБ1");
    expect(stripOf(form).hidden).toBe(false);
    expect(form.hasAttribute("data-dirty")).toBe(true);
    expect(form.querySelector(".f-changed")).not.toBeNull();

    editRegister("УБ99112233");
    expect(stripOf(form).hidden).toBe(true);
    expect(form.hasAttribute("data-dirty")).toBe(false);
    expect(form.querySelector(".f-changed")).toBeNull();
  });

  it("«Болих» restores the stored values, hides the strip and sends nothing", () => {
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ1");
    fireEvent.click(within(form).getByText("Болих"));
    expect(registerBox().value).toBe("УБ99112233");
    expect(stripOf(form).hidden).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("«Хадгалах» posts only the changed names, with the section's snapshot and no clash choices", async () => {
    sectionAnswers = [{ status: 200, body: OK }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    expect(await postedBodies("identity")).toEqual([{ values: { register_no: "УБ2" }, resolve: {}, loaded: "L1" }]);
  });

  it("a field error stays under its box with aria-invalid, and the strip stays", async () => {
    sectionAnswers = [{ status: 200, body: refused({ field_errors: { register_no: ["Буруу утга"] } }) }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(registerBox().getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getByText("Буруу утга")).toBeTruthy();
    expect(registerBox().value).toBe("УБ2");
    expect(stripOf(form).hidden).toBe(false);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("an error outside the section's boxes shows in the red box above the boxes", async () => {
    sectionAnswers = [{ status: 200, body: refused({ form_errors: ["Ажилтны код давхцаж байна"] }) }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(screen.getByText("Ажилтны код давхцаж байна")).toBeTruthy());
    const box = form.querySelector(".mb-3.rounded.bg-red-50.p-2.text-sm.text-red-700");
    expect(box?.textContent).toContain("Ажилтны код давхцаж байна");
    expect(stripOf(form).hidden).toBe(false);
  });

  it("a clash shows the choice under the box; the re-save sends the chosen resolve and the fresh snapshot", async () => {
    sectionAnswers = [
      { status: 200, body: refused({ conflicts: { register_no: "УБ00000000" }, loaded: "L2" }) },
      { status: 200, body: OK },
    ];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(screen.getByLabelText("«УБ00000000» хэвээр үлдээх")).toBeTruthy());
    expect((screen.getByLabelText("Миний утгыг хадгалах") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("«УБ00000000» хэвээр үлдээх"));
    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    expect(await postedBodies("identity")).toEqual([
      { values: { register_no: "УБ2" }, resolve: {}, loaded: "L1" },
      { values: { register_no: "УБ2" }, resolve: { register_no: "theirs" }, loaded: "L2" },
    ]);
    expect(screen.queryByLabelText("Миний утгыг хадгалах")).toBeNull();
  });

  it("a second submit while a save is in flight sends one request", async () => {
    sectionAnswers = [{ status: 200, body: OK }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    expect(sectionCalls("identity")).toHaveLength(1);
  });

  it("a refused request (400) shows the save-failed text and keeps the edit", async () => {
    sectionAnswers = [{ status: 400, body: { form_errors: [], field_errors: {} } }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(screen.getByText("Мэдээллийг хадгалж чадсангүй.")).toBeTruthy());
    expect(registerBox().value).toBe("УБ2");
    expect(stripOf(form).hidden).toBe(false);
  });

  it("a refetch keeps an edit that still differs from the stored value", () => {
    mockPersonal(withLoaded(personal(true), "L1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    mockPersonal(withStored(withLoaded(personal(true), "L1"), "register_no", "УБ5"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    expect(registerBox().value).toBe("УБ2");
    expect(stripOf(identityForm()).hidden).toBe(false);
    expect(form).toBe(identityForm());
  });

  it("a refetch that brings the edited value drops the edit", () => {
    mockPersonal(withLoaded(personal(true), "L1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    editRegister("УБ2");
    mockPersonal(withStored(withLoaded(personal(true), "L1"), "register_no", "УБ2"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    expect(registerBox().value).toBe("УБ2");
    expect(stripOf(identityForm()).hidden).toBe(true);
    expect(identityForm().querySelector(".f-changed")).toBeNull();
  });

  it("two sections keep their edits apart: each saves only its own names", async () => {
    sectionAnswers = [{ status: 200, body: OK }];
    mockPersonal(withFields(withLoaded(personal(true), "L1"), "contact", [textField("phone", "Утас", "99112233")]));
    renderPersonal(<PersonalSection pk={7} />);
    const identity = identityForm();
    const contact = document.querySelector<HTMLFormElement>("#sec-contact-form") as HTMLFormElement;
    editRegister("УБ2");
    fireEvent.change(within(contact).getByLabelText("Утас"), { target: { value: "88776655" } });
    expect(stripOf(identity).hidden).toBe(false);
    expect(stripOf(contact).hidden).toBe(false);

    fireEvent.click(within(identity).getByText("Болих"));
    expect(stripOf(identity).hidden).toBe(true);
    expect(stripOf(contact).hidden).toBe(false);
    expect((within(contact).getByLabelText("Утас") as HTMLInputElement).value).toBe("88776655");

    pressSave(contact);
    await waitFor(() => expect(stripOf(contact).hidden).toBe(true));
    expect(await postedBodies("contact")).toEqual([{ values: { phone: "88776655" }, resolve: {}, loaded: "L1" }]);
    expect(sectionCalls("identity")).toHaveLength(0);
  });
});

// ---- Snapshot bases, edits in flight, cancel after a refusal (fix round 1, task 14a) ----

const saveButton = (form: HTMLElement) => within(form).getByText("Хадгалах") as HTMLButtonElement;

// A snapshot text: the section's loaded token as the server sends it (a JSON object of field values).
const snapshot = (values: Record<string, string>) => JSON.stringify(values);

describe("on-the-spot editing: snapshot bases, in-flight edits and cancel", () => {
  beforeEach(() => {
    sectionAnswers = [];
    fetchMock.mockReset();
    routeSections();
  });

  it("a pending edit keeps its base: a refetched snapshot does not change what the save sends for that name", async () => {
    sectionAnswers = [{ status: 200, body: OK }];
    const loaded0 = snapshot({ register_no: "УБ99112233", gender: "F" });
    mockPersonal(withLoaded(personal(true), loaded0));
    const view = renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");

    // A refetch brings a snapshot where register_no is Z and gender is M; the stored register_no is still the old one.
    const loaded1 = snapshot({ register_no: "УБ00000001", gender: "M" });
    mockPersonal(withLoaded(personal(true), loaded1));
    view.rerender(wrap(<PersonalSection pk={7} />));
    expect(registerBox().value).toBe("УБ2");

    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const [body] = (await postedBodies("identity")) as { loaded: string }[];
    expect(JSON.parse(body.loaded)).toEqual({ register_no: "УБ99112233", gender: "M" });
  });

  it("«Болих» after a refused save refetches the personal data, then drops the edit", async () => {
    sectionAnswers = [{ status: 200, body: refused({ field_errors: { register_no: ["Буруу утга"] } }) }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(registerBox().getAttribute("aria-invalid")).toBe("true"));

    fireEvent.click(within(form).getByText("Болих"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "personal"], exact: true });
    expect(registerBox().value).toBe("УБ99112233");
    expect(stripOf(form).hidden).toBe(true);
    expect(registerBox().getAttribute("aria-invalid")).toBeNull();
  });

  it("an ok keeps an edit typed while the save was in flight, and sends only the names it sent", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    sectionAnswers = [{ status: 200, body: OK, gate }];
    mockPersonal(withLoaded(personal(true), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(saveButton(form).disabled).toBe(true));

    editRegister("УБ3");
    release();
    await waitFor(() => expect(saveButton(form).disabled).toBe(false));
    expect(registerBox().value).toBe("УБ3");
    expect(stripOf(form).hidden).toBe(false);
    expect(await postedBodies("identity")).toEqual([{ values: { register_no: "УБ2" }, resolve: {}, loaded: "L1" }]);
  });

  it("an ok, then the section refetches with a new snapshot: the next save sends that snapshot", async () => {
    sectionAnswers = [
      { status: 200, body: OK },
      { status: 200, body: OK },
    ];
    mockPersonal(withLoaded(personal(true), "L1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));

    mockPersonal(withLoaded(personal(true), "L3"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    editRegister("УБ4");
    pressSave(form);
    await waitFor(() => expect(sectionCalls("identity")).toHaveLength(2));
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const bodies = (await postedBodies("identity")) as { loaded: string }[];
    expect(bodies[1].loaded).toBe("L3");
  });
});

// ---- JSON snapshots: bases across refusals, conflicts, set-back and refetch, in-flight edits (fix round 2) ----

// The identity section at a snapshot: its loaded token holds the register and gender the user saw, and the stored values
// match it (a refetch brings both).
function identityAt(register: string, gender = "F"): PersonalOut {
  const data = withLoaded(personal(true), snapshot({ register_no: register, gender }));
  return withStored(withStored(data, "register_no", register), "gender", gender);
}

function identityBodies(): Promise<{ values: Record<string, string>; resolve: Record<string, string>; loaded: string }[]> {
  return postedBodies("identity") as Promise<
    { values: Record<string, string>; resolve: Record<string, string>; loaded: string }[]
  >;
}

describe("on-the-spot editing: JSON snapshot bases", () => {
  beforeEach(() => {
    sectionAnswers = [];
    fetchMock.mockReset();
    routeSections();
  });

  it("a base survives a refused save of another name: the next save still sends the displayed value", async () => {
    sectionAnswers = [
      {
        status: 200,
        body: refused({
          field_errors: { gender: ["Буруу утга"] },
          loaded: snapshot({ register_no: "S2", gender: "F" }),
        }),
      },
      { status: 200, body: OK },
    ];
    mockPersonal(identityAt("S1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    fireEvent.change(screen.getByLabelText("Хүйс"), { target: { value: "" } });
    pressSave(form);
    await waitFor(() => expect(sectionCalls("identity")).toHaveLength(1));
    await waitFor(() => expect(stripOf(form).hidden).toBe(false));

    // The boxes still show S1 (no refetch after a refusal); the colleague's S2 is only in the refused answer.
    editRegister("V");
    pressSave(form);
    await waitFor(() => expect(sectionCalls("identity")).toHaveLength(2));
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const [, second] = await identityBodies();
    expect(second.values).toEqual({ gender: "", register_no: "V" });
    expect(JSON.parse(second.loaded)).toEqual({ register_no: "S1", gender: "F" });
  });

  it("a conflicted name drops its base: the re-save sends the refused snapshot and the chosen resolve", async () => {
    sectionAnswers = [
      {
        status: 200,
        body: refused({ conflicts: { register_no: "УБ-theirs" }, loaded: snapshot({ register_no: "S2", gender: "F" }) }),
      },
      { status: 200, body: OK },
    ];
    mockPersonal(identityAt("S1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("V");
    pressSave(form);
    await waitFor(() => expect(screen.getByLabelText("«УБ-theirs» хэвээр үлдээх")).toBeTruthy());
    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const [, second] = await identityBodies();
    expect(second.resolve).toEqual({ register_no: "mine" });
    expect(JSON.parse(second.loaded)).toEqual({ register_no: "S2", gender: "F" });
  });

  it("an edit set back to the server value, then edited again after a refetch, captures a new base", async () => {
    sectionAnswers = [{ status: 200, body: OK }];
    mockPersonal(identityAt("S1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("V");
    editRegister("S1");
    expect(stripOf(form).hidden).toBe(true);

    mockPersonal(identityAt("S3"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    editRegister("W");
    pressSave(form);
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const [first] = await identityBodies();
    expect(first.values).toEqual({ register_no: "W" });
    expect(JSON.parse(first.loaded)).toEqual({ register_no: "S3", gender: "F" });
  });

  it("an edit kept across an ok takes no base: after the refetch the next save sends the refreshed snapshot", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    sectionAnswers = [
      { status: 200, body: { ...OK, loaded: snapshot({ register_no: "V1", gender: "F" }) }, gate },
      { status: 200, body: OK },
    ];
    mockPersonal(identityAt("S1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("V1");
    pressSave(form);
    await waitFor(() => expect(saveButton(form).disabled).toBe(true));
    editRegister("V2");
    release();
    await waitFor(() => expect(saveButton(form).disabled).toBe(false));
    expect(registerBox().value).toBe("V2");

    // The refetch brings the saved value V1 as the stored and displayed one; the kept edit V2 differs, so it stays.
    mockPersonal(identityAt("V1"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    expect(registerBox().value).toBe("V2");
    expect(stripOf(form).hidden).toBe(false);

    pressSave(form);
    await waitFor(() => expect(sectionCalls("identity")).toHaveLength(2));
    await waitFor(() => expect(stripOf(form).hidden).toBe(true));
    const [, second] = await identityBodies();
    expect(second.values).toEqual({ register_no: "V2" });
    expect(JSON.parse(second.loaded)).toEqual({ register_no: "V1", gender: "F" });
  });
});

// ---- openMarked: a group with a dirty or failed section opens itself; a user-closed clean group stays closed (task 14b) ----

// The personal data with one section moved to another group (the fixture's identity section sits in «basic», which opens
// by default; «health» opens only by hand).
function inGroup(data: PersonalOut, name: string, group: string): PersonalOut {
  return { ...data, sections: data.sections.map((section) => (section.name === name ? { ...section, group } : section)) };
}

describe("openMarked: a group with unsaved or failed sections opens itself", () => {
  beforeEach(() => {
    sectionAnswers = [];
    fetchMock.mockReset();
    routeSections();
  });

  it("a dirty section opens its closed group, and a clean closed group stays closed", () => {
    mockPersonal(withLoaded(inGroup(personal(true), "identity", "health"), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    expect(groupEl("health").open).toBe(false);

    editRegister("УБ2");
    expect(groupEl("health").open).toBe(true);
    expect(groupEl("health").querySelector("summary")?.getAttribute("aria-expanded")).toBe("true");
    expect(groupEl("edu").open).toBe(false);
  });

  it("a failed save in a closed group opens it", async () => {
    sectionAnswers = [{ status: 400, body: { form_errors: [], field_errors: {} } }];
    mockPersonal(withLoaded(inGroup(personal(true), "identity", "health"), "L1"));
    renderPersonal(<PersonalSection pk={7} />);
    const form = identityForm();
    editRegister("УБ2");
    expect(groupEl("health").open).toBe(true);

    // The user closes the group by hand while the edit is unsaved; the edit keeps the section dirty.
    fireEvent.click(groupEl("health").querySelector("summary") as HTMLElement);
    expect(groupEl("health").open).toBe(false);

    pressSave(form);
    await waitFor(() => expect(screen.getByText("Мэдээллийг хадгалж чадсангүй.")).toBeTruthy());
    expect(groupEl("health").open).toBe(true);
    expect(groupEl("health").querySelector("summary")?.getAttribute("aria-expanded")).toBe("true");
  });

  it("a user-closed clean group stays closed after a refetch", () => {
    mockPersonal(withLoaded(personal(true), "L1"));
    const view = renderPersonal(<PersonalSection pk={7} />);
    expect(groupEl("basic").open).toBe(true);
    fireEvent.click(groupEl("basic").querySelector("summary") as HTMLElement);
    expect(groupEl("basic").open).toBe(false);

    mockPersonal(withLoaded(personal(true), "L2"));
    view.rerender(wrap(<PersonalSection pk={7} />));
    expect(groupEl("basic").open).toBe(false);
    expect(groupEl("basic").querySelector("summary")?.getAttribute("aria-expanded")).toBe("false");
  });
});
