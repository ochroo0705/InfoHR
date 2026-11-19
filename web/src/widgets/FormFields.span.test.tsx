import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { FormFields } from "./FormFields";

function field(name: string, label: string, value: string): EmployeeFormFieldOut {
  return {
    name,
    label,
    required: false,
    kind: "text",
    value,
    checked: false,
    placeholder: "",
    choice: "",
    combo: false,
    choices: [],
    help: "",
    max_length: null,
    errors: [],
  };
}

const FIELDS = [field("reason", "Шалтгаан", ""), field("note", "Тайлбар", "")];

afterEach(() => {
  cleanup();
});

describe("FormFields boxed: spanNames and errorInline", () => {
  it("by default only reason spans both columns", () => {
    const { container } = render(
      <FormFields variant="boxed" fields={FIELDS} values={{}} errors={{}} onChange={vi.fn()} />,
    );

    const labels = container.querySelectorAll("label");
    expect(labels[0].className).toContain("md:col-span-2");
    expect(labels[1].className).not.toContain("md:col-span-2");
  });

  it("spanNames draws the named boxes across both columns", () => {
    const { container } = render(
      <FormFields
        variant="boxed"
        fields={FIELDS}
        values={{}}
        errors={{}}
        onChange={vi.fn()}
        spanNames={["reason", "note"]}
      />,
    );

    const labels = container.querySelectorAll("label");
    expect(labels[0].className).toContain("md:col-span-2");
    expect(labels[1].className).toContain("md:col-span-2");
  });

  it("the default error span is a block span", () => {
    const { container } = render(
      <FormFields
        variant="boxed"
        fields={FIELDS}
        values={{}}
        errors={{ note: ["Тайлбар заавал."] }}
        onChange={vi.fn()}
      />,
    );

    const error = Array.from(container.querySelectorAll("span")).find((span) => span.textContent === "Тайлбар заавал.");
    expect(error?.className).toBe("block text-xs text-red-600");
  });

  it("errorInline draws the error as an inline span", () => {
    const { container } = render(
      <FormFields
        variant="boxed"
        fields={FIELDS}
        values={{}}
        errors={{ note: ["Тайлбар заавал."] }}
        onChange={vi.fn()}
        errorInline
      />,
    );

    const error = Array.from(container.querySelectorAll("span")).find((span) => span.textContent === "Тайлбар заавал.");
    expect(error?.className).toBe("text-xs text-red-600");
  });
});
