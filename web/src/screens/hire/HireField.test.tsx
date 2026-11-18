import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import { HireField } from "./HireField";

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

afterEach(() => {
  cleanup();
});

describe("HireField", () => {
  it("shows the required star for a required field and not for an optional one", () => {
    const { container, rerender } = render(
      <HireField field={field({ name: "family_name", label: "Овог", kind: "text", required: true })} value="" onChange={() => {}} />,
    );
    const label = container.querySelector("label") as HTMLLabelElement;
    expect(label.className).toContain("block");
    expect(label.className).toContain("text-sm");
    expect(label.textContent).toBe("Овог *");

    rerender(
      <HireField field={field({ name: "middle_name", label: "Эцгийн нэр", kind: "text" })} value="" onChange={() => {}} />,
    );
    expect((container.querySelector("label") as HTMLLabelElement).textContent).toBe("Эцгийн нэр");
  });

  it("draws each error as a field-error span", () => {
    const { container } = render(
      <HireField
        field={field({ name: "family_name", label: "Овог", kind: "text", required: true })}
        value=""
        onChange={() => {}}
        errors={["Заавал бөглөнө."]}
      />,
    );
    const span = container.querySelector("span.field-error");
    expect(span).not.toBeNull();
    expect(span?.className).toContain("text-xs");
    expect(span?.className).toContain("text-red-600");
    expect(span?.textContent).toBe("Заавал бөглөнө.");
  });

  it("draws a checkbox as a flex label with the box and its text, errors inside", () => {
    const onChange = vi.fn();
    const { container } = render(
      <HireField
        field={field({ name: "is_active", label: "Идэвхтэй", kind: "checkbox", required: true })}
        value=""
        onChange={onChange}
        errors={["Алдаа"]}
      />,
    );
    const label = container.querySelector("label") as HTMLLabelElement;
    expect(label.className).toBe("flex items-center gap-2 text-sm");
    const box = label.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(box).not.toBeNull();
    expect(box.name).toBe("is_active");
    expect(label.textContent).toContain("Идэвхтэй");
    expect(label.textContent).not.toContain("*");
    expect(label.querySelector("span.field-error")?.textContent).toBe("Алдаа");

    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith("on");
  });

  it("draws a file field as a real file input with accept image/* and calls onFile", () => {
    const onFile = vi.fn();
    const onChange = vi.fn();
    const { container } = render(
      <HireField
        field={field({ name: "photo", label: "Зураг", kind: "file" })}
        value=""
        onChange={onChange}
        onFile={onFile}
      />,
    );
    const input = container.querySelector('input[name="photo"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.type).toBe("file");
    expect(input.getAttribute("accept")).toBe("image/*");
    expect(input.className).toContain("rounded-lg");

    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onFile).toHaveBeenCalledWith(file);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("sets controlRef to the file input for a file field", () => {
    const ref = { current: null as HTMLElement | null };
    const { container } = render(
      <HireField
        field={field({ name: "photo", label: "Зураг", kind: "file" })}
        value=""
        onChange={() => {}}
        controlRef={ref}
      />,
    );
    const input = container.querySelector('input[name="photo"]');
    expect(input).not.toBeNull();
    expect(ref.current).toBe(input);
  });

  it("shows the help text under the control", () => {
    render(
      <HireField
        field={field({ name: "first_hire_date", label: "Анх орсон огноо", kind: "date", help: "Байгууллагад анх орсон өдөр" })}
        value=""
        onChange={() => {}}
      />,
    );
    const help = screen.getByText("Байгууллагад анх орсон өдөр");
    expect(help.tagName).toBe("SPAN");
    expect(help.className).toContain("text-slate-500");
  });

  it("passes a text change to onChange with the typed value", () => {
    const onChange = vi.fn();
    const { container } = render(
      <HireField field={field({ name: "family_name", label: "Овог", kind: "text" })} value="" onChange={onChange} />,
    );
    const input = container.querySelector("input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Бат" } });
    expect(onChange).toHaveBeenCalledWith("Бат");
  });

  it("draws afterControl right after the control, inside the label", () => {
    const { container } = render(
      <HireField
        field={field({ name: "register_no", label: "Регистр", kind: "text" })}
        value=""
        onChange={() => {}}
        afterControl={<span id="extra">extra</span>}
      />,
    );
    const label = container.querySelector("label") as HTMLLabelElement;
    expect(label.querySelector("#extra")).not.toBeNull();
  });
});
