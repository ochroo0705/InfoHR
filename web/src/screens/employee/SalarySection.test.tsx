import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEmployeeSalary } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { SalarySection } from "./SalarySection";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

vi.mock("../../api/employee", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/employee")>();
  return { ...actual, useEmployeeSalary: vi.fn() };
});

type EmployeeSalaryOut = components["schemas"]["EmployeeSalaryOut"];
type EmployeeBankFieldOut = components["schemas"]["EmployeeBankFieldOut"];
type Row = EmployeeSalaryOut["rows"][number];

// A text box as the API sends it: its raw value and the read-only text.
function text(label: string, value = "", shown = "—", aria = label): EmployeeBankFieldOut {
  return { label, aria_label: aria, kind: "text", value, choice: "", text: shown, checked: false };
}

// The bank block in template order, empty, as a user with no bank on file gets it.
function bankFields(overrides: Partial<Record<string, EmployeeBankFieldOut>> = {}): EmployeeBankFieldOut[] {
  const base: EmployeeBankFieldOut[] = [
    { label: "Банк", aria_label: "Банк", kind: "select", value: "", choice: "---------", text: "—", checked: false },
    text("Дансны дугаар"),
    text("НДД", "", "—", "НДД-ийн дугаар"),
    text("ЭМДД", "", "—", "ЭМДД-ийн дугаар"),
    {
      label: "Даатгуулагчийн төрөл",
      aria_label: "Даатгуулагчийн төрөл",
      kind: "select",
      value: "",
      choice: "---------",
      text: "—",
      checked: false,
    },
    text("ТТД", "", "—", "Татвар төлөгчийн дугаар"),
    {
      label: "Хөгжлийн бэрхшээл",
      aria_label: "Хөгжлийн бэрхшээлтэй",
      kind: "checkbox",
      value: "",
      choice: "",
      text: "Үгүй",
      checked: false,
    },
  ];
  return base.map((field) => overrides[field.label] ?? field);
}

// A salary payload as the API sends it: today's pay, the history rows and the bank block.
function salary(overrides: Partial<EmployeeSalaryOut> = {}): EmployeeSalaryOut {
  return {
    current: "2,500,000₮",
    missing_label: "",
    rows: [],
    has_rows: false,
    can_set: false,
    set_label: "",
    editable: false,
    bank_fields: bankFields(),
    ...overrides,
  } as EmployeeSalaryOut;
}

// One history row as the API sends it.
function row(overrides: Partial<Row> = {}): Row {
  return {
    pk: 1,
    event_id: null,
    period_text: "2026-01-05 – одоо",
    amount: "2,500,000₮",
    label: "Анхны цалин",
    scheduled: false,
    scheduled_label: "",
    cancellable: false,
    correctable: true,
    action_label: "Засвар",
    action_class: "text-violet-700 hover:underline",
    ...overrides,
  };
}

function mockSalary(data: EmployeeSalaryOut | undefined, error: unknown = null) {
  vi.mocked(useEmployeeSalary).mockReturnValue({ data, error } as unknown as ReturnType<typeof useEmployeeSalary>);
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
});

describe("SalarySection", () => {
  it("draws nothing before the salary data arrives", () => {
    mockSalary(undefined);
    const { container } = render(<SalarySection pk={7} />);
    expect(container.textContent).toBe("");
  });

  it("shows the failed-request line when the salary request fails", () => {
    mockSalary(undefined, new Error("boom"));
    render(<SalarySection pk={7} />);
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
  });

  it("draws the pay heading, the current pay and the bank heading in the template's order", () => {
    mockSalary(salary());
    const { container } = render(<SalarySection pk={7} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent);
    expect(headings).toEqual(["Үндсэн цалин", "Банк, даатгал"]);
    expect(screen.getByText("Одоогийн").nextElementSibling?.textContent).toBe("2,500,000₮");
    expect(screen.getByText("2,500,000₮").className).toBe("text-2xl font-semibold");
  });

  it("current: null shows «тогтоогоогүй» beside the heading and no current pay", () => {
    mockSalary(salary({ current: null, missing_label: "тогтоогоогүй" }));
    const { container } = render(<SalarySection pk={7} />);
    expect(screen.getByText("тогтоогоогүй").className).toBe("ml-1 text-sm font-normal text-slate-400");
    expect(container.querySelector("h3")?.textContent).toBe("Үндсэн цалин тогтоогоогүй");
    expect(screen.queryByText("Одоогийн")).toBeNull();
  });

  it("a set pay shows no «тогтоогоогүй» note", () => {
    mockSalary(salary());
    render(<SalarySection pk={7} />);
    expect(screen.queryByText("тогтоогоогүй")).toBeNull();
  });

  it("the history table has its four columns, and no table without rows", () => {
    mockSalary(salary());
    const { container } = render(<SalarySection pk={7} />);
    expect(container.querySelector(".ptable")).toBeNull();
    cleanup();
    mockSalary(salary({ rows: [row()], has_rows: true }));
    const { container: withRows } = render(<SalarySection pk={7} />);
    const heads = Array.from(withRows.querySelectorAll("th")).map((th) => th.textContent);
    expect(heads).toEqual(["Хугацаа", "Цалин", "Төрөл", ""]);
  });

  it("a scheduled row has the «Төлөвлөсөн» badge, a closed row none", () => {
    mockSalary(
      salary({
        rows: [
          row({ pk: 1, period_text: "2030-01-01 –", scheduled: true, scheduled_label: "Төлөвлөсөн", label: "Өсөлт" }),
          row({ pk: 2, period_text: "2026-01-05 – 2029-12-31", label: "Анхны цалин", action_label: "", action_class: "" }),
        ],
        has_rows: true,
      }),
    );
    render(<SalarySection pk={7} />);
    const badge = screen.getByText("Төлөвлөсөн");
    expect(badge.className).toBe("rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800");
    expect(badge.closest("tr")?.textContent).toContain("Өсөлт");
    expect(screen.getAllByText("Төлөвлөсөн")).toHaveLength(1);
  });

  it("a period text is drawn as the API gives it", () => {
    mockSalary(
      salary({
        rows: [
          row({ pk: 1, period_text: "2030-01-01 –", scheduled: true, scheduled_label: "Төлөвлөсөн" }),
          row({ pk: 2, period_text: "2026-01-05 – одоо" }),
        ],
        has_rows: true,
      }),
    );
    render(<SalarySection pk={7} />);
    expect(screen.getByText("2030-01-01 –")).toBeTruthy();
    expect(screen.getByText("2026-01-05 – одоо")).toBeTruthy();
  });

  it("«Цалин тогтоох» shows when the API sends set_label, and opens the legacy page", () => {
    mockSalary(salary({ can_set: true, set_label: "Цалин тогтоох" }));
    render(<SalarySection pk={7} />);
    const button = screen.getByRole("button", { name: "Цалин тогтоох" });
    expect(button.className).toBe("ml-auto rounded px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-50");
    fireEvent.click(button);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("no «Цалин тогтоох» without set_label", () => {
    mockSalary(salary({ rows: [row()], has_rows: true }));
    render(<SalarySection pk={7} />);
    expect(screen.queryByRole("button", { name: "Цалин тогтоох" })).toBeNull();
  });

  it("a row's action button takes its label and class from the API and opens the legacy page", () => {
    mockSalary(
      salary({
        rows: [
          row({
            pk: 1,
            period_text: "2030-01-01 –",
            scheduled: true,
            scheduled_label: "Төлөвлөсөн",
            cancellable: true,
            correctable: false,
            action_label: "Цуцлах",
            action_class: "rounded px-2 py-1 text-red-600 hover:bg-red-50",
          }),
        ],
        has_rows: true,
      }),
    );
    render(<SalarySection pk={7} />);
    const cancel = screen.getByRole("button", { name: "Цуцлах" });
    expect(cancel.className).toBe("rounded px-2 py-1 text-red-600 hover:bg-red-50");
    fireEvent.click(cancel);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("a row without an action label draws no button in its last cell", () => {
    mockSalary(salary({ rows: [row({ action_label: "", action_class: "", correctable: false })], has_rows: true }));
    const { container } = render(<SalarySection pk={7} />);
    const lastCell = container.querySelector("tbody tr td:last-child");
    expect(lastCell?.className).toBe("text-right whitespace-nowrap");
    expect(lastCell?.querySelector("button")).toBeNull();
  });

  it("read-only bank block: the printed text, «—» for empty, Тийм / Үгүй for the flag", () => {
    mockSalary(
      salary({
        editable: false,
        bank_fields: bankFields({
          "Дансны дугаар": text("Дансны дугаар", "5001234567", "5001234567"),
          "Хөгжлийн бэрхшээл": { label: "Хөгжлийн бэрхшээл", aria_label: "Хөгжлийн бэрхшээлтэй", kind: "checkbox", value: "", choice: "", text: "Тийм", checked: true },
        }),
      }),
    );
    const { container } = render(<SalarySection pk={7} />);
    expect(container.querySelectorAll("input, select")).toHaveLength(0);
    expect(screen.getByText("Дансны дугаар").nextElementSibling?.textContent).toBe("5001234567");
    expect(screen.getByText("Банк").nextElementSibling?.textContent).toBe("—");
    expect(screen.getByText("Хөгжлийн бэрхшээл").nextElementSibling?.textContent).toBe("Тийм");
  });

  it("editable bank block: selects with their option only, text boxes with the placeholder, a read-only checkbox", () => {
    mockSalary(
      salary({
        editable: true,
        bank_fields: bankFields({
          Банк: { label: "Банк", aria_label: "Банк", kind: "select", value: "4", choice: "Хаан банк", text: "Хаан банк", checked: false },
          "Дансны дугаар": text("Дансны дугаар", "5001234567"),
          "Хөгжлийн бэрхшээл": { label: "Хөгжлийн бэрхшээл", aria_label: "Хөгжлийн бэрхшээлтэй", kind: "checkbox", value: "", choice: "", text: "Тийм", checked: true },
        }),
      }),
    );
    render(<SalarySection pk={7} />);
    expect(document.querySelectorAll("select")).toHaveLength(2); // bank and insured category
    const bank = screen.getByLabelText("Банк") as HTMLSelectElement;
    expect(bank.className).toContain("f-soft");
    expect(bank.options).toHaveLength(1);
    expect(bank.options[0].textContent).toBe("Хаан банк");
    expect(bank.value).toBe("4");
    expect(fireEvent.mouseDown(bank)).toBe(false);
    expect(fireEvent.keyDown(bank, { key: "ArrowDown" })).toBe(false);
    const account = screen.getByLabelText("Дансны дугаар") as HTMLInputElement;
    expect(account.type).toBe("text");
    expect(account.value).toBe("5001234567");
    expect(account.readOnly).toBe(true);
    const empty = screen.getByLabelText("НДД-ийн дугаар") as HTMLInputElement;
    expect(empty.value).toBe("");
    expect(empty.placeholder).toBe("—");
    const disability = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(disability.type).toBe("checkbox");
    expect(disability.checked).toBe(true);
    expect(disability.className).toBe("h-4 w-4 accent-violet-600");
  });
});
