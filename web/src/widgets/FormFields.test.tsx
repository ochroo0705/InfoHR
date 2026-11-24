import type { ReactNode, RefObject } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeFormFieldOut } from "../api/employeeWrites";
import { QuickAddProvider } from "../screens/lists/QuickAddHost";
import { FormFields, toPostValues, useFormValues, type FormValues } from "./FormFields";

// The quick-add tests need the signed-in user's perms and the lists API (the modal's form and save), stubbed as in
// Soft.test.tsx and QuickAddHost.test.tsx. The other tests here draw no add line (no provider, no add info).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), perms: [] as string[] }));

vi.mock("../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../shell/useMeta", () => ({
  useMeta: () => ({ data: { user: { perms: h.perms } } }),
}));

vi.mock("./confirm", () => ({ confirm: vi.fn() }));

type Field = EmployeeFormFieldOut;

function field(over: Partial<Field> & Pick<Field, "name" | "label" | "kind">): Field {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    max_length: null,
    placeholder: "—",
    required: false,
    value: "",
    ...over,
  };
}

// A form holding its values in state, as a caller does with useFormValues.
function Harness({
  fields,
  variant,
  errors = {},
  spy,
  idPrefix,
  formId,
  firstRef,
  resetKey,
}: {
  fields: Field[];
  variant: "boxed" | "soft";
  errors?: Record<string, string[]>;
  spy?: (name: string, value: string) => void;
  idPrefix?: string;
  formId?: string;
  firstRef?: RefObject<HTMLElement | null>;
  resetKey?: string;
}) {
  const { values, set } = useFormValues(fields, resetKey);
  return (
    <div>
      <FormFields
        fields={fields}
        values={values}
        errors={errors}
        variant={variant}
        idPrefix={idPrefix}
        formId={formId}
        firstFieldRef={firstRef}
        onChange={(name, value) => {
          spy?.(name, value);
          set(name, value);
        }}
      />
    </div>
  );
}

const SOFT_FIELDS: Field[] = [
  field({ name: "work_phone", label: "Ажлын утас", kind: "text", value: "7700-1234" }),
  field({
    name: "dept",
    label: "Хэлтэс",
    kind: "select",
    value: "1",
    choice: "Санхүү",
    choices: [
      { value: "", label: "" },
      { value: "1", label: "Санхүү" },
      { value: "2", label: "Худалдаа" },
    ],
  }),
  field({ name: "start_date", label: "Ажилд орсон", kind: "date", value: "2026-01-01" }),
];

const BOXED_FIELDS: Field[] = [
  field({ name: "name", label: "Нэр", kind: "text", value: "Бат", required: true, max_length: 40 }),
  field({ name: "amount", label: "Үндсэн цалин", kind: "money", value: "" }),
  field({ name: "reason", label: "Шалтгаан", kind: "textarea", required: true }),
  field({ name: "agree", label: "Зөвшөөрөх", kind: "checkbox", checked: false }),
  field({ name: "note", label: "Тайлбар", kind: "text", help: "Сонголтоор бөглөнө" }),
];

afterEach(() => {
  cleanup();
});

describe("FormFields soft variant", () => {
  it("draws a soft box per field with its name and the min-w-20 class", () => {
    const { container } = render(<Harness fields={SOFT_FIELDS} variant="soft" />);
    const phone = container.querySelector('input[name="work_phone"]') as HTMLInputElement;
    expect(phone.value).toBe("7700-1234");
    expect(phone.className).toContain("min-w-20");
    expect(container.querySelector('select[name="dept"]')).not.toBeNull();
    const date = container.querySelector('input[name="start_date"]') as HTMLInputElement;
    expect(date.className).toContain("min-w-20");
  });

  it("reports typed text, a picked option and a typed date through onChange", () => {
    const spy = vi.fn();
    const { container } = render(<Harness fields={SOFT_FIELDS} variant="soft" spy={spy} />);
    fireEvent.change(container.querySelector('input[name="work_phone"]') as HTMLInputElement, {
      target: { value: "7700-9999" },
    });
    expect(spy).toHaveBeenLastCalledWith("work_phone", "7700-9999");
    fireEvent.change(container.querySelector('select[name="dept"]') as HTMLSelectElement, { target: { value: "2" } });
    expect(spy).toHaveBeenLastCalledWith("dept", "2");
    fireEvent.change(container.querySelector('input[name="start_date"]') as HTMLInputElement, {
      target: { value: "2026-03-05" },
    });
    expect(spy).toHaveBeenLastCalledWith("start_date", "2026-03-05");
  });

  it("reports a checkbox as on or empty", () => {
    const spy = vi.fn();
    const fields = [field({ name: "agree", label: "Зөвшөөрөх", kind: "checkbox", checked: false })];
    const { container } = render(<Harness fields={fields} variant="soft" spy={spy} />);
    fireEvent.click(container.querySelector('input[name="agree"]') as HTMLInputElement);
    expect(spy).toHaveBeenLastCalledWith("agree", "on");
    // Query the box again after each change: Soft's changed mark can remount the input (report, concern 1).
    fireEvent.click(container.querySelector('input[name="agree"]') as HTMLInputElement);
    expect(spy).toHaveBeenLastCalledWith("agree", "");
  });

  it("puts the form id on each box as the form attribute", () => {
    const { container } = render(<Harness fields={SOFT_FIELDS} variant="soft" formId="inline-personal-form" />);
    const phone = container.querySelector('input[name="work_phone"]') as HTMLInputElement;
    expect(phone.getAttribute("form")).toBe("inline-personal-form");
  });

  it("keeps the same money box and its focus while typing digit by digit, and posts the plain value", () => {
    const spy = vi.fn();
    const fields = [field({ name: "amount", label: "Үндсэн цалин", kind: "money", value: "" })];
    const { container } = render(<Harness fields={fields} variant="soft" spy={spy} />);
    const input = container.querySelector('input[name="amount"]') as HTMLInputElement;
    input.focus();
    for (const digit of "2500000") {
      fireEvent.change(input, { target: { value: input.value + digit } });
    }
    // The wrapper stays the same, so the input is not remounted by the first keystroke.
    expect(container.querySelector('input[name="amount"]')).toBe(input);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("2,500,000");
    expect(spy).toHaveBeenLastCalledWith("amount", "2500000");
  });

  it("draws the errors under a soft box and marks it invalid", () => {
    const { container } = render(
      <Harness fields={SOFT_FIELDS} variant="soft" errors={{ work_phone: ["Утас буруу байна."] }} />,
    );
    expect(container.querySelector('input[name="work_phone"]')?.getAttribute("aria-invalid")).toBe("true");
    const message = container.querySelector("p.text-red-600") as HTMLElement;
    expect(message.className).toBe("mt-1 text-xs text-red-600");
    expect(message.textContent).toBe("Утас буруу байна.");
  });

  it("draws the errors under a soft money box", () => {
    const fields = [field({ name: "amount", label: "Үндсэн цалин", kind: "money", value: "" })];
    const { container } = render(<Harness fields={fields} variant="soft" errors={{ amount: ["Тоо буруу."] }} />);
    expect(container.querySelector('input[name="amount"]')?.getAttribute("aria-invalid")).toBe("true");
    expect(container.querySelector("p.text-red-600")?.textContent).toBe("Тоо буруу.");
  });
});

describe("FormFields boxed variant", () => {
  it("lays the fields out in the modal grid", () => {
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" />);
    const grid = container.querySelector("div.grid") as HTMLElement;
    expect(grid.className).toContain("gap-3");
    expect(grid.className).toContain("md:grid-cols-2");
    const label = container.querySelector('input[name="name"]')?.closest("label") as HTMLElement;
    expect(label.className).toContain("block text-sm");
    expect(label.className).not.toContain("md:col-span-2");
    const input = container.querySelector('input[name="name"]') as HTMLInputElement;
    expect(input.className).toContain("rounded-lg border border-slate-300");
    expect(input.getAttribute("maxlength")).toBe("40");
  });

  it("shows a required star and the required attribute", () => {
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" />);
    const label = container.querySelector('input[name="name"]')?.closest("label") as HTMLElement;
    expect(label.textContent).toBe("Нэр *");
    expect((container.querySelector('input[name="name"]') as HTMLInputElement).required).toBe(true);
    const note = container.querySelector('input[name="note"]')?.closest("label") as HTMLElement;
    expect(note.textContent).not.toContain("*");
  });

  it("spans the reason field over both columns and uses two rows for a textarea", () => {
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" />);
    const label = container.querySelector('textarea[name="reason"]')?.closest("label") as HTMLElement;
    expect(label.className).toContain("md:col-span-2");
    expect(container.querySelector('textarea[name="reason"]')?.getAttribute("rows")).toBe("2");
  });

  it("draws each error under its field", () => {
    const { container } = render(
      <Harness fields={BOXED_FIELDS} variant="boxed" errors={{ name: ["Заавал бөглөнө."] }} />,
    );
    const error = container.querySelector("span.text-red-600") as HTMLElement;
    expect(error.className).toBe("block text-xs text-red-600");
    expect(error.textContent).toBe("Заавал бөглөнө.");
    expect(container.querySelector('input[name="name"]')?.getAttribute("aria-invalid")).toBe("true");
  });

  it("draws the help text in grey under the control", () => {
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" />);
    const help = container.querySelector("span.text-slate-500") as HTMLElement;
    expect(help.className).toBe("block text-xs text-slate-500");
    expect(help.textContent).toBe("Сонголтоор бөглөнө");
  });

  it("posts a money value as the plain number, with the grouped text on screen", () => {
    const spy = vi.fn();
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" spy={spy} />);
    const amount = container.querySelector('input[name="amount"]') as HTMLInputElement;
    fireEvent.change(amount, { target: { value: "2,500,000" } });
    expect(spy).toHaveBeenLastCalledWith("amount", "2500000");
    expect(amount.value).toBe("2,500,000");
  });

  it("reports a checkbox as on or empty", () => {
    const spy = vi.fn();
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" spy={spy} />);
    const box = container.querySelector('input[name="agree"]') as HTMLInputElement;
    fireEvent.click(box);
    expect(spy).toHaveBeenLastCalledWith("agree", "on");
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(spy).toHaveBeenLastCalledWith("agree", "");
  });

  it("prefixes the control ids with idPrefix", () => {
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" idPrefix="inline-personal" />);
    expect(container.querySelector("#inline-personal-name")).not.toBeNull();
  });

  it("gives the first field's native control to firstFieldRef", () => {
    const ref: RefObject<HTMLElement | null> = { current: null };
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" firstRef={ref} />);
    expect(ref.current).toBe(container.querySelector('input[name="name"]'));
  });

  it("still points firstFieldRef at the first control after an edit", () => {
    const ref: RefObject<HTMLElement | null> = { current: null };
    const { container } = render(<Harness fields={BOXED_FIELDS} variant="boxed" firstRef={ref} />);
    fireEvent.change(container.querySelector('input[name="name"]') as HTMLInputElement, { target: { value: "Дорж" } });
    expect(ref.current).toBe(container.querySelector('input[name="name"]'));
    expect(ref.current).not.toBeNull();
  });

  it("reports a select pick, a date, a textarea and a number change", () => {
    const spy = vi.fn();
    const fields = [
      field({
        name: "dept",
        label: "Хэлтэс",
        kind: "select",
        value: "1",
        choice: "Санхүү",
        choices: [
          { value: "1", label: "Санхүү" },
          { value: "2", label: "Худалдаа" },
        ],
      }),
      field({ name: "start_date", label: "Ажилд орсон", kind: "date", value: "2026-01-01" }),
      field({ name: "reason", label: "Шалтгаан", kind: "textarea", value: "" }),
      field({ name: "qty", label: "Тоо", kind: "number", value: "1" }),
    ];
    const { container } = render(<Harness fields={fields} variant="boxed" spy={spy} />);
    fireEvent.change(container.querySelector('select[name="dept"]') as HTMLSelectElement, { target: { value: "2" } });
    expect(spy).toHaveBeenLastCalledWith("dept", "2");
    fireEvent.change(container.querySelector('input[name="start_date"]') as HTMLInputElement, {
      target: { value: "2026-03-05" },
    });
    expect(spy).toHaveBeenLastCalledWith("start_date", "2026-03-05");
    fireEvent.change(container.querySelector('textarea[name="reason"]') as HTMLTextAreaElement, {
      target: { value: "Гэрээ дууссан" },
    });
    expect(spy).toHaveBeenLastCalledWith("reason", "Гэрээ дууссан");
    fireEvent.change(container.querySelector('input[name="qty"]') as HTMLInputElement, { target: { value: "3" } });
    expect(spy).toHaveBeenLastCalledWith("qty", "3");
  });

  it("keeps typing through a refetch of the same form, and resets when the form key changes", () => {
    const refetched = BOXED_FIELDS.map((f) => (f.name === "name" ? { ...f, value: "Бат-Эрдэнэ" } : f));
    const { container, rerender } = render(<Harness fields={BOXED_FIELDS} variant="boxed" resetKey="personal/1" />);
    const nameBox = () => container.querySelector('input[name="name"]') as HTMLInputElement;
    fireEvent.change(nameBox(), { target: { value: "Дорж" } });
    rerender(<Harness fields={refetched} variant="boxed" resetKey="personal/1" />);
    expect(nameBox().value).toBe("Дорж");
    rerender(<Harness fields={refetched} variant="boxed" resetKey="personal/2" />);
    expect(nameBox().value).toBe("Бат-Эрдэнэ");
  });
});

describe("useFormValues", () => {
  const fields = [
    field({ name: "name", label: "Нэр", kind: "text", value: "Бат" }),
    field({ name: "agree", label: "Зөвшөөрөх", kind: "checkbox", checked: true }),
  ];

  it("starts from the fields' own values and is not dirty", () => {
    const { result } = renderHook(() => useFormValues(fields));
    expect(result.current.values).toEqual({ name: "Бат", agree: "on" });
    expect(result.current.dirty).toBe(false);
  });

  it("is dirty after a change, clean again after reset", () => {
    const { result } = renderHook(() => useFormValues(fields));
    act(() => result.current.set("name", "Дорж"));
    expect(result.current.values.name).toBe("Дорж");
    expect(result.current.dirty).toBe(true);
    act(() => result.current.reset());
    expect(result.current.values.name).toBe("Бат");
    expect(result.current.dirty).toBe(false);
  });

  it("is not dirty when a value is set back to its own", () => {
    const { result } = renderHook(() => useFormValues(fields));
    act(() => result.current.set("name", "Дорж"));
    act(() => result.current.set("name", "Бат"));
    expect(result.current.dirty).toBe(false);
  });

  it("ignores an edit to a name that is not in the fields", () => {
    const { result } = renderHook(() => useFormValues(fields));
    act(() => result.current.set("ghost", "x"));
    expect(result.current.dirty).toBe(false);
  });

  it("keeps edits when the fields are refetched under the same key", () => {
    const { result, rerender } = renderHook(
      ({ list, key }: { list: Field[]; key: string }) => useFormValues(list, key),
      { initialProps: { list: fields, key: "personal/1" } },
    );
    act(() => result.current.set("name", "Дорж"));
    rerender({ list: [...fields], key: "personal/1" });
    expect(result.current.values.name).toBe("Дорж");
    expect(result.current.dirty).toBe(true);
  });

  it("drops the edits when the key changes, and reset() drops them too", () => {
    const { result, rerender } = renderHook(
      ({ list, key }: { list: Field[]; key: string }) => useFormValues(list, key),
      { initialProps: { list: fields, key: "personal/1" } },
    );
    act(() => result.current.set("name", "Дорж"));
    rerender({ list: fields, key: "personal/2" });
    expect(result.current.values.name).toBe("Бат");
    expect(result.current.dirty).toBe(false);
    act(() => result.current.set("name", "Дорж"));
    act(() => result.current.reset());
    expect(result.current.values.name).toBe("Бат");
    expect(result.current.dirty).toBe(false);
  });
});

describe("toPostValues", () => {
  it("returns every field as a string: checkbox on or empty, money without commas", () => {
    const fields = [
      field({ name: "name", label: "Нэр", kind: "text", value: "Бат" }),
      field({ name: "agree", label: "Зөвшөөрөх", kind: "checkbox", checked: true }),
      field({ name: "amount", label: "Үндсэн цалин", kind: "money", value: "" }),
    ];
    const values: FormValues = { amount: "2,500,000", agree: "" };
    expect(toPostValues(fields, values)).toEqual({ name: "Бат", agree: "", amount: "2500000" });
  });

  it("falls back to the fields' own values for a name not in values", () => {
    const fields = [
      field({ name: "name", label: "Нэр", kind: "text", value: "Бат" }),
      field({ name: "agree", label: "Зөвшөөрөх", kind: "checkbox", checked: true }),
    ];
    expect(toPostValues(fields, {})).toEqual({ name: "Бат", agree: "on" });
  });
});

describe("FormFields: the quick-add line of a select", () => {
  const CITY_FORM = {
    title: "Салбар",
    can_delete: false,
    fields: [
      { name: "name", label: "Нэр", kind: "text", required: true, value: "", errors: [], choices: [], max_length: 100 },
    ],
  };
  const INDEX = { items: [{ slug: "district", label: "Сум, дүүрэг", count: 0, hits: 0 }] };
  const DEPT_CHOICES = [
    { value: "", label: "" },
    { value: "1", label: "Санхүү" },
    { value: "2", label: "Худалдаа" },
  ];

  function ok(data: unknown) {
    return { data, error: undefined, response: { ok: true, status: 200 } };
  }

  // A select field with an add info; the form holds its values, so a pick is reported through `spy` and kept.
  function addField(over: Partial<Field>): Field {
    return field({
      name: "dept",
      label: "Хэлтэс",
      kind: "select",
      value: "",
      combo: true,
      choices: DEPT_CHOICES,
      ...over,
    });
  }

  function renderWithProvider(ui: ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <QuickAddProvider>{ui}</QuickAddProvider>
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.perms = ["lists.manage_lists"];
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/lists") return ok(INDEX);
      if (path === "/api/v1/lists/{slug}/form") return ok(CITY_FORM);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("the soft box of an addable select shows the add line and a typed name is added through the quick URL", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ value: "99", label: "Шинэ" }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const spy = vi.fn();
    renderWithProvider(
      <Harness fields={[addField({ add: { slug: "branch", modal: false, parent: null } })]} variant="soft" spy={spy} />,
    );

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByText('+ "Шинэ" нэмэх'));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("dept", "99"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/lists/branch/quick",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Шинэ" }) }),
    );
    expect(box.value).toBe("Шинэ");
  });

  it("the boxed control of an addable select shows the add line and a typed name is added through the quick URL", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ value: "99", label: "Шинэ" }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const spy = vi.fn();
    renderWithProvider(
      <Harness fields={[addField({ add: { slug: "branch", modal: false, parent: null } })]} variant="boxed" spy={spy} />,
    );

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByText('+ "Шинэ" нэмэх'));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("dept", "99"));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/lists/branch/quick", expect.objectContaining({ method: "POST" }));
    expect(box.value).toBe("Шинэ");
  });

  it("without lists.manage_lists no add line shows", () => {
    h.perms = [];
    renderWithProvider(
      <Harness fields={[addField({ add: { slug: "branch", modal: false, parent: null } })]} variant="boxed" />,
    );

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    expect(screen.queryByText('+ "Шинэ" нэмэх')).toBeNull();
  });

  it("a select with no add info shows no add line", () => {
    renderWithProvider(<Harness fields={[addField({ add: null })]} variant="boxed" />);

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    expect(screen.queryByText('+ "Шинэ" нэмэх')).toBeNull();
  });

  it("a modal list in the boxed control opens the quick-add pop-up, and after save the new entry is picked and shown", async () => {
    h.post.mockResolvedValue(ok({ value: 42, label: "Баянзүрх", existed: false }));
    const spy = vi.fn();
    renderWithProvider(
      <Harness fields={[addField({ add: { slug: "district", modal: true, parent: null } })]} variant="boxed" spy={spy} />,
    );

    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Баянзүрх" } });
    fireEvent.click(screen.getByText('+ "Баянзүрх" нэмэх'));

    await screen.findByRole("button", { name: "Хадгалах" });
    expect(spy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("dept", "42"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull());
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("Баянзүрх");
  });
});
