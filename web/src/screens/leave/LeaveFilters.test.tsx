import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaveListOut, LeaveListParams } from "../../api/leave";
import { LeaveFilters } from "./LeaveFilters";

const TYPES: LeaveListOut["types"] = [
  { value: 1, label: "Жилийн амралт" },
  { value: 2, label: "Өвчний чөлөө" },
];

const DEBOUNCE = 300;

function renderFilters(params: Partial<LeaveListParams> = {}) {
  const onChange = vi.fn();
  const view = render(
    <LeaveFilters
      params={{ q: "", status: "recorded", type: "", from: "", to: "", employee: "", ...params }}
      types={TYPES}
      onChange={onChange}
    />,
  );
  return { ...view, onChange };
}

function select(container: HTMLElement, name: string): HTMLSelectElement {
  const el = container.querySelector<HTMLSelectElement>(`select[name="${name}"]`);
  if (!el) throw new Error(`no select[name=${name}]`);
  return el;
}

function field(container: HTMLElement, name: string): HTMLInputElement {
  const el = container.querySelector(`[name="${name}"]`);
  if (!el) throw new Error(`no [name=${name}]`);
  return el as HTMLInputElement;
}

describe("LeaveFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the address values in the boxes", () => {
    const { container } = renderFilters({ q: "Бат", type: "2", status: "all", from: "2026-01-01", to: "2026-12-31" });
    expect(field(container, "q").value).toBe("Бат");
    expect(select(container, "type").value).toBe("2");
    expect(select(container, "status").value).toBe("all");
    expect((screen.getByLabelText("Эхлэх огноо") as HTMLInputElement).value).toBe("2026-01-01");
    expect((screen.getByLabelText("Дуусах огноо") as HTMLInputElement).value).toBe("2026-12-31");
  });

  it("the status select lists the five states in Mongolian", () => {
    const { container } = renderFilters();
    const options = Array.from(select(container, "status").options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["recorded", "Бүртгэсэн"],
      ["cancelled", "Цуцалсан"],
      ["mistake", "Буруу бүртгэсэн"],
      ["rejected", "Татгалзсан"],
      ["all", "Бүгд"],
    ]);
  });

  it("the type select starts with «Бүх төрөл» and lists the types", () => {
    const { container } = renderFilters();
    const options = Array.from(select(container, "type").options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "Бүх төрөл"],
      ["1", "Жилийн амралт"],
      ["2", "Өвчний чөлөө"],
    ]);
  });

  it("the search box waits 300 ms after the last keystroke, then sends the text", () => {
    const { container, onChange } = renderFilters({ status: "all" });
    fireEvent.change(field(container, "q"), { target: { value: "абв" } });
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(DEBOUNCE - 1));
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ q: "абв", status: "all", type: "", from: "", to: "" });
  });

  it("Enter in the search box sends it at once", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "q"), { target: { value: "Болд" } });
    fireEvent.keyDown(field(container, "q"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ q: "Болд" }));
  });

  it("the type select sends the picked type at once", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "type"), { target: { value: "2" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ type: "2", status: "recorded" }));
  });

  it("the status select sends the picked state at once", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(field(container, "status"), { target: { value: "cancelled" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
  });

  it("a whole date is sent at once; a half-typed date is kept in the box only", () => {
    const { onChange } = renderFilters();
    const from = screen.getByLabelText("Эхлэх огноо") as HTMLInputElement;

    fireEvent.change(from, { target: { value: "2026-0" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(from.value).toBe("2026-0");

    fireEvent.change(from, { target: { value: "2026-03-05" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ from: "2026-03-05" }));
  });

  it("another filter change sends only the committed dates, not a half-typed one in the box", () => {
    const { container, onChange } = renderFilters();
    fireEvent.change(screen.getByLabelText("Эхлэх огноо"), { target: { value: "2026-0" } });
    fireEvent.change(select(container, "type"), { target: { value: "2" } });
    expect(onChange).toHaveBeenCalledWith({ q: "", status: "recorded", type: "2", from: "", to: "" });
  });

  it("an emptied date box sends an empty date", () => {
    const { onChange } = renderFilters({ to: "2026-12-31" });
    fireEvent.change(screen.getByLabelText("Дуусах огноо"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ to: "" }));
  });

  it("any change drops the employee filter, as the Django form does", () => {
    const { container, onChange } = renderFilters({ employee: "7" });
    fireEvent.change(field(container, "status"), { target: { value: "all" } });
    const next = onChange.mock.calls[0][0] as LeaveListParams;
    expect(next).toEqual({ q: "", status: "all", type: "", from: "", to: "" });
    expect(next).not.toHaveProperty("employee");
  });
});
