import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { suggestOrderNumber } from "../api/hire";
import { OrderFields } from "./OrderFields";

vi.mock("../api/hire", () => ({
  suggestOrderNumber: vi.fn(),
}));

const suggestMock = vi.mocked(suggestOrderNumber);

function field(over: Partial<EmployeeFormFieldOut> & Pick<EmployeeFormFieldOut, "name" | "label" | "kind">): EmployeeFormFieldOut {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    max_length: null,
    placeholder: "",
    required: false,
    value: "",
    ...over,
  };
}

const FIELDS: EmployeeFormFieldOut[] = [
  field({ name: "order-number", label: "Тушаалын дугаар", kind: "text", required: true }),
  field({ name: "order-date", label: "Тушаалын огноо", kind: "date" }),
  field({ name: "order-summary", label: "Агуулга", kind: "text" }),
  field({ name: "order-issued_by", label: "Гаргасан", kind: "text" }),
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderBoxes(values: Record<string, string> = {}, errors: Record<string, string[]> = {}) {
  const onChange = vi.fn();
  const utils = render(<OrderFields fields={FIELDS} values={values} errors={errors} onChange={onChange} />);
  const button = screen.getByRole("button", { name: "Санал болгох" }) as HTMLButtonElement;
  return { ...utils, onChange, button };
}

beforeEach(() => {
  suggestMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("OrderFields", () => {
  it("suggest fills the number and an empty date", async () => {
    suggestMock.mockResolvedValue({ number: "А-12", date: "2026-11-18" });
    const { button, onChange } = renderBoxes({ "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-12"));
    expect(onChange).toHaveBeenCalledWith("order-date", "2026-11-18");
  });

  it("suggest keeps a typed date and does not change it", async () => {
    suggestMock.mockResolvedValue({ number: "А-13", date: "2026-03-01" });
    const { button, onChange } = renderBoxes({ "order-date": "2026-03-01" });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-13"));
    expect(onChange).not.toHaveBeenCalledWith("order-date", expect.anything());
  });

  it("asks with no date argument (no ?date=) when the date box is empty, and with the typed date otherwise", async () => {
    suggestMock.mockResolvedValue({ number: "А-14", date: "2026-11-18" });
    const empty = renderBoxes({ "order-date": "" });
    fireEvent.click(empty.button);
    await waitFor(() => expect(suggestMock).toHaveBeenCalledTimes(1));
    expect(suggestMock).toHaveBeenLastCalledWith("");
    empty.unmount();

    const typed = renderBoxes({ "order-date": "2026-03-01" });
    fireEvent.click(typed.button);
    await waitFor(() => expect(suggestMock).toHaveBeenCalledTimes(2));
    expect(suggestMock).toHaveBeenLastCalledWith("2026-03-01");
  });

  it("draws an error under the box it belongs to and nowhere else", () => {
    const { container } = renderBoxes({}, { "order-summary": ["Агуулга хоосон байна"] });

    const message = screen.getByText("Агуулга хоосон байна");
    const box = message.closest("label");
    expect(box?.querySelector("[name='order-summary']")).not.toBeNull();
    expect(box?.querySelector("[name='order-number']")).toBeNull();
    expect(container.querySelectorAll("label span.text-red-600").length).toBe(1);
  });

  it("puts the required star on the number box when the field says required", () => {
    const { container } = renderBoxes();

    const numberLabel = container.querySelector("input[name='order-number']")?.closest("label");
    expect(numberLabel?.textContent?.startsWith("Тушаалын дугаар *")).toBe(true);
    const dateLabel = container.querySelector("input[name='order-date']")?.closest("label");
    expect(dateLabel?.textContent?.includes("*")).toBe(false);
  });

  it("unmount during a pending suggestion does not update state or call onChange", async () => {
    const pending = deferred<{ number: string; date: string }>();
    suggestMock.mockReturnValue(pending.promise);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { button, onChange, unmount } = renderBoxes({ "order-date": "" });

    fireEvent.click(button);
    unmount();
    pending.resolve({ number: "А-18", date: "2026-11-18" });
    await pending.promise;
    await Promise.resolve();

    expect(onChange).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
