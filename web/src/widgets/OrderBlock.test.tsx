import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { OrderBlock } from "./OrderBlock";

afterEach(() => {
  cleanup();
});

const NOTE = "дугаар заавал, огноо хоосон бол өөрчлөлтийн огноо";

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

function renderBlock(props: { formErrors?: string[]; onChange?: (name: string, value: string) => void } = {}) {
  const onChange = props.onChange ?? vi.fn();
  const utils = render(
    <OrderBlock
      note={NOTE}
      formErrors={props.formErrors}
      fields={FIELDS}
      values={{}}
      errors={{}}
      onChange={onChange}
    />,
  );
  return { ...utils, onChange };
}

describe("OrderBlock", () => {
  it("shows the heading «Тушаал» with the note verbatim after the dot", () => {
    const { container } = renderBlock();
    const heading = container.querySelector("h3") as HTMLElement;
    expect(heading.textContent).toBe("Тушаал · " + NOTE);
    expect(heading.querySelector("span")?.className).toContain("text-slate-500");
  });

  it("draws the order messages in red above the boxes", () => {
    const { container } = renderBlock({ formErrors: ["Тушаалын дугаар заавал.", "Өөр мессеж."] });
    const messages = Array.from(container.querySelectorAll("p.bg-red-50"));
    expect(messages.map((p) => p.textContent)).toEqual(["Тушаалын дугаар заавал.", "Өөр мессеж."]);
    expect(messages[0].classList.contains("text-red-700")).toBe(true);
    const firstBox = container.querySelector("[name='order-number']") as HTMLElement;
    // The message comes before the first box in the document.
    expect(messages[0].compareDocumentPosition(firstBox) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("draws no message when there are no order messages", () => {
    const { container } = renderBlock({ formErrors: [] });
    expect(container.querySelectorAll("p.bg-red-50")).toHaveLength(0);
    const none = renderBlock();
    expect(none.container.querySelectorAll("p.bg-red-50")).toHaveLength(0);
  });

  it("draws the boxes through OrderFields, with the number box's suggest button and changes reported", () => {
    const { container, onChange } = renderBlock();
    expect(screen.getByRole("button", { name: "Санал болгох" })).not.toBeNull();
    const issuer = container.querySelector("[name='order-issued_by']") as HTMLInputElement;
    expect(issuer).not.toBeNull();
    fireEvent.change(issuer, { target: { value: "Захирал" } });
    expect(onChange).toHaveBeenCalledWith("order-issued_by", "Захирал");
  });
});
