import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { LogSystemOptionsOut, LogSystemQueryOut, SystemLogParams } from "../../api/logs";
import { SystemLogFilters, type SystemLogFiltersProps } from "./SystemLogFilters";

const OPTIONS: LogSystemOptionsOut = {
  actions: [
    { value: "login", label: "Нэвтрэх" },
    { value: "update", label: "Засах" },
  ],
  categories: [
    { value: "auth", label: "Нэвтрэлт" },
    { value: "data", label: "Өгөгдөл" },
  ],
};

const NOTHING: LogSystemQueryOut = {
  action: "",
  by: "",
  categories: [],
  date_from: "",
  date_to: "",
  ip: "",
  oldest: false,
  q: "",
  target: "",
};

const NO_PICKS: SystemLogParams = {
  q: "",
  by: "",
  target: "",
  ip: "",
  category: [],
  action: "",
  from: "",
  to: "",
  oldest: "",
};

const DEBOUNCE = 300;

function Routed(props: SystemLogFiltersProps) {
  return (
    <MemoryRouter>
      <SystemLogFilters {...props} />
    </MemoryRouter>
  );
}

function renderFilters(
  overrides: Partial<SystemLogFiltersProps> = {},
  params: Partial<SystemLogParams> = {},
) {
  const onChange = vi.fn();
  const view = render(
    <Routed
      query={NOTHING}
      options={OPTIONS}
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

describe("SystemLogFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("text boxes show what the address holds, not the server echo", () => {
    const { container } = renderFilters(
      { query: { ...NOTHING, q: "чистый", by: "Болд", target: "Бат", ip: "10.0.0.1" } },
      { q: "  чистый  ", by: "  Болд  ", target: "  Бат  ", ip: "  10.0.  " },
    );
    expect(field(container, "q").value).toBe("  чистый  ");
    expect(field(container, "by").value).toBe("  Болд  ");
    expect(field(container, "target").value).toBe("  Бат  ");
    expect(field(container, "ip").value).toBe("  10.0.  ");
  });

  it("filters show the echoed clean values", () => {
    const { container } = renderFilters(
      { query: { ...NOTHING, action: "", oldest: true, categories: ["auth"], date_from: "2026-11-01", date_to: "2026-11-30" } },
      { action: "bogus", oldest: "", category: ["zzz", "auth"], from: "2026-10-01", to: "2026-10-31" },
    );
    expect(field(container, "action").value).toBe("");
    expect(field(container, "oldest").value).toBe("1");
    expect(field(container, "from").value).toBe("2026-11-01");
    expect(field(container, "to").value).toBe("2026-11-30");
    const summary = container.querySelector("summary") as HTMLElement;
    expect(summary.textContent).toBe("Ангилал · 1 ▾");
  });

  it("the selects and the category menu show the address while the data is not settled", () => {
    const { container } = renderFilters(
      { settled: false, query: { ...NOTHING, action: "" } },
      { action: "login", oldest: "1", category: ["auth", "data"] },
    );
    expect(field(container, "action").value).toBe("login");
    expect(field(container, "oldest").value).toBe("1");
    expect((container.querySelector("summary") as HTMLElement).textContent).toBe("Ангилал · 2 ▾");
  });

  it("typing in q calls onChange once after 300 ms", () => {
    const { container, onChange } = renderFilters({}, { category: ["auth"] });
    fireEvent.change(field(container, "q"), { target: { value: "абв" } });
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(DEBOUNCE - 1));
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ q: "абв", category: ["auth"] }));
  });

  it.each([
    ["by", "Болд"],
    ["target", "Ажилтан"],
    ["ip", "10.0."],
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
    const { container, onChange } = renderFilters({}, { ip: "" });
    fireEvent.change(field(container, "ip"), { target: { value: "10.0." } });
    fireEvent.keyDown(field(container, "ip"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ ip: "10.0." }));

    act(() => vi.advanceTimersByTime(DEBOUNCE));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("the action select calls onChange at once with its value", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "action"), { target: { value: "login" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ action: "login" }));
  });

  it("the sort select calls onChange at once with 1 for oldest first", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "oldest"), { target: { value: "1" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ oldest: "1" }));
  });

  it("the action and sort selects are found by their Mongolian labels", () => {
    const { container } = renderFilters();
    const action = screen.getByLabelText("Үйлдэл") as HTMLSelectElement;
    const oldest = screen.getByLabelText("Эрэмбэ") as HTMLSelectElement;
    expect(action.tagName).toBe("SELECT");
    expect(action.name).toBe("action");
    expect(oldest.tagName).toBe("SELECT");
    expect(oldest.name).toBe("oldest");
    expect(container.querySelector("#log-action")).toBe(action);
    expect(container.querySelector("#log-oldest")).toBe(oldest);
  });

  it("category menu sends repeated values", () => {
    // Settled, so the menu shows the echo: the echo must carry the same categories as the address.
    const { container, onChange } = renderFilters({ query: { ...NOTHING, categories: ["auth"] } }, { category: ["auth"] });
    const data = container.querySelector('input[type="checkbox"][value="data"]') as HTMLInputElement;
    fireEvent.click(data);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ category: ["auth", "data"] }));
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

  it("has no person chip and no system-only box", () => {
    const { container } = renderFilters();
    expect(container.querySelector('input[name="employee"]')).toBeNull();
    expect(container.querySelector('input[name="system"]')).toBeNull();
  });

  it("a change of address from outside shows in the text boxes", () => {
    const { container, rerender } = render(
      <Routed query={NOTHING} options={OPTIONS} params={{ ...NO_PICKS, q: "old" }} settled onChange={vi.fn()} />,
    );
    rerender(<Routed query={NOTHING} options={OPTIONS} params={{ ...NO_PICKS, q: "" }} settled onChange={vi.fn()} />);
    expect(field(container, "q").value).toBe("");
  });

  it("«Цэвэрлэх» links to the bare system log", () => {
    const { container } = renderFilters();
    const clear = Array.from(container.querySelectorAll("a")).find((a) => a.textContent === "Цэвэрлэх");
    expect(clear?.getAttribute("href")).toBe("/logs/system/");
  });
});
