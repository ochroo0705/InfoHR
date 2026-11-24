import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EmployeeWorkOut, useEmployeeWork } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { WorkSection } from "./WorkSection";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn(), legacyOrigin: () => "http://legacy.test" };
});

vi.mock("../../api/employee", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/employee")>();
  return { ...actual, useEmployeeWork: vi.fn() };
});

// The job, order, salary and fact rows call the pop-up openers from the provider. The section is rendered alone, so the
// hook returns stubs.
const popups = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
  openOrderDetail: vi.fn(),
  openOrderCancel: vi.fn(),
  openOrderSign: vi.fn(),
}));
vi.mock("./EmployeePopups", () => ({ useEmployeePopups: () => popups }));

// A work payload with every field the Work tab reads, so each child renders from real data. Soft fields are plain text.
function field(text: string) {
  return { kind: "text", value: text, choice: "", text };
}

function leaveOut(overrides: Record<string, unknown> = {}) {
  return {
    visible: true,
    configured: true,
    start_missing: false,
    periods: [],
    old_count: 0,
    fold_old: false,
    fold_show_label: "",
    fold_hide_label: "",
    no_year_started: false,
    nowhere: [],
    old_absences: [],
    can_record: false,
    can_manage_settings: false,
    settings_url: "/leave/settings/",
    all_leaves_url: "/leave/?employee=7&status=all",
    ...overrides,
  };
}

function work(overrides: Record<string, unknown> = {}): EmployeeWorkOut {
  return {
    order_warning: "",
    can_manage: false,
    transfer_chip: false,
    contract_chip: false,
    position: "Нягтлан",
    department: "Санхүү",
    manager: "Бат",
    second_position: field("—"),
    office: field("—"),
    section: field("—"),
    branch: field("—"),
    employee_type: "Бүтэн цагийн",
    contract_type: "Хугацаагүй",
    contract_no: "",
    contract_start: "2026-01-05",
    contract_end: "",
    contract_end_label: "Хугацаагүй",
    probation_end: field("—"),
    first_hire_date: null,
    job_type: field("—"),
    job_figure: field("—"),
    work_conditions: field("—"),
    work_schedule: field("—"),
    sector_years: field("—"),
    macs_contract_no: "—",
    macs_contract_period: "—",
    macs_taken_leave: "—",
    macs_leave_type: "—",
    macs_probation_months: "—",
    macs_last_order_no: "—",
    macs_last_order_text: "—",
    waiting: [],
    jobs: [],
    orders_count: 0,
    orders: [],
    leave: leaveOut(),
    checklist_visible: false,
    checklists: [],
    ...overrides,
  } as unknown as EmployeeWorkOut;
}

const CURRENT_TONE =
  "inline-block min-w-10 rounded-full px-2 py-0.5 text-center font-semibold bg-emerald-100 text-emerald-800";

function period(overrides: Record<string, unknown> = {}) {
  return {
    period_text: "2026-01-05 – 2026-12-31",
    row_class: "group border-b border-slate-100 last:border-0 bg-amber-50/60",
    period_class: "font-semibold",
    badge: { label: "Одоо", tone: "ml-2 rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-900" },
    current: true,
    old: false,
    granted: "15",
    taken: "0",
    left: "15",
    left_tone: CURRENT_TONE,
    doubled_note: "",
    grants: [],
    leaves: [],
    ...overrides,
  };
}

function panel(overrides: Record<string, unknown> = {}) {
  return {
    kind: "onboarding",
    heading: "Ажилд орох жагсаалт",
    caption: "Ажилд орох · эхлэх огноо 2026-01-05",
    checklist: true,
    completed: false,
    progress: "1 / 2",
    today: "2026-11-17",
    can_start: false,
    can_cancel: false,
    rows: [],
    ...overrides,
  };
}

function task(overrides: Record<string, unknown> = {}) {
  return {
    title: "Гэрээ баталгаажуулах",
    required: true,
    owner_label: "HR",
    due_on: "2026-01-10",
    overdue: false,
    done: false,
    done_label: "",
    done_rest: "—",
    title_class: "",
    due_class: "whitespace-nowrap",
    can_tick: false,
    can_untick: false,
    ...overrides,
  };
}

function useWork(data: EmployeeWorkOut | undefined, error: unknown = null) {
  vi.mocked(useEmployeeWork).mockReturnValue({ data, error } as unknown as ReturnType<typeof useEmployeeWork>);
}

const SETUP = {
  complete: false,
  done: 1,
  total: 2,
  percent: 50,
  progress_text: "1 / 2 хийгдсэн",
  items: [],
} as unknown as NonNullable<Parameters<typeof WorkSection>[0]["setup"]>;

// SetupCard in the section calls a mutation hook, so every render needs a query client (a fresh one per test).
let client: QueryClient;
function wrap(ui: ReactNode) {
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}
function renderSection(ui: ReactNode) {
  return render(wrap(ui));
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WorkSection", () => {
  it("draws nothing before the Work data arrives", () => {
    useWork(undefined);
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    expect(container.textContent).toBe("");
  });

  it("shows the section error line when the request fails", () => {
    useWork(undefined, new Error("boom"));
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
  });

  it("renders the blocks in the template's order: setup, facts, jobs, orders, leave, checklists", () => {
    useWork(
      work({
        waiting: [
          {
            event_pk: 1,
            label: "Албан тушаал",
            effective: "2026-12-01",
            order_no: "",
            order_pk: null,
            chip: { label: "Гарын үсэг хүлээж", tone: "rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900" },
            cancellable: false,
            clickable: false,
            order_no_muted: true,
          },
        ],
        orders_count: 1,
        orders: [
          {
            order_pk: 5,
            legacy: false,
            number: "№ 3 / 2026",
            number_muted: false,
            date: "2026-02-01",
            type_label: "Албан тушаал өөрчлөх",
            hire_note: "",
            summary: "Тест",
            cancel_prefix: "",
            cancel_number: "",
            cancel_suffix: "",
            cancelled_by_pk: null,
            cancels: [],
            chip: { label: "Бүртгэгдсэн", tone: "x" },
            cancelled: false,
            can_edit: false,
            can_upload: false,
            scan_url: "",
            word_url: "",
            pdf_url: "",
          },
        ],
        leave: leaveOut({ periods: [period()] }),
        checklist_visible: true,
        checklists: [panel()],
      }),
    );
    const { container } = renderSection(<WorkSection pk={7} setup={SETUP} />);
    const headings = Array.from(container.querySelectorAll("h3")).map((h) => h.textContent ?? "");
    expect(headings).toEqual([
      "Албан тушаал, байршил",
      "Гэрээ",
      "Ажлын нөхцөл, цаг",
      "Хуучин системээс (MACS)",
      "Гарын үсэг хүлээж буй өөрчлөлт",
      "Ажлын түүх",
      "Бусад тушаал 1",
      "Ээлжийн амралт",
      "Ажилд орох жагсаалт",
    ]);
    const ordersHeading = headings.findIndex((h) => h.startsWith("Бусад тушаал"));
    expect(container.querySelectorAll("h3")[ordersHeading].querySelector("span")?.textContent).toBe("1");
    const setupCard = container.querySelector("#setup");
    const first = container.querySelector("h3");
    expect(setupCard && first && setupCard.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders no leave block when leave.visible is false", () => {
    useWork(work({ leave: leaveOut({ visible: false }) }));
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.queryByText("Ээлжийн амралт")).toBeNull();
  });

  it("shows the not-configured line, with the settings link only for a user who can manage it", () => {
    useWork(work({ leave: leaveOut({ configured: false, can_manage_settings: false }) }));
    const first = renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText(/Ээлжийн амралтын төрлийг сонгоогүй байна\./)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Төрөл тохируулах" })).toBeNull();
    first.unmount();
    useWork(work({ leave: leaveOut({ configured: false, can_manage_settings: true }) }));
    renderSection(<WorkSection pk={7} setup={null} />);
    const link = screen.getByRole("link", { name: "Төрөл тохируулах" });
    expect(link.getAttribute("href")).toBe("/leave/settings/");
  });

  it("folds the old years and the toggle opens and closes them", () => {
    const old = period({
      period_text: "2024-01-05 – 2024-12-31",
      old: true,
      current: false,
      badge: null,
      row_class: "group border-b border-slate-100 last:border-0",
      period_class: "font-medium",
    });
    useWork(
      work({
        leave: leaveOut({
          periods: [old, period()],
          old_count: 1,
          fold_old: true,
          fold_show_label: "Өмнөх 1 жил харах ▾",
          fold_hide_label: "Өмнөх жилүүдийг нуух ▴",
        }),
      }),
    );
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    const oldBody = container.querySelector("[data-old-year]") as HTMLElement;
    expect(oldBody.className).toContain("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Өмнөх 1 жил харах ▾" }));
    expect(oldBody.className).not.toContain("hidden");
    expect(screen.getByRole("button", { name: "Өмнөх жилүүдийг нуух ▴" })).toBeTruthy();
  });

  it("hides the checklist blocks when checklist_visible is false", () => {
    useWork(work({ checklist_visible: false, checklists: [panel()] }));
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    expect(container.querySelector("[data-checklist]")).toBeNull();
  });

  it("emphasises a done task; the tick posts to the API, not the Django page (posts are tested in ChecklistPanels.test)", () => {
    useWork(
      work({
        checklist_visible: true,
        checklists: [
          panel({
            rows: [
              task({
                done: true,
                done_label: "Хийгдсэн",
                done_rest: " · Бат Болд, 2026-01-09",
                title_class: "text-slate-500",
              }),
              task({ title: "Бичиг баримт", required: false, can_tick: true }),
            ],
          }),
        ],
      }),
    );
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(document.querySelector("span.text-emerald-700")?.textContent).toBe("Хийгдсэн");
    expect(screen.getByText("Заавал биш")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Хийгдсэн" }));
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("shows the start form for an offboarding panel that can start, and does not open the Django page on submit", () => {
    useWork(
      work({
        checklist_visible: true,
        checklists: [
          panel({
            kind: "offboarding",
            heading: "Ажлаас гарах жагсаалт",
            checklist: false,
            progress: "",
            caption: "",
            can_start: true,
            rows: [],
          }),
        ],
      }),
    );
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    const input = container.querySelector('input[name="anchor_day"]') as HTMLInputElement;
    expect(input.value).toBe("2026-11-17");
    fireEvent.click(screen.getByRole("button", { name: "Ажлаас гарах жагсаалт эхлүүлэх" }));
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("shows the badges: Одоо on the current year, Ирэх on the next one", () => {
    useWork(
      work({
        leave: leaveOut({
          periods: [
            period(),
            period({
              period_text: "2027-01-05 – 2027-12-31",
              current: false,
              upcoming: true,
              badge: { label: "Ирэх", tone: "ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600" },
              row_class: "group border-b border-slate-100 last:border-0",
              period_class: "font-medium",
            }),
          ],
        }),
      }),
    );
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Одоо").className).toContain("bg-amber-200");
    expect(screen.getByText("Ирэх").className).toContain("bg-slate-100");
  });

  it("shows the doubled-rights warning and the grants and leaves lines", () => {
    useWork(
      work({
        leave: leaveOut({
          periods: [
            period({
              doubled_note: "Энэ хугацаанд давхардсан эрх байна. Үлдэгдлийг бүртгэдэг системд засна уу.",
              grants: [{ label: "Ажилтны", days: "15 хоног", breakdown: "", comment: "", old_chip: false }],
              leaves: [{ label: "Авсан", text: "2026-03-01 – 2026-03-02, 2 өдөр", old_chip: true }],
            }),
          ],
        }),
      }),
    );
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText(/Энэ хугацаанд давхардсан эрх байна/)).toBeTruthy();
    expect(screen.getByText("15 хоног")).toBeTruthy();
    expect(screen.getByText("2026-03-01 – 2026-03-02, 2 өдөр")).toBeTruthy();
    expect(screen.getByText("Хуучин системээс")).toBeTruthy();
  });

  it("shows the start-missing line and no table when the start date is unknown", () => {
    useWork(work({ leave: leaveOut({ start_missing: true, configured: true }) }));
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Ажилд орсон огноо бүртгэлгүй тул ээлжийн амралтыг тооцох боломжгүй.")).toBeTruthy();
    expect(container.querySelector("[data-old-year]")).toBeNull();
    expect(screen.queryByText("Ажлын жил")).toBeNull();
  });

  it("shows the no-year line when the year has not started", () => {
    useWork(work({ leave: leaveOut({ no_year_started: true }) }));
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Ажлын жил эхлээгүй байна.")).toBeTruthy();
  });

  it("lists leave outside any period, with its old-system chip", () => {
    useWork(
      work({
        leave: leaveOut({
          nowhere: [{ label: "Авсан", text: "2026-02-01 – 2026-02-03, 3 өдөр", old_chip: true }],
        }),
      }),
    );
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Эрхийн хугацаагүй чөлөө")).toBeTruthy();
    expect(screen.getByText(/2026-02-01 – 2026-02-03, 3 өдөр/)).toBeTruthy();
    expect(screen.getByText("Хуучин системээс")).toBeTruthy();
  });

  it("lists the MACS absences as read-only, with their note", () => {
    useWork(
      work({
        leave: leaveOut({
          old_absences: [{ date: "2020-01-01 – 2020-01-05", name: "Өвчний чөлөө", note: "Тест" }],
        }),
      }),
    );
    const { container } = renderSection(<WorkSection pk={7} setup={null} />);
    expect(container.querySelector("[data-old-absences]")).not.toBeNull();
    expect(screen.getByText("Зөвхөн харах")).toBeTruthy();
    expect(screen.getByText("Өвчний чөлөө")).toBeTruthy();
    expect(screen.getByText(/· Тест/)).toBeTruthy();
  });

  it("gives «Чөлөө бүртгэх» to the Django page only when the user can record leave", () => {
    useWork(work({ leave: leaveOut({ can_record: true }) }));
    renderSection(<WorkSection pk={7} setup={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Чөлөө бүртгэх" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("links «Бүх чөлөө» to the leave list", () => {
    useWork(work());
    renderSection(<WorkSection pk={7} setup={null} />);
    const link = screen.getByRole("link", { name: "Бүх чөлөө (өвчний, цалингүй…)" });
    expect(link.getAttribute("href")).toBe("/leave/?employee=7&status=all");
  });

  it("shows «Цуцлах» on a cancellable checklist; the cancel posts to the API, not the Django page", () => {
    useWork(work({ checklist_visible: true, checklists: [panel({ can_cancel: true })] }));
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByRole("button", { name: "Цуцлах" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("adds the «Дууссан» note to the caption of a completed checklist", () => {
    useWork(work({ checklist_visible: true, checklists: [panel({ completed: true })] }));
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Дууссан").className).toContain("text-emerald-700");
  });

  it("colours an overdue due date red", () => {
    useWork(
      work({
        checklist_visible: true,
        checklists: [
          panel({
            rows: [task({ overdue: true, due_class: "whitespace-nowrap font-medium text-red-700" })],
          }),
        ],
      }),
    );
    renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("2026-01-10").className).toContain("text-red-700");
  });

  it("keeps the one-shot order warning when a refetch returns an empty warning", () => {
    useWork(work({ order_warning: "Тушаал анхааруулга" }));
    const { rerender } = renderSection(<WorkSection pk={7} setup={null} />);
    expect(screen.getByText("Тушаал анхааруулга")).toBeTruthy();
    useWork(work({ order_warning: "" }));
    rerender(wrap(<WorkSection pk={7} setup={null} />));
    expect(screen.getByText("Тушаал анхааруулга")).toBeTruthy();
  });
});
