import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  OrderRegisterAllLabelsOut,
  OrderRegisterOptionsOut,
  OrderRegisterQueryOut,
  RegisterParams,
} from "../../api/orderRegister";
import { MemoryRouter } from "react-router";
import { RegisterFilters, type RegisterFiltersProps } from "./RegisterFilters";

const OPTIONS: OrderRegisterOptionsOut = {
  years: [
    { value: "2024", label: "2024" },
    { value: "2025", label: "2025" },
  ],
  types: [{ value: "1", label: "Ажилд авах" }],
  departments: [{ value: "4", label: "Санхүү" }],
  states: [{ value: "signed", label: "Гарын үсэгтэй" }],
};

const LABELS: OrderRegisterAllLabelsOut = {
  year: "Бүх он",
  order_type: "Бүх төрөл",
  department: "Бүх хэлтэс",
  state: "Бүх төлөв",
};

const NOTHING: OrderRegisterQueryOut = {
  year: null,
  order_type: null,
  department: null,
  q: "",
  sort: "-date",
  state: "",
};

const NO_PICKS: RegisterParams = {
  q: "",
  sort: "-date",
  year: "",
  order_type: "",
  department: "",
  state: "",
};

const DEBOUNCE = 300;

// The filter bar holds a link that uses the router («Цэвэрлэх» is a client link on a ported path), so every render
// sits inside a MemoryRouter.
function Routed(props: RegisterFiltersProps) {
  return (
    <MemoryRouter>
      <RegisterFilters {...props} />
    </MemoryRouter>
  );
}


function field(container: HTMLElement, name: string): HTMLInputElement & HTMLSelectElement {
  const el = container.querySelector(`[name="${name}"]`);
  if (!el) throw new Error(`no [name=${name}]`);
  return el as HTMLInputElement & HTMLSelectElement;
}

// The page as the tests drive it: `params` is the address, and each onChange writes it (the parent does this at once).
function renderFilters(
  initial: Partial<RegisterParams> = {},
  onChange: (p: RegisterParams) => void = vi.fn(),
) {
  const view = render(
    <Routed
      options={OPTIONS}
      query={NOTHING}
      allLabels={LABELS}
      params={{ ...NO_PICKS, ...initial }}
      settled
      onChange={onChange}
    />,
  );
  return {
    container: view.container,
    address(p: Partial<RegisterParams>) {
      view.rerender(
        <Routed
          options={OPTIONS}
          query={NOTHING}
          allLabels={LABELS}
          params={{ ...NO_PICKS, ...p }}
          settled
          onChange={onChange}
        />,
      );
    },
  };
}

describe("RegisterFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("typing in q calls onChange once after 300 ms", () => {
    const onChange = vi.fn();
    const { container } = renderFilters({}, onChange);
    const q = field(container, "q");
    fireEvent.change(q, { target: { value: "Б" } });
    fireEvent.change(q, { target: { value: "Бат" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE - 1);
    });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ ...NO_PICKS, q: "Бат" });
  });

  it("Enter in the search box sends at once and drops the pending quiet-time send", () => {
    const onChange = vi.fn();
    const { container } = renderFilters({}, onChange);
    fireEvent.change(field(container, "q"), { target: { value: "Бат" } });
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ ...NO_PICKS, q: "Бат" });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("picking a select calls onChange immediately", () => {
    const onChange = vi.fn();
    const { container } = renderFilters({}, onChange);
    fireEvent.change(field(container, "year"), { target: { value: "2025" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ year: "2025", q: "" }));
  });

  it("a cleaned echo (year empty) shows «Бүх он» only when settled", () => {
    const onChange = vi.fn();
    const { container } = renderFilters({ year: "abc" }, onChange);
    const year = field(container, "year");
    expect(year.value).toBe("");
    expect(year.selectedOptions[0]?.textContent).toBe("Бүх он");
    // Not settled yet: the pick in the address shows.
    const view = render(
      <Routed
        options={OPTIONS}
        query={NOTHING}
        allLabels={LABELS}
        params={{ ...NO_PICKS, year: "abc" }}
        settled={false}
        onChange={vi.fn()}
      />,
    );
    expect(field(view.container, "year").value).toBe("abc");
  });

  it("a pick stays shown while settled is false", () => {
    const view = render(
      <Routed
        options={OPTIONS}
        query={NOTHING}
        allLabels={LABELS}
        params={{ ...NO_PICKS, year: "2025" }}
        settled={false}
        onChange={vi.fn()}
      />,
    );
    expect(field(view.container, "year").value).toBe("2025");
  });

  it("two picks before an answer keep both in the second payload", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    fireEvent.change(field(container, "year"), { target: { value: "2025" } });
    const first = onChange.mock.calls[0]?.[0] as RegisterParams;
    // The page stores the pick in the address; the answer has not come back yet.
    address(first);
    fireEvent.change(field(container, "department"), { target: { value: "4" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...NO_PICKS, year: "2025", department: "4" });
  });

  it("typing «Бат» then «Бат Дорж» keeps what was typed while the address follows each send", () => {
    const { container, address } = renderFilters();
    const q = field(container, "q");
    fireEvent.change(q, { target: { value: "Бат" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    address({ q: "Бат" });
    fireEvent.change(q, { target: { value: "Бат Дорж" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    address({ q: "Бат Дорж" });
    expect(field(container, "q").value).toBe("Бат Дорж");
  });

  it("back button: the address changes to an earlier text, the box shows it and the next pick sends it", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    const q = field(container, "q");
    fireEvent.change(q, { target: { value: "Бат" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    address({ q: "Бат" });
    fireEvent.change(q, { target: { value: "Бат Дорж" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    address({ q: "Бат Дорж" });
    address({ q: "Бат" });
    expect(field(container, "q").value).toBe("Бат");
    fireEvent.change(field(container, "year"), { target: { value: "2025" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...NO_PICKS, q: "Бат", year: "2025" });
  });

  it("«Цэвэрлэх»-style change of the address to an empty text empties the box", () => {
    const { container, address } = renderFilters({ q: "Бат" });
    expect(field(container, "q").value).toBe("Бат");
    address({ q: "" });
    expect(field(container, "q").value).toBe("");
  });

  it("an address change within the 300 ms window cancels the pending send", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    fireEvent.change(field(container, "q"), { target: { value: "Бат" } });
    address({ q: "Бат Дорж" });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(field(container, "q").value).toBe("Бат Дорж");
  });

  it("a page pick made within the 300 ms window is kept in the next payload", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    fireEvent.change(field(container, "q"), { target: { value: "Бат" } });
    address({ year: "2025" });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ ...NO_PICKS, q: "Бат", year: "2025" });
  });

  it("two emissions the parent has not rendered yet do not revert the box", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    const q = field(container, "q");
    fireEvent.change(q, { target: { value: "Бат" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    fireEvent.change(q, { target: { value: "Бат Дорж" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledTimes(2);
    // The first render (of "Бат") arrives late, after "Бат Дорж" was passed up.
    address({ q: "Бат" });
    expect(field(container, "q").value).toBe("Бат Дорж");
    address({ q: "Бат Дорж" });
    expect(field(container, "q").value).toBe("Бат Дорж");
    // Both renders have been seen: a back navigation to "Бат" is an outside change.
    address({ q: "Бат" });
    expect(field(container, "q").value).toBe("Бат");
  });

  it("a late render does not cancel a send that is still waiting for its quiet time", () => {
    const onChange = vi.fn();
    const { container, address } = renderFilters({}, onChange);
    const q = field(container, "q");
    fireEvent.change(q, { target: { value: "Бат" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    fireEvent.change(q, { target: { value: "Бат Дорж" } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    fireEvent.change(q, { target: { value: "Бат Дорж А" } });
    address({ q: "Бат" });
    expect(field(container, "q").value).toBe("Бат Дорж А");
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(onChange).toHaveBeenLastCalledWith({ ...NO_PICKS, q: "Бат Дорж А" });
  });

  it("the text sent is the cleaned text (stripped), while the box keeps what is typed", () => {
    const onChange = vi.fn();
    const { container } = renderFilters({}, onChange);
    fireEvent.change(field(container, "q"), { target: { value: "  Бат  " } });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE);
    });
    expect(onChange).toHaveBeenCalledWith({ ...NO_PICKS, q: "Бат" });
    expect(field(container, "q").value).toBe("  Бат  ");
  });
});
