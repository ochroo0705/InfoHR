import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import { suggestOrderNumber, type HireSectionOut } from "../../api/hire";
import { HireOrderBlock } from "./HireOrderBlock";

vi.mock("../../api/hire", () => ({
  suggestOrderNumber: vi.fn(),
}));

const suggestMock = vi.mocked(suggestOrderNumber);

// The project has no jest-dom matchers, so classes are checked on the element's classList.
const has = (el: Element | null, className: string) => el?.classList.contains(className) ?? false;

const NOTE = "дугаар заавал, огноо хоосон бол өөрчлөлтийн огноо";
const SECTION: HireSectionOut = {
  heading: "Тушаал",
  kind: "order",
  names: ["order-number", "order-date", "order-summary", "order-issued_by"],
  note: NOTE,
};

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
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderBlock(values: Record<string, string> = {}, errors: Record<string, string[]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <HireOrderBlock section={SECTION} fields={FIELDS} values={values} errors={errors} onChange={onChange} />,
  );
  const button = screen.getByRole("button", { name: "Санал болгох" }) as HTMLButtonElement;
  // The note is the muted span right after the number box's flex row.
  const note = utils.container.querySelector("span.flex + span") as HTMLElement;
  return { ...utils, onChange, button, note };
}

beforeEach(() => {
  suggestMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("HireOrderBlock", () => {
  it("shows the heading with the server's note verbatim", () => {
    const { container } = renderBlock();
    const heading = container.querySelector("h3") as HTMLElement;
    expect(heading.textContent).toBe("Тушаал · " + NOTE);
    expect(heading.querySelector("span")?.textContent).toBe("· " + NOTE);
  });

  it("stars the required boxes only", () => {
    renderBlock();
    expect(screen.getByText(/Тушаалын дугаар \*/));
    expect(screen.getByText("Тушаалын огноо"));
    expect(screen.queryByText("Тушаалын огноо *")).toBeNull();
  });

  it("a suggestion fills the number and an empty date", async () => {
    suggestMock.mockResolvedValue({ number: "А-12", date: "2026-11-18" });
    const { button, onChange } = renderBlock({ "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-12"));
    expect(onChange).toHaveBeenCalledWith("order-date", "2026-11-18");
  });

  it("a typed date is kept and sent to the server as the date argument", async () => {
    suggestMock.mockResolvedValue({ number: "А-13", date: "2026-03-01" });
    const { button, onChange } = renderBlock({ "order-date": "2026-03-01" });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-13"));
    expect(suggestMock).toHaveBeenCalledWith("2026-03-01");
    expect(onChange).not.toHaveBeenCalledWith("order-date", expect.anything());
  });

  it("asks the server with an empty date argument when the date box is empty", async () => {
    suggestMock.mockResolvedValue({ number: "А-14", date: "2026-11-18" });
    const { button } = renderBlock({ "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(suggestMock).toHaveBeenCalledTimes(1));
    expect(suggestMock).toHaveBeenCalledWith("");
  });

  it("an existing typed number is overwritten (parity with order_suggest.js)", async () => {
    suggestMock.mockResolvedValue({ number: "А-15", date: "2026-11-18" });
    const { button, onChange } = renderBlock({ "order-number": "Гараар-1", "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-15"));
  });

  it("an empty number in the answer shows the note and changes nothing", async () => {
    suggestMock.mockResolvedValue({ number: "", date: "2026-11-18" });
    const { button, onChange, note } = renderBlock({ "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(has(note, "hidden")).toBe(false));
    expect(note.textContent).toBe("Дугаарыг санал болгох боломжгүй, гараар оруулна уу.");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a failed request shows the note", async () => {
    suggestMock.mockRejectedValue(new Error("network"));
    const { button, onChange, note } = renderBlock({ "order-date": "" });

    fireEvent.click(button);

    await waitFor(() => expect(has(note, "hidden")).toBe(false));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a later good answer hides the note again", async () => {
    suggestMock.mockRejectedValueOnce(new Error("network"));
    suggestMock.mockResolvedValueOnce({ number: "А-16", date: "2026-11-18" });
    const { button, onChange, note } = renderBlock({ "order-date": "" });

    fireEvent.click(button);
    await waitFor(() => expect(has(note, "hidden")).toBe(false));

    fireEvent.click(button);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("order-number", "А-16"));
    expect(has(note, "hidden")).toBe(true);
  });

  it("the button is disabled during the request and enabled after", async () => {
    const pending = deferred<{ number: string; date: string }>();
    suggestMock.mockReturnValue(pending.promise);
    const { button } = renderBlock({ "order-date": "" });

    fireEvent.click(button);
    expect(button.disabled).toBe(true);

    pending.resolve({ number: "А-17", date: "2026-11-18" });
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("order errors render without the field-error class", () => {
    const { container } = renderBlock({}, { "order-summary": ["Агуулга хоосон байна"] });
    const message = screen.getByText("Агуулга хоосон байна");
    expect(has(message, "text-xs") && has(message, "text-red-600")).toBe(true);
    expect(has(message, "field-error")).toBe(false);
    expect(container.querySelector(".field-error")).toBeNull();
  });

  it("unmount during a pending suggestion does not update state or call onChange", async () => {
    const pending = deferred<{ number: string; date: string }>();
    suggestMock.mockReturnValue(pending.promise);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { button, onChange, unmount } = renderBlock({ "order-date": "" });

    fireEvent.click(button);
    unmount();
    pending.resolve({ number: "А-18", date: "2026-11-18" });
    await pending.promise;
    await Promise.resolve();

    expect(onChange).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("draws the form's non-field messages above the grid, and nothing extra without them", () => {
    const { container, rerender } = render(
      <HireOrderBlock section={SECTION} fields={FIELDS} values={{}} errors={{}} onChange={() => {}} formErrors={["Тушаал давхцаж байна"]} />,
    );
    const message = screen.getByText("Тушаал давхцаж байна");
    expect(message.tagName).toBe("P");
    expect(message.className).toBe("rounded bg-red-50 p-2 text-sm text-red-700");
    expect(message.nextElementSibling?.classList.contains("grid")).toBe(true);

    rerender(<HireOrderBlock section={SECTION} fields={FIELDS} values={{}} errors={{}} onChange={() => {}} />);
    expect(container.querySelectorAll("p").length).toBe(0);
  });

  it("the summary box spans two columns", () => {
    const { container } = renderBlock();
    const summaryLabel = container.querySelector("textarea[name='order-summary'], input[name='order-summary']")?.closest("label");
    expect(has(summaryLabel ?? null, "md:col-span-2")).toBe(true);
    const numberLabel = container.querySelector("input[name='order-number']")?.closest("label");
    expect(has(numberLabel ?? null, "md:col-span-2")).toBe(false);
  });
});
