import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { PersonalList } from "./PersonalList";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

type PersonalListOut = components["schemas"]["EmployeePersonalListOut"];

// An inline list (the family list) as the API sends it: headers without classes, cells already as display text.
function familyList(overrides: Partial<PersonalListOut> = {}): PersonalListOut {
  return {
    kind: "family",
    title: "Гэр бүл",
    group: "basic",
    parent: null,
    inline: true,
    editable: false,
    count: 2,
    empty_label: "",
    columns: [
      { header: "Нэр", head_class: "", cell_class: "" },
      { header: "Хамаатан", head_class: "", cell_class: "" },
      { header: "Төрсөн он", head_class: "", cell_class: "" },
    ],
    rows: [
      { key: "11", cells: ["Бат", "Хүү", "2015"] },
      { key: "12", cells: ["Сара", "—", "—"] },
    ],
    ...overrides,
  };
}

// A pop-up table list (the education list) as the API sends it: classes on the last columns, a cell class on «Голч».
function educationList(overrides: Partial<PersonalListOut> = {}): PersonalListOut {
  return {
    kind: "education",
    title: "Сурсан сургууль",
    group: "edu",
    parent: null,
    inline: false,
    editable: true,
    count: 1,
    empty_label: "",
    columns: [
      { header: "Сургууль", head_class: "", cell_class: "" },
      { header: "Он", head_class: "", cell_class: "whitespace-nowrap" },
      { header: "Голч", head_class: "text-right", cell_class: "text-right" },
      { header: "Диплом №", head_class: "pl-6", cell_class: "pl-6" },
    ],
    rows: [{ key: "7", cells: ["ХИС", "2010–2014", "3.2", "D-0001"] }],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
});

describe("PersonalList", () => {
  it("renders an inline list's values in the API column order", () => {
    const { container } = render(<PersonalList list={familyList()} pk={7} editable={false} />);

    const headers = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(headers).toEqual(["Нэр", "Хамаатан", "Төрсөн он"]);

    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.map((tr) => tr.getAttribute("data-row-key"))).toEqual(["11", "12"]);
    expect(Array.from(rows[0].querySelectorAll("td")).map((td) => td.textContent)).toEqual(["Бат", "Хүү", "2015"]);
    expect(Array.from(rows[1].querySelectorAll("td")).map((td) => td.textContent)).toEqual(["Сара", "—", "—"]);
  });

  it("wraps an inline list in its data-inline-list block and a pop-up list in none", () => {
    const { container: inline } = render(<PersonalList list={familyList()} pk={7} editable={false} />);
    const block = inline.querySelector("#list-family");
    expect(block?.hasAttribute("data-inline-list")).toBe(true);
    cleanup();

    const { container: popup } = render(<PersonalList list={educationList()} pk={7} editable={false} />);
    expect(popup.querySelector("[data-inline-list]")).toBeNull();
    expect(popup.querySelector("[id^='list-']")).toBeNull();
    expect(popup.querySelector("tbody tr")?.hasAttribute("data-row-key")).toBe(false);
  });

  it("applies the API's head and cell classes, and none for the empty ones", () => {
    const { container } = render(<PersonalList list={educationList()} pk={7} editable={false} />);

    const ths = Array.from(container.querySelectorAll("thead th"));
    expect(ths.map((th) => th.getAttribute("class"))).toEqual([null, null, "text-right", "pl-6"]);

    const tds = Array.from(container.querySelectorAll("tbody td"));
    expect(tds.map((td) => td.getAttribute("class"))).toEqual([null, "whitespace-nowrap", "text-right", "pl-6"]);
  });

  it("shows the empty label beside the title when the list has no rows", () => {
    const list = familyList({ count: 0, empty_label: "бүртгэгдээгүй", rows: [] });
    const { container } = render(<PersonalList list={list} pk={7} editable={false} />);

    expect(screen.getByText("бүртгэгдээгүй").className).toBe("ml-1 text-sm font-normal text-slate-400");
    expect(container.querySelector("h3.sec-title")?.textContent).toBe("Гэр бүл бүртгэгдээгүй");
    expect(container.querySelector("table")).toBeNull();
  });

  it("shows no empty label and no table for a filled list's title", () => {
    const { container } = render(<PersonalList list={educationList()} pk={7} editable={false} />);

    expect(container.querySelector("h3.sec-title")?.textContent).toBe("Сурсан сургууль");
    expect(container.querySelector(".ptable table")).not.toBeNull();
  });

  it("opens the Django employee page when «+ нэмэх» is clicked", () => {
    render(<PersonalList list={educationList()} pk={7} editable={true} />);

    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("opens the Django employee page when a pop-up row is clicked and the list is editable", () => {
    const { container } = render(<PersonalList list={educationList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("opens the Django employee page when an inline row is clicked and the list is editable", () => {
    const { container } = render(<PersonalList list={familyList({ editable: true })} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='12']") as HTMLElement);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("adds the action column to an editable inline list only", () => {
    const { container: editable } = render(
      <PersonalList list={familyList({ editable: true })} pk={7} editable={true} />,
    );
    expect(editable.querySelectorAll("thead th")).toHaveLength(4);
    expect(editable.querySelector("tbody tr")?.querySelectorAll("td")).toHaveLength(4);
    cleanup();

    const { container: readonly } = render(<PersonalList list={familyList()} pk={7} editable={false} />);
    expect(readonly.querySelectorAll("thead th")).toHaveLength(3);
    expect(readonly.querySelector("tbody tr")?.querySelectorAll("td")).toHaveLength(3);
  });

  it("shows no add button and opens nothing on a row click when not editable", () => {
    const { container } = render(<PersonalList list={educationList({ editable: false })} pk={7} editable={false} />);

    expect(screen.queryByRole("button", { name: "+ нэмэх" })).toBeNull();
    const row = container.querySelector("tbody tr") as HTMLElement;
    expect(row.getAttribute("class")).toBe("");
    fireEvent.click(row);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });
});
