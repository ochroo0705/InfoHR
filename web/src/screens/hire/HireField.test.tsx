import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import { QuickAddProvider } from "../lists/QuickAddHost";
import { HireField, siblingName } from "./HireField";

// The quick-add pop-up needs the API client (the lists index and form) and the signed-in perms.
const h = vi.hoisted(() => ({ get: vi.fn(), perms: [] as string[] }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../../shell/useMeta", () => ({
  useMeta: () => ({ data: { user: { perms: h.perms } } }),
}));

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

describe("HireField quick add on a prefixed name", () => {
  beforeEach(() => {
    h.perms = ["lists.manage_lists"];
    h.get.mockReset();
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/lists") return { data: { items: [] }, error: undefined, response: { ok: true, status: 200 } };
      if (path === "/api/v1/lists/{slug}/form") {
        // The district pop-up's own form: a name box and the required city select.
        return {
          data: {
            title: "Сум, дүүрэг",
            can_delete: false,
            fields: [
              { name: "name", label: "Нэр", kind: "text", required: true, value: "", errors: [], choices: [], max_length: 100 },
              {
                name: "city",
                label: "Аймаг, хот",
                kind: "select",
                required: true,
                value: "",
                errors: [],
                max_length: null,
                choices: [
                  { value: "", label: "— сонгоогүй —" },
                  { value: "1", label: "Улаанбаатар" },
                  { value: "2", label: "Дархан" },
                ],
              },
            ],
          },
          error: undefined,
          response: { ok: true, status: 200 },
        };
      }
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
  });

  function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return (
      <QueryClientProvider client={client}>
        <QuickAddProvider>{children}</QuickAddProvider>
      </QueryClientProvider>
    );
  }

  it("siblingName keeps the field's prefix and uses the parent's own name without one", () => {
    expect(siblingName("addr-district", "city")).toBe("addr-city");
    expect(siblingName("photo", "city")).toBe("city");
    expect(siblingName("addr-district", null)).toBeUndefined();
  });

  it("a prefixed district field finds addr-city by its prefixed name and opens the pop-up with that city", async () => {
    // The page's own city box (the hire page's `addr-city`), set to Дархан; the server's unprefixed name is not on the page.
    const page = render(
      <>
        <select name="addr-city" defaultValue="2">
          <option value="">—</option>
          <option value="2">Дархан</option>
        </select>
        <HireField
          field={field({
            name: "addr-district",
            label: "Дүүрэг",
            kind: "select",
            combo: true,
            choices: [{ value: "5", label: "Сүхбаатар" }],
            add: { slug: "district", modal: true, parent: "city" },
          })}
          value=""
          onChange={() => {}}
        />
      </>,
      { wrapper },
    );

    // The page's own native select also has the combobox role, so the district's typing box is found by its class.
    const box = document.querySelector<HTMLInputElement>("input.sel-combo") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Баянзүрх" } });
    fireEvent.click(screen.getByText('+ "Баянзүрх" нэмэх'));

    await screen.findByRole("button", { name: "Хадгалах" });
    const cities = document.querySelectorAll<HTMLSelectElement>('[name="city"]');
    expect(cities[cities.length - 1].value).toBe("2");
    page.unmount();
  });

  it("the pop-up's city is blank when the page has no city box under that prefix", async () => {
    render(
      <HireField
        field={field({
          name: "addr-district",
          label: "Дүүрэг",
          kind: "select",
          combo: true,
          choices: [{ value: "5", label: "Сүхбаатар" }],
          add: { slug: "district", modal: true, parent: "city" },
        })}
        value=""
        onChange={() => {}}
      />,
      { wrapper },
    );

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Баянзүрх" } });
    fireEvent.click(screen.getByText('+ "Баянзүрх" нэмэх'));

    await waitFor(() => expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy());
    const cities = document.querySelectorAll<HTMLSelectElement>('[name="city"]');
    expect(cities[cities.length - 1].value).toBe("");
  });
});
