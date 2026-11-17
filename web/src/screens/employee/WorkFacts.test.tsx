import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeWorkOut, WorkFieldOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { WorkFacts } from "./WorkFacts";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// Soft fields as the API sends them: a select with its current option, a date or a number box, and the read-only text.
// `aria` is the form field's accessible name (the API's aria_label), the name the tests query by.
// A plain select (a choice list): drawn as a native select. Its blank option has an empty label.
const select = (aria: string, value = "", choice = "", text = "—"): WorkFieldOut => ({
  kind: "select",
  value,
  choice,
  combo: false,
  text,
  aria_label: aria,
});
// A foreign key with a quick-add list: Django draws it as a combo text box showing the current option's text.
const fk = (aria: string, value = "", choice = "", text = "—"): WorkFieldOut => ({
  kind: "select",
  value,
  choice,
  combo: true,
  text,
  aria_label: aria,
});
const date = (aria: string, value = "", text = "—"): WorkFieldOut => ({
  kind: "date",
  value,
  choice: "",
  combo: false,
  text,
  aria_label: aria,
});
const number = (aria: string, value: string): WorkFieldOut => ({
  kind: "number",
  value,
  choice: "",
  combo: false,
  text: value,
  aria_label: aria,
});

// A work payload as the API sends it.
function work(overrides: Partial<EmployeeWorkOut> = {}): EmployeeWorkOut {
  return {
    can_manage: false,
    transfer_chip: false,
    contract_chip: false,
    position: "Мэргэжилтэн",
    department: "Хүний нөөц",
    manager: "—",
    second_position: fk("Албан тушаал (хавсарсан)"),
    office: fk("Алба"),
    section: fk("Хэсэг"),
    branch: fk("Салбар"),
    employee_type: "Үндсэн ажилтан",
    contract_type: "Тодорхой хугацаатай",
    contract_no: "Г-12",
    contract_start: "2026-01-05",
    contract_end: "2027-01-04",
    contract_end_label: "2027-01-04",
    probation_end: date("Туршилтын хугацаа дуусах"),
    first_hire_date: null,
    job_type: select("Ажлын төрөл", "NonSesional", "Тогтмол", "Тогтмол"),
    job_figure: select("Ажлын хэлбэр", "Main", "Үндсэн", "Үндсэн"),
    work_conditions: select("Ажлын нөхцөл", "1", "Хэвийн", "Хэвийн"),
    work_schedule: fk("Ажлын цагийн хуваарь"),
    sector_years: number("Салбарт ажилласан жил", "3"),
    macs_contract_no: "—",
    macs_contract_period: "— – ",
    macs_taken_leave: "—",
    macs_leave_type: "—",
    macs_probation_months: "—",
    macs_last_order_no: "—",
    macs_last_order_text: "—",
    ...overrides,
  } as EmployeeWorkOut;
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
});

// The field (dd) that sits next to a label (dt), found by its label.
function valueOf(label: string): HTMLElement {
  const dt = screen.getByText(label, { selector: "dt" });
  return dt.nextElementSibling as HTMLElement;
}

describe("WorkFacts", () => {
  it("draws the four headings in the template's order", () => {
    const { container } = render(<WorkFacts work={work()} pk={7} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent);
    expect(headings).toEqual(["Албан тушаал, байршил", "Гэрээ", "Ажлын нөхцөл, цаг", "Хуучин системээс (MACS)"]);
  });

  it("shows the job values as text, and the contract end label", () => {
    render(<WorkFacts work={work()} pk={7} />);
    expect(valueOf("Албан тушаал").textContent).toContain("Мэргэжилтэн");
    expect(valueOf("Гэрээ дуусах").textContent).toBe("2027-01-04");
    expect(screen.getByText("2027-01-04", { selector: "span" }).getAttribute("data-field")).toBe("contract_end");
  });

  it("the «өөрчлөлт» chips follow the transfer and contract flags, carry the template title and open the legacy page", () => {
    render(<WorkFacts work={work({ transfer_chip: true, contract_chip: true })} pk={7} />);
    const chips = screen.getAllByRole("button", { name: "өөрчлөх" });
    expect(chips).toHaveLength(4); // position, department, manager, contract
    expect(chips[0].getAttribute("title")).toBe("Өөрчлөлт бүртгэж солино (тушаалтай)");
    fireEvent.click(chips[0]);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("no chip is drawn when neither flag is set", () => {
    render(<WorkFacts work={work()} pk={7} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("without the manage right the fields are plain text: no soft box, no hire date", () => {
    const { container } = render(<WorkFacts work={work({ can_manage: false })} pk={7} />);
    expect(container.querySelectorAll("input, select")).toHaveLength(0);
    expect(screen.queryByText("Анх ажилд орсон огноо")).toBeNull();
    expect(valueOf("Ажлын нөхцөл").textContent).toBe("Хэвийн");
  });

  it("a foreign-key field is a combo text box showing its current option, as Django's select.js draws it", () => {
    const { container } = render(
      <WorkFacts work={work({ can_manage: true, office: fk("Алба", "4", "Удирдлагын алба") })} pk={7} />,
    );
    const office = screen.getByLabelText("Алба") as HTMLInputElement;
    expect(office.tagName).toBe("INPUT");
    expect(office.value).toBe("Удирдлагын алба");
    expect(office.getAttribute("role")).toBe("combobox");
    expect(office.className).toContain("sel-combo");
    // second, office, section, branch, schedule are combos; type, figure, conditions stay native selects.
    expect(container.querySelectorAll('input[role="combobox"]')).toHaveLength(5);
    expect(container.querySelectorAll("select")).toHaveLength(3);
  });

  it("a plain select draws only its current option, and its mousedown is stopped so it does not open", () => {
    render(
      <WorkFacts
        work={work({ can_manage: true, job_type: select("Ажлын төрөл", "NonSesional", "Тогтмол", "Тогтмол") })}
        pk={7}
      />,
    );
    const jobType = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(jobType.options).toHaveLength(1);
    expect(jobType.options[0].textContent).toBe("Тогтмол");
    expect(jobType.className).toContain("f-soft");
    expect(jobType.disabled).toBe(false);
    expect(fireEvent.mouseDown(jobType)).toBe(false);
    expect(fireEvent.keyDown(jobType, { key: "ArrowDown" })).toBe(false);
  });

  it("an empty foreign key is an empty text box, and an empty plain select keeps an empty option", () => {
    render(<WorkFacts work={work({ can_manage: true, job_type: select("Ажлын төрөл") })} pk={7} />);
    expect((screen.getByLabelText("Алба") as HTMLInputElement).value).toBe("");
    const jobType = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(jobType.value).toBe("");
    expect(jobType.options[0].textContent).toBe("");
  });

  it("date and number boxes are read-only inputs of their type, with the placeholder for an empty value", () => {
    render(
      <WorkFacts
        work={work({
          can_manage: true,
          first_hire_date: date("Анх ажилд орсон огноо", "2026-01-05"),
          probation_end: date("Туршилтын хугацаа дуусах", ""),
        })}
        pk={7}
      />,
    );
    const hire = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(hire.type).toBe("text"); // datepicker.js draws a text box in a dp-wrap (Django parity)
    expect(hire.parentElement?.className).toBe("dp-wrap");
    expect(hire.value).toBe("2026-01-05");
    expect(hire.readOnly).toBe(true);
    const probation = screen.getByLabelText("Туршилтын хугацаа дуусах") as HTMLInputElement;
    expect(probation.type).toBe("text");
    expect(probation.value).toBe("");
    expect(probation.placeholder).toBe("—");
    const years = screen.getByLabelText("Салбарт ажилласан жил") as HTMLInputElement;
    expect(years.type).toBe("number");
    expect(years.value).toBe("3");
    expect(years.className).toContain("w-20");
  });

  it("the hire-date box is drawn only when the API sends it", () => {
    render(<WorkFacts work={work({ can_manage: true, first_hire_date: null })} pk={7} />);
    expect(screen.queryByText("Анх ажилд орсон огноо")).toBeNull();
  });

  it("the MACS block shows the legacy values as sent", () => {
    render(<WorkFacts work={work({ macs_taken_leave: "Тийм", macs_last_order_text: "Ажилд авах" })} pk={7} />);
    expect(valueOf("Урт амралттай").textContent).toBe("Тийм");
    expect(valueOf("Сүүлийн тушаалын агуулга").textContent).toBe("Ажилд авах");
  });
});
