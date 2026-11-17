import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEmployeePersonal } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { PersonalSection } from "./PersonalSection";

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
  const plainCol = { head_class: "", cell_class: "" };
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
        fields: [],
      },
      {
        name: "education",
        title: "Боловсрол",
        group: "edu",
        editable,
        rows: [{ label: "Боловсрол", display: "Бакалавр", empty: false }],
        fields: [],
      },
      {
        name: "other",
        title: "Бусад мэдээлэл",
        group: "other",
        editable,
        rows: [{ label: "Нэмэлт", display: "—", empty: true }],
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
        columns: [{ header: "Нэр", ...plainCol }],
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
          { header: "Он", head_class: "", cell_class: "whitespace-nowrap" },
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
  const plainCol = { head_class: "", cell_class: "" };
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
      { header: "Нэр", ...plainCol },
      { header: "Хамаатан", ...plainCol },
      { header: "Төрсөн он", ...plainCol },
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
    render(<PersonalSection pk={7} />);
    expect(document.querySelector("#menu-count-contact")?.textContent).toBe("2");
    expect(document.querySelector("#menu-count-contact")?.parentElement?.textContent).toBe("Холбоо барих, хаяг 2");
    expect(document.querySelector("#menu-count-family")?.textContent).toBe("2");
    expect(groupEl("basic").querySelector("summary")?.textContent).toContain("Холбоо барих, хаяг");
  });

  it("toggling a group flips aria-expanded and its open state", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
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
    render(<PersonalSection pk={7} />);
    const section = document.getElementById("sec-body");
    expect(section?.querySelector("h3")?.textContent).toBe("Эрүүл мэндийн үзлэг бүртгэгдээгүй");
    expect(section?.querySelector("table")).toBeNull();
  });

  it("the family list renders the API values in the API column order", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
    const rows = Array.from(document.querySelectorAll("#list-family tbody tr"));
    expect(rows.map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => td.textContent))).toEqual([
      ["Бат", "Хүү", "2015"],
      ["Сара", "—", "—"],
    ]);
  });

  it("the «Бусад мэдээлэл» count shows filled/total", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
    expect(document.querySelector("#menu-count-other")?.textContent).toBe("3/12");
  });

  it("a chip with visible false keeps its number hidden with invisible", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
    const relative = document.querySelector("#menu-count-relative");
    expect(relative?.classList.contains("invisible")).toBe(true);
    expect(relative?.parentElement?.className).toBe(CHIP_TONE);
    expect(document.querySelector("#menu-count-contact")?.classList.contains("invisible")).toBe(false);
  });

  it("a reader gets read rows, no soft boxes, no add button and no row clicks", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
    expect(document.querySelector("[data-on-spot]")).toBeNull();
    expect(screen.queryByText("+ нэмэх")).toBeNull();
    expect(document.querySelector("#sec-identity dl")?.textContent).toContain("Регистрийн дугаар");
    const nullCell = document.querySelector("#sec-identity dd span.text-slate-300");
    expect(nullCell?.textContent).toBe("—");
    fireEvent.click(document.querySelector("#list-family tbody tr") as HTMLElement);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a manager gets soft boxes and an add button, and the box opens the Django page", () => {
    mockPersonal(personal(true));
    render(<PersonalSection pk={7} />);
    expect(document.querySelector("#sec-identity-form[data-on-spot]")).not.toBeNull();
    expect(document.querySelector("#fields-identity")).not.toBeNull();
    const required = screen.getByText((_, el) => el?.tagName === "DT" && el.textContent === "Регистрийн дугаар *");
    expect(required).toBeTruthy();
    const gender = screen.getByLabelText("Хүйс") as HTMLSelectElement;
    expect(gender.options[0].textContent).toBe("Эмэгтэй");
    fireEvent.click(screen.getAllByText("+ нэмэх")[0]);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("a select with a quick-add list or 8+ options is a combo text box with its current text", () => {
    mockPersonal(personal(true));
    render(<PersonalSection pk={7} />);
    const city = screen.getByLabelText("Төрсөн аймаг, хот") as HTMLInputElement;
    expect(city.tagName).toBe("INPUT");
    expect(city.getAttribute("role")).toBe("combobox");
    expect(city.value).toBe("Улаанбаатар");
    expect(city.className).toContain("sel-combo");
    expect((screen.getByLabelText("Хүйс") as HTMLSelectElement).tagName).toBe("SELECT");
  });

  it("the address list sits in the contact section, and the education list in its section", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
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
    render(<PersonalSection pk={7} openGroup="edu" />);
    expect(groupEl("edu").open).toBe(true);
    expect(groupEl("award").open).toBe(false);
    expect(groupEl("basic").open).toBe(true);
  });

  it("a hash change to a group opens it and scrolls it into view", () => {
    mockPersonal(personal(false));
    render(<PersonalSection pk={7} />);
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
    render(<PersonalSection pk={7} />);
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
    render(<PersonalSection pk={7} />);
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(document.querySelector("details[data-pgroup]")).toBeNull();
  });
});
