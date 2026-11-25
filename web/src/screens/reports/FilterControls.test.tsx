import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { filterControlApplied, renderFilterControl, type FilterControlContext } from "./FilterControls";

type ReportBarOut = components["schemas"]["ReportBarOut"];

const opt = (value: string, label: string) => ({ value, label });

// The bar as the API sends it, with only the option lists these controls read.
function barFixture(): ReportBarOut {
  return {
    adds: [],
    clear_url: "/reports/x/?view=plain",
    column_chips: [],
    columns_query: "",
    items: [],
    picker: [],
    options: {
      absence_types: [],
      attributes: [opt("gender", "Хүйс"), opt("age", "Насны бүлэг")],
      branches: [opt("5", "Улаанбаатар"), opt("6", "Дархан")],
      change_kinds: [],
      contact_types: [],
      departments: [opt("8", "Санхүү")],
      discipline_types: [],
      emptypes: [opt("1", "Ажилчид"), opt("2", "Гадаад нөөц"), opt("5", "Гэрээт ажилтан")],
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
      states: [opt("working", "Ажиллаж байгаа"), opt("upcoming", "Удахгүй ажилд орох"), opt("left", "Гарсан"), opt("all", "Бүгд")],
      training_types: [],
      year: null,
    },
  } as ReportBarOut;
}

function ctxOf(query: string, onChange = vi.fn()): FilterControlContext {
  return { bar: barFixture(), query, onChange };
}

function drawn(name: string, ctx: FilterControlContext) {
  return render(<>{renderFilterControl(name, ctx)}</>);
}

afterEach(() => {
  cleanup();
});

describe("FilterControls", () => {
  it("returns null for a name this module does not draw", () => {
    expect(renderFilterControl("q", ctxOf(""))).toBeNull();
    expect(renderFilterControl("group", ctxOf(""))).toBeNull();
    expect(renderFilterControl("nope", ctxOf(""))).toBeNull();
  });

  it("select lists its «Бүх …» entry first and reads the value from the address", () => {
    drawn("branch", ctxOf("branch=6"));
    const select = screen.getByLabelText("Салбар") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("6");
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toEqual(["Бүх салбар", "Улаанбаатар", "Дархан"]);
  });

  it("a dirty address shows the cleaned value, falling back to the default when absent", () => {
    // the API's cleaned query is what the bar receives; an absent parameter shows the default entry
    drawn("emptype", ctxOf("q=x"));
    expect((screen.getByLabelText("Ажилтны төрөл") as HTMLSelectElement).value).toBe("");
  });

  it("applied_marking_for_select", () => {
    const { container, unmount } = drawn("branch", ctxOf("branch=6"));
    expect(container.querySelector('[data-filter="branch"]')?.hasAttribute("data-applied")).toBe(true);
    unmount();

    const plain = drawn("branch", ctxOf(""));
    expect(plain.container.querySelector('[data-filter="branch"]')?.hasAttribute("data-applied")).toBe(false);
    expect(filterControlApplied("branch", ctxOf(""))).toBe(false);
    expect(filterControlApplied("branch", ctxOf("branch=5"))).toBe(true);
  });

  it("attribute is a plain name and never marked applied", () => {
    const { container } = drawn("attribute", ctxOf("attribute=age"));
    expect((screen.getByLabelText("Шинж") as HTMLSelectElement).value).toBe("age");
    expect(container.querySelector('[data-filter="attribute"]')?.hasAttribute("data-applied")).toBe(false);
  });

  it("state_select_disabled_when_emptype_has_no_working_state", () => {
    drawn("state", ctxOf("emptype=2&state=all"));
    const state = screen.getByLabelText("Төлөв") as HTMLSelectElement;
    expect(state.disabled).toBe(true);
    // a disabled control never applies
    expect(filterControlApplied("state", ctxOf("emptype=2&state=all"))).toBe(false);
  });

  it("state_select_enabled_for_a_working_type", () => {
    drawn("state", ctxOf("emptype=1&state=all"));
    const state = screen.getByLabelText("Төлөв") as HTMLSelectElement;
    expect(state.disabled).toBe(false);
    expect(state.value).toBe("all");
    expect(filterControlApplied("state", ctxOf("emptype=1&state=all"))).toBe(true);
  });

  it("state default is its first entry, so not applied", () => {
    expect(filterControlApplied("state", ctxOf("state=working"))).toBe(false);
    expect(filterControlApplied("state", ctxOf(""))).toBe(false);
  });

  it("a change calls onChange with the name and the chosen value", () => {
    const onChange = vi.fn();
    drawn("gender", ctxOf("", onChange));
    fireEvent.change(screen.getByLabelText("Хүйс"), { target: { value: "F" } });
    expect(onChange).toHaveBeenCalledWith("gender", "F");
  });

  it("date_filter_uses_datepicker_not_native_date", () => {
    const { container } = drawn("period", ctxOf(""));
    const from = screen.getByLabelText("Эхлэх огноо") as HTMLInputElement;
    expect(from.type).toBe("text");
    expect(from.closest(".dp-wrap")).not.toBeNull();
    expect(from.value).toBe("2026-01-01");
    expect(screen.getByLabelText("Дуусах огноо")).not.toBeNull();
    expect(container.querySelector('input[type="date"]')).toBeNull();
  });

  it("period_commit_on_blur_not_per_keystroke", () => {
    const onChange = vi.fn();
    drawn("period", ctxOf("", onChange));
    const from = screen.getByLabelText("Эхлэх огноо");
    fireEvent.change(from, { target: { value: "2026-02-0" } });
    fireEvent.change(from, { target: { value: "2026-02-01" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(from);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("from", "2026-02-01");
  });

  it("a date box commits on Enter and a picked day commits at once", () => {
    const onChange = vi.fn();
    drawn("period", ctxOf("", onChange));
    const to = screen.getByLabelText("Дуусах огноо");
    fireEvent.change(to, { target: { value: "2026-03-31" } });
    fireEvent.keyDown(to, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("to", "2026-03-31");

    fireEvent.click(screen.getByLabelText("Эхлэх огноо"));
    const day = Array.from(document.querySelectorAll(".dp-popup .dp-day")).find(
      (b) => b.textContent === "15" && !b.classList.contains("dp-other"),
    ) as HTMLButtonElement;
    onChange.mockClear();
    fireEvent.click(day);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("from", "2026-01-15");
  });

  it("a calendar navigation press keeps the typed date until the box is left", () => {
    const onChange = vi.fn();
    drawn("period", ctxOf("", onChange));
    const from = screen.getByLabelText("Эхлэх огноо");
    fireEvent.click(from); // opens the calendar
    fireEvent.change(from, { target: { value: "1985-03-02" } });
    const previous = document.querySelector(".dp-popup .dp-nav") as HTMLElement; // the ‹ arrow
    fireEvent.mouseDown(previous);
    fireEvent.click(previous);
    expect(onChange).not.toHaveBeenCalled();
    // the press left the box for the calendar; leaving the calendar for the page commits the typed date once
    fireEvent.blur(from);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("from", "1985-03-02");
  });

  it("employee_control_lists_people_from_the_api", () => {
    const onChange = vi.fn();
    const ctx = withOptions({ people: [opt("11", "Ажилтан А"), opt("12", "Ажилтан Б")] }, "employee=12", onChange);
    drawn("employee", ctx);
    const select = screen.getByLabelText("Ажилтан") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "Бүх ажилтан",
      "Ажилтан А",
      "Ажилтан Б",
    ]);
    expect(select.value).toBe("12");
    expect(filterControlApplied("employee", ctx)).toBe(true);
    fireEvent.change(select, { target: { value: "11" } });
    expect(onChange).toHaveBeenCalledWith("employee", "11");
  });

  it("age_range_edits_both_params", () => {
    const onChange = vi.fn();
    const { container } = drawn("age_range", ctxOf("age_from=20&age_to=40", onChange));
    const low = screen.getByLabelText("Доод нас") as HTMLInputElement;
    const high = screen.getByLabelText("Дээд нас") as HTMLInputElement;
    expect(low.value).toBe("20");
    expect(high.value).toBe("40");
    expect(container.querySelector('[data-filter="age_range"]')?.hasAttribute("data-applied")).toBe(true);

    fireEvent.change(high, { target: { value: "45" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(high);
    expect(onChange).toHaveBeenLastCalledWith("age_to", "45");

    fireEvent.change(low, { target: { value: "25" } });
    fireEvent.keyDown(low, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("age_from", "25");
  });

  it("year_and_quarter_selects_default_not_applied", () => {
    const withYear = withOptions({ year: 2026, quarter: 2 }, "", vi.fn());
    drawn("year", withYear);
    expect((screen.getByLabelText("Он") as HTMLInputElement).value).toBe("2026");
    expect(filterControlApplied("year", withYear)).toBe(false);

    drawn("quarter", withYear);
    const quarter = screen.getByLabelText("Улирал") as HTMLSelectElement;
    expect(quarter.value).toBe("2");
    expect(Array.from(quarter.options).map((o) => o.textContent)).toEqual([
      "1-р улирал",
      "2-р улирал",
      "3-р улирал",
      "4-р улирал",
    ]);
    expect(filterControlApplied("quarter", withYear)).toBe(false);
    // a value the address sets is still a plain name: never applied
    expect(filterControlApplied("quarter", withOptions({ quarter: 3 }, "quarter=3", vi.fn()))).toBe(false);

    // mode is a select with a default first entry: only the children mode is applied
    expect(filterControlApplied("mode", ctxOf(""))).toBe(false);
    expect(filterControlApplied("mode", ctxOf("mode=children"))).toBe(true);
  });
});

// The fixture with some option lists replaced, and the address and onChange of the test.
function withOptions(over: Partial<ReportBarOut["options"]>, query: string, onChange: (name: string, value: string) => void) {
  const base = barFixture();
  return { bar: { ...base, options: { ...base.options, ...over } }, query, onChange };
}
