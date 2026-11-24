import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type {
  EmployeeLogParams,
  LogChipOut,
  LogEmployeeOptionsOut,
  LogEmployeeQueryOut,
} from "../../api/logs";
import { EmployeeLogFilters, type EmployeeLogFiltersProps } from "./EmployeeLogFilters";

const OPTIONS: LogEmployeeOptionsOut = {
  areas: [{ value: "employee", label: "Ажилтан" }],
  kinds: [
    { value: "hire", label: "Томилгоо" },
    { value: "leave", label: "Чөлөө" },
  ],
};

const NOTHING: LogEmployeeQueryOut = {
  area: "",
  by: "",
  date_from: "",
  date_to: "",
  emp: "",
  employee: null,
  field: "",
  kinds: [],
  oldest: false,
  q: "",
  system: false,
};

const NO_PICKS: EmployeeLogParams = {
  q: "",
  emp: "",
  employee: "",
  by: "",
  kind: [],
  area: "",
  field: "",
  from: "",
  to: "",
  system: "",
  oldest: "",
};

const DEBOUNCE = 300;

function Routed(props: EmployeeLogFiltersProps) {
  return (
    <MemoryRouter>
      <EmployeeLogFilters {...props} />
    </MemoryRouter>
  );
}

function renderFilters(
  overrides: Partial<EmployeeLogFiltersProps> = {},
  params: Partial<EmployeeLogParams> = {},
) {
  const onChange = vi.fn();
  const chip: LogChipOut | null = overrides.chip ?? null;
  const view = render(
    <Routed
      query={NOTHING}
      options={OPTIONS}
      chip={chip}
      params={{ ...NO_PICKS, ...params }}
      settled
      onChange={onChange}
      {...overrides}
    />,
  );
  return { ...view, onChange };
}

function field(container: HTMLElement, name: string): HTMLInputElement {
  const el = container.querySelector(`[name="${name}"]`);
  if (!el) throw new Error(`no [name=${name}]`);
  return el as HTMLInputElement;
}

describe("EmployeeLogFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("text boxes show what the address holds, not the server echo", () => {
    const { container } = renderFilters(
      { query: { ...NOTHING, q: "чистый", emp: "Бат", by: "Болд", field: "Хаяг" } },
      { q: "  чистый  ", emp: "  Бат  ", by: "  Болд  ", field: "  Хаяг  " },
    );
    expect(field(container, "q").value).toBe("  чистый  ");
    expect(field(container, "emp").value).toBe("  Бат  ");
    expect(field(container, "by").value).toBe("  Болд  ");
    expect(field(container, "field").value).toBe("  Хаяг  ");
  });

  it("the selects and the sort show the echo once settled", () => {
    const { container } = renderFilters(
      { query: { ...NOTHING, area: "", oldest: true } },
      { area: "bogus", oldest: "" },
    );
    expect(field(container, "area").value).toBe("");
    expect(field(container, "oldest").value).toBe("1");
  });

  it("the selects show the address while the data is not settled", () => {
    const { container } = renderFilters(
      { settled: false, query: { ...NOTHING, area: "" } },
      { area: "employee", oldest: "1" },
    );
    expect(field(container, "area").value).toBe("employee");
    expect(field(container, "oldest").value).toBe("1");
  });

  it("typing in q calls onChange once after 300 ms", () => {
    const { container, onChange } = renderFilters({}, { kind: ["hire"] });
    fireEvent.change(field(container, "q"), { target: { value: "абв" } });
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(DEBOUNCE - 1));
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ q: "абв", kind: ["hire"] }));
  });

  it.each([
    ["emp", "Бат"],
    ["by", "Болд"],
    ["field", "Хаяг"],
  ])("typing in %s calls onChange once after 300 ms", (name, value) => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, name), { target: { value } });
    act(() => vi.advanceTimersByTime(DEBOUNCE - 1));
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ [name]: value }));
  });

  it("Enter in a search box sends that box at once", () => {
    const { container, onChange } = renderFilters({}, { emp: "" });
    fireEvent.change(field(container, "emp"), { target: { value: "Бат" } });
    fireEvent.keyDown(field(container, "emp"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ emp: "Бат" }));

    act(() => vi.advanceTimersByTime(DEBOUNCE));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("the area select calls onChange at once with its value", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "area"), { target: { value: "employee" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ area: "employee" }));
  });

  it("the sort select calls onChange at once with 1 for oldest first", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "oldest"), { target: { value: "1" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ oldest: "1" }));
  });

  it("the area and sort selects are found by their Mongolian labels", () => {
    const { container } = renderFilters();
    const area = screen.getByLabelText("Хэсэг") as HTMLSelectElement;
    const oldest = screen.getByLabelText("Эрэмбэ") as HTMLSelectElement;
    expect(area.tagName).toBe("SELECT");
    expect(area.name).toBe("area");
    expect(oldest.tagName).toBe("SELECT");
    expect(oldest.name).toBe("oldest");
    expect(container.querySelector("#log-area")).toBe(area);
    expect(container.querySelector("#log-oldest")).toBe(oldest);
  });

  it("picking a kind calls onChange at once with the repeated values", () => {
    // Settled, so the boxes show the echo: the echo must carry the same kinds as the address.
    const { container, onChange } = renderFilters({ query: { ...NOTHING, kinds: ["hire"] } }, { kind: ["hire"] });
    const leave = container.querySelector('input[type="checkbox"][value="leave"]') as HTMLInputElement;
    fireEvent.click(leave);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kind: ["hire", "leave"] }));
  });

  it("the system box sends 1 when ticked and nothing when not", () => {
    const first = renderFilters();
    fireEvent.click(field(first.container, "system"));
    expect(first.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ system: "1" }));
    cleanup();

    // Settled, so the box shows the echo: the echo must be ticked to start from ticked.
    const second = renderFilters({ query: { ...NOTHING, system: true } }, { system: "1" });
    fireEvent.click(field(second.container, "system"));
    expect(second.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ system: "" }));
  });

  it("a date can be typed: partial text stays in the box and reaches the address only when whole", () => {
    const { container, onChange } = renderFilters();
    const box = field(container, "from");
    fireEvent.change(box, { target: { value: "2" } });
    expect(box.value).toBe("2");
    fireEvent.change(box, { target: { value: "2026-1" } });
    expect(box.value).toBe("2026-1");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "2026-11-01" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ from: "2026-11-01" }));
    fireEvent.change(box, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ from: "" }));
  });

  it("the date boxes call onChange at once", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "from"), { target: { value: "2026-11-01" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ from: "2026-11-01" }));
    fireEvent.change(field(container, "to"), { target: { value: "2026-11-30" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ to: "2026-11-30" }));
  });

  it("the chip remove link keeps the other filters", () => {
    const { container } = renderFilters(
      { chip: { id: 7, name: "Бат Болд" } },
      { employee: "7", q: "x", kind: ["hire"], oldest: "1" },
    );
    const chip = container.querySelector('a[aria-label="Хасах"]') as HTMLAnchorElement;
    expect(chip.getAttribute("href")).toBe("/logs/?q=x&kind=hire&oldest=1");
    expect(container.textContent).toContain("Ажилтан: Бат Болд");
    expect(field(container, "employee").value).toBe("7");
  });

  it("the chip remove link goes to the bare log when nothing else is set", () => {
    const { container } = renderFilters({ chip: { id: 7, name: "Бат Болд" } }, { employee: "7" });
    const chip = container.querySelector('a[aria-label="Хасах"]') as HTMLAnchorElement;
    expect(chip.getAttribute("href")).toBe("/logs/");
  });

  it("a change of the q address from outside (not the chip ×) shows in the q box", () => {
    const { container, rerender } = render(
      <Routed
        query={NOTHING}
        options={OPTIONS}
        chip={null}
        params={{ ...NO_PICKS, q: "old" }}
        settled
        onChange={vi.fn()}
      />,
    );
    rerender(
      <Routed query={NOTHING} options={OPTIONS} chip={null} params={{ ...NO_PICKS, q: "" }} settled onChange={vi.fn()} />,
    );
    expect(field(container, "q").value).toBe("");
  });

  it("shows no chip without a person", () => {
    const { container } = renderFilters();
    expect(container.querySelector('a[aria-label="Хасах"]')).toBeNull();
  });

  it("«Цэвэрлэх» links to the bare log", () => {
    const { container } = renderFilters();
    const clear = Array.from(container.querySelectorAll("a")).find((a) => a.textContent === "Цэвэрлэх");
    expect(clear?.getAttribute("href")).toBe("/logs/");
  });
});
