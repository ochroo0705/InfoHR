import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import type { components } from "../../api/schema";
import { FilterBar } from "./FilterBar";

type ReportBarOut = components["schemas"]["ReportBarOut"];

const opt = (value: string, label: string) => ({ value, label });

// The bar as the API sends it, with the option lists the select controls read.
function barFixture(overrides: Partial<ReportBarOut> = {}): ReportBarOut {
  return {
    adds: [],
    clear_url: "/reports/x/?view=plain",
    column_chips: [],
    columns_query: "",
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

// Shows the router's address, so a test can read where a picker entry went.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderBar(bar: ReportBarOut, query: string, onChange = vi.fn()) {
  const view = render(
    <MemoryRouter initialEntries={["/reports/x/"]}>
      <FilterBar bar={bar} query={query} editQuery={query} onChange={onChange} />
      <Probe />
    </MemoryRouter>,
  );
  return { ...view, onChange };
}

const DEBOUNCE = 300;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("FilterBar", () => {
  it("bar_draws_only_items_from_api_in_order", () => {
    const bar = barFixture({
      items: [
        { name: "emptype", remove: "" },
        { name: "branch", remove: "/reports/x/?view=plain" },
        { name: "state", remove: "" },
      ],
    });
    const { container } = renderBar(bar, "");
    const drawn = Array.from(container.querySelectorAll("[data-filter]")).map((el) => el.getAttribute("data-filter"));
    expect(drawn).toEqual(["emptype", "branch", "state"]);
    // the gender select is not an item, so it is not drawn
    expect(container.querySelector('[data-filter="gender"]')).toBeNull();
  });

  it("the search box is the first control of the form", () => {
    const { container } = renderBar(barFixture(), "");
    const form = container.querySelector("form#report-filters");
    const first = form?.querySelector("input, select");
    expect(first?.getAttribute("name")).toBe("q");
    expect(first?.getAttribute("maxlength")).toBe("200");
    expect(first?.getAttribute("placeholder")).toBe("Хайх…");
    expect(first?.getAttribute("aria-label")).toBe("Тайлангаас хайх");
  });

  it("select_change_edits_only_its_parameter_and_keeps_others", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "" }] });
    const { onChange } = renderBar(bar, "add=branch&q=x&offset=40&sort=name&branch=5");
    fireEvent.change(screen.getByLabelText("Салбар"), { target: { value: "6" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("add=branch&q=x&sort=name&branch=6");
  });

  it("typed_q_navigates_after_debounce_and_not_per_keystroke", () => {
    const { onChange } = renderBar(barFixture(), "");
    const box = screen.getByLabelText("Тайлангаас хайх");
    fireEvent.change(box, { target: { value: "a" } });
    fireEvent.change(box, { target: { value: "ab" } });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE - 1);
    });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("q=ab");
  });

  it("enter_flushes_waiting_debounce", () => {
    const { onChange } = renderBar(barFixture(), "state=all");
    const box = screen.getByLabelText("Тайлангаас хайх");
    fireEvent.change(box, { target: { value: "abc" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("state=all&q=abc");
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE * 2);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("the search event flushes the waiting text too", () => {
    const { onChange } = renderBar(barFixture(), "");
    const box = screen.getByLabelText("Тайлангаас хайх");
    fireEvent.change(box, { target: { value: "dor" } });
    fireEvent(box, new Event("search"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("q=dor");
  });

  it("a search with the text already drawn sends nothing", () => {
    const { onChange } = renderBar(barFixture(), "q=abc");
    const box = screen.getByLabelText("Тайлангаас хайх");
    fireEvent.change(box, { target: { value: "abcd" } });
    fireEvent.change(box, { target: { value: "abc" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("remove_x_navigates_to_remove_href", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "/reports/x/?view=plain&q=abc" }] });
    renderBar(bar, "branch=5");
    const link = screen.getByLabelText("Шүүлтүүрийг арилгах");
    expect(link.getAttribute("href")).toBe("/reports/x/?view=plain&q=abc");
    expect(link.textContent).toBe("×");
    const wrap = document.querySelector("[data-filter-wrap]");
    expect(wrap?.querySelector('input[type="hidden"][name="add"]')?.getAttribute("value")).toBe("branch");
  });

  it("picker_entry_navigates_to_its_href_with_heading", () => {
    const bar = barFixture({
      picker: [
        { label: "Салбар", href: "/reports/x/?add=branch", heading: "Шүүлтүүр" },
        { label: "Хэлтэс", href: "/reports/x/?add=department", heading: "" },
        { label: "Нэр", href: "/reports/x/?add=name", heading: "Баганаар" },
      ],
    });
    renderBar(bar, "");
    expect(screen.getByText("Шүүлтүүр").tagName).toBe("P");
    expect(screen.getByText("Баганаар").tagName).toBe("P");
    fireEvent.click(screen.getByText("Хэлтэс"));
    expect(screen.getByTestId("loc").textContent).toBe("/reports/x/?add=department");
  });

  it("applied_marking_for_select_and_text", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "" }] });
    const { container, unmount } = renderBar(bar, "branch=6&q=abc");
    expect(container.querySelector('[data-filter="branch"]')?.hasAttribute("data-applied")).toBe(true);
    expect(container.querySelector('input[name="q"]')?.hasAttribute("data-applied")).toBe(true);
    unmount();

    const plain = renderBar(bar, "");
    expect(plain.container.querySelector('[data-filter="branch"]')?.hasAttribute("data-applied")).toBe(false);
    expect(plain.container.querySelector('input[name="q"]')?.hasAttribute("data-applied")).toBe(false);
  });

  it("clear_is_shown_only_while_something_is_applied", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "" }] });
    const { container, unmount } = renderBar(bar, "");
    const clear = container.querySelector("[data-filters-clear]");
    expect(clear?.getAttribute("href")).toBe("/reports/x/?view=plain");
    expect(clear?.hasAttribute("hidden")).toBe(true);
    unmount();

    const applied = renderBar(bar, "branch=5");
    expect(applied.container.querySelector("[data-filters-clear]")?.hasAttribute("hidden")).toBe(false);
  });

  it("a text typed without a send still counts as applied for «Цэвэрлэх»", () => {
    const { container } = renderBar(barFixture(), "");
    fireEvent.change(screen.getByLabelText("Тайлангаас хайх"), { target: { value: "x" } });
    expect(container.querySelector("[data-filters-clear]")?.hasAttribute("hidden")).toBe(false);
  });

  it("an address change from outside replaces the box text", () => {
    const { rerender, onChange } = renderBar(barFixture(), "q=one");
    const box = screen.getByLabelText("Тайлангаас хайх") as HTMLInputElement;
    expect(box.value).toBe("one");
    fireEvent.change(box, { target: { value: "one two" } });
    rerender(
      <MemoryRouter initialEntries={["/reports/x/"]}>
        <FilterBar bar={barFixture()} query="q=other" editQuery="q=other" onChange={onChange} />
      </MemoryRouter>,
    );
    expect(box.value).toBe("other");
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("clearing_after_a_send_still_sends_the_clear", () => {
    const bar = barFixture();
    const onChange = vi.fn();
    const tree = (query: string) => (
      <MemoryRouter initialEntries={["/reports/x/"]}>
        <FilterBar bar={bar} query={query} editQuery={query} onChange={onChange} />
      </MemoryRouter>
    );
    const { rerender } = render(tree("branch=5"));
    const box = screen.getByLabelText("Тайлангаас хайх") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "x" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenLastCalledWith("branch=5&q=x");
    // the address has not come back yet: the drawn q is still empty
    rerender(tree("branch=5"));
    fireEvent.change(box, { target: { value: "" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange).toHaveBeenLastCalledWith("branch=5");
  });

  it("picker_closes_on_outside_pointerdown", () => {
    renderBar(pickerBar(), "");
    fireEvent.click(screen.getByText("Шүүлтүүр нэмэх ▾"));
    const details = document.querySelector("details[data-column-picker]") as HTMLDetailsElement;
    expect(details.hasAttribute("open")).toBe(true);
    fireEvent.pointerDown(document.body);
    expect(details.hasAttribute("open")).toBe(false);
  });

  it("picker_closes_on_escape_only_while_open", () => {
    renderBar(pickerBar(), "");
    const details = document.querySelector("details[data-column-picker]") as HTMLDetailsElement;
    // closed: Escape is not consumed by the menu
    expect(fireEvent.keyDown(document, { key: "Escape" })).toBe(true);
    fireEvent.click(screen.getByText("Шүүлтүүр нэмэх ▾"));
    expect(details.hasAttribute("open")).toBe(true);
    // open: Escape closes it and is consumed
    expect(fireEvent.keyDown(document, { key: "Escape" })).toBe(false);
    expect(details.hasAttribute("open")).toBe(false);
  });

  it("picker_search_resets_each_time_it_opens", () => {
    renderBar(pickerBar(), "");
    fireEvent.click(screen.getByText("Шүүлтүүр нэмэх ▾"));
    const search = screen.getByLabelText("Шүүлтүүр хайх") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "абв" } });
    expect(search.value).toBe("абв");
    fireEvent.pointerDown(document.body);
    fireEvent.click(screen.getByText("Шүүлтүүр нэмэх ▾"));
    expect((screen.getByLabelText("Шүүлтүүр хайх") as HTMLInputElement).value).toBe("");
  });

  it("group_select_feeds_clear_visibility", () => {
    const base = barFixture();
    const bar = barFixture({
      options: { ...base.options, group_choices: [opt("branch", "Салбар")], group_text: "" },
    });
    const clearOf = (container: HTMLElement) => container.querySelector("[data-filters-clear]") as HTMLElement;

    const none = renderBar(bar, "");
    expect(screen.getByLabelText("Бүлэглэх")).not.toBeNull();
    expect(clearOf(none.container).hasAttribute("hidden")).toBe(true);
    none.unmount();

    const grouped = renderBar(bar, "group=branch");
    const group = screen.getByLabelText("Бүлэглэх") as HTMLSelectElement;
    expect(Array.from(group.options).map((o) => o.textContent)).toEqual(["Бүлэглэхгүй", "Салбар"]);
    expect(group.value).toBe("branch");
    expect(grouped.container.querySelector('[data-filters-clear]')?.hasAttribute("hidden")).toBe(false);
    fireEvent.change(group, { target: { value: "" } });
    expect(grouped.onChange).toHaveBeenCalledWith("");
  });

  it("no group select is drawn when the report offers no grouping", () => {
    renderBar(barFixture(), "group=branch");
    expect(screen.queryByLabelText("Бүлэглэх")).toBeNull();
  });
});

function pickerBar(): ReportBarOut {
  return barFixture({
    picker: [{ label: "Салбар", href: "/reports/x/?add=branch", heading: "Шүүлтүүр" }],
  });
}

// While a new address loads the bar shows the settled query, but every edit builds on the latest requested address.
describe("FilterBar while a new address loads", () => {
  it("two_selects_changed_during_a_load_compose", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "" }, { name: "state", remove: "" }] });
    const onChange = vi.fn();
    const tree = (query: string, editQuery: string) => (
      <MemoryRouter initialEntries={["/reports/x/"]}>
        <FilterBar bar={bar} query={query} editQuery={editQuery} onChange={onChange} />
      </MemoryRouter>
    );
    const { rerender } = render(tree("q=a", "q=a"));
    fireEvent.change(screen.getByLabelText("Салбар"), { target: { value: "6" } });
    expect(onChange).toHaveBeenLastCalledWith("q=a&branch=6");
    // the page asks for the first change; the settled query is still q=a
    rerender(tree("q=a", "q=a&branch=6"));
    fireEvent.change(screen.getByLabelText("Төлөв"), { target: { value: "all" } });
    expect(onChange).toHaveBeenLastCalledWith("q=a&branch=6&state=all");
  });

  // Typing while a select change is on its way keeps the select's parameter: the debounced send reads the latest address.
  it("typing_after_a_select_change_during_a_load_keeps_the_select", () => {
    const bar = barFixture({ items: [{ name: "branch", remove: "" }] });
    const onChange = vi.fn();
    const tree = (query: string, editQuery: string) => (
      <MemoryRouter initialEntries={["/reports/x/"]}>
        <FilterBar bar={bar} query={query} editQuery={editQuery} onChange={onChange} />
      </MemoryRouter>
    );
    const { rerender } = render(tree("q=a", "q=a"));
    fireEvent.change(screen.getByLabelText("Салбар"), { target: { value: "6" } });
    rerender(tree("q=a", "q=a&branch=6"));
    fireEvent.change(screen.getByLabelText("Тайлангаас хайх"), { target: { value: "x" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenLastCalledWith("q=x&branch=6");
  });
});
