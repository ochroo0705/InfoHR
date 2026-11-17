import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeWorkOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { WorkJobs } from "./WorkJobs";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// A work payload as the API sends it. Only the fields this part reads matter; the rest is filled so the shape is complete.
function work(overrides: Partial<EmployeeWorkOut> = {}): EmployeeWorkOut {
  return {
    waiting: [],
    jobs: [],
    ...overrides,
  } as EmployeeWorkOut;
}

// A history row without an order: no popup (clickable false), the grey dash (order_no_muted true).
const scheduledJob = {
  pk: 2,
  label: "Албан тушаал солигдсон",
  scheduled: true,
  is_cancelled: false,
  position: "Ахлах мэргэжилтэн",
  department: "Хүний нөөц",
  status: "Ажиллаж байгаа",
  order_no: "№ 12 / 2030",
  cancel_note: "",
  order_pk: 40,
  order_chip: null,
  period_text: "2030-01-01 –",
  period_note: "",
  cancellable: false,
  correctable: false,
  clickable: true,
  order_no_muted: false,
};

const cancellableJob = {
  ...scheduledJob,
  pk: 3,
  label: "Хэлтэс солигдсон",
  scheduled: false,
  order_pk: null,
  order_no: "—",
  period_text: "2026-01-05 – одоо",
  cancellable: true,
  clickable: false,
  order_no_muted: true,
};

const signedChip = { label: "Баталсан", tone: "seal" };
const registeredChip = { label: "Бүртгэсэн", tone: "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900" };
const defaultChip = { label: "Хүчингүй", tone: "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700" };

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
});

describe("WorkJobs", () => {
  it("a scheduled row shows the «Төлөвлөсөн» badge with the sky classes", () => {
    render(<WorkJobs work={work({ jobs: [scheduledJob] })} pk={7} />);
    const badge = screen.getByText("Төлөвлөсөн");
    expect(badge.className).toContain("bg-sky-100");
    expect(badge.className).toContain("text-sky-800");
    expect(badge.className).toContain("no-underline");
  });

  it("a cancellable row shows «Цуцлах», and a click calls openLegacyEmployee with the pk", () => {
    render(<WorkJobs work={work({ jobs: [cancellableJob] })} pk={7} />);
    const button = screen.getByRole("button", { name: "Цуцлах" });
    expect(button.className).toContain("text-red-600");
    fireEvent.click(button);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("a struck-through row never shows «Цуцлах», even when the flag is set", () => {
    const cancelled = {
      ...cancellableJob,
      is_cancelled: true,
      cancellable: true,
      correctable: false,
      position: "—",
      department: "—",
      status: "—",
    };
    render(<WorkJobs work={work({ jobs: [cancelled] })} pk={7} />);
    expect(screen.queryByRole("button", { name: "Цуцлах" })).toBeNull();
  });

  it("a correctable row shows «Засвар», not «Цуцлах»", () => {
    render(<WorkJobs work={work({ jobs: [{ ...cancellableJob, cancellable: false, correctable: true }] })} pk={7} />);
    expect(screen.queryByRole("button", { name: "Цуцлах" })).toBeNull();
    expect(screen.getByRole("button", { name: "Засвар" }).className).toContain("text-violet-700");
  });

  it("the period text is in the DOM, and the note sits in its own grey span", () => {
    const leave = { ...cancellableJob, cancellable: false, period_text: "2026-01-05 –", period_note: "(2026-08-01 буцна)" };
    const { container } = render(<WorkJobs work={work({ jobs: [leave] })} pk={7} />);
    const cell = container.querySelector("tbody tr td:nth-child(7)") as HTMLElement;
    expect(cell.textContent).toBe("2026-01-05 – (2026-08-01 буцна)");
    expect(screen.getByText("(2026-08-01 буцна)").className).toContain("text-slate-500");
    expect(screen.getByText("(2026-08-01 буцна)").tagName).toBe("SPAN");
  });

  it("the order chip takes the class string sent by the API: signed seal, registered, default", () => {
    const rows = [
      { ...scheduledJob, pk: 11, order_chip: signedChip },
      { ...scheduledJob, pk: 12, order_chip: registeredChip },
      { ...scheduledJob, pk: 13, order_chip: defaultChip },
    ];
    render(<WorkJobs work={work({ jobs: rows })} pk={7} />);
    expect(screen.getByText("Баталсан").className).toBe("seal");
    expect(screen.getByText("Бүртгэсэн").className).toContain("bg-sky-100");
    expect(screen.getByText("Хүчингүй").className).toContain("bg-slate-200");
  });

  it("a row with no order shows the grey dash and is not clickable", () => {
    const { container } = render(<WorkJobs work={work({ jobs: [cancellableJob] })} pk={7} />);
    expect(screen.getByText("—", { selector: "span.text-slate-400" })).toBeTruthy();
    const row = container.querySelector("tbody tr") as HTMLElement;
    expect(row.className).not.toContain("cursor-pointer");
    fireEvent.click(row);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a waiting row shows its chip and «Цуцлах» when cancellable", () => {
    const waiting = {
      event_pk: 9,
      label: "Гэрээ сунгасан",
      effective: "2027-02-01",
      order_no: "—",
      order_pk: null,
      chip: {
        label: "Гарын үсэг хүлээж байна",
        tone: "whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 no-underline",
      },
      cancellable: true,
      clickable: false,
      order_no_muted: true,
    };
    render(<WorkJobs work={work({ waiting: [waiting] })} pk={7} />);
    expect(screen.getByText("Гарын үсэг хүлээж буй өөрчлөлт")).toBeTruthy();
    expect(screen.getByText("Гарын үсэг хүлээж байна").className).toContain("bg-amber-50");
    expect(screen.getByText("2027-02-01")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("no waiting rows: the waiting heading and table are not drawn", () => {
    render(<WorkJobs work={work()} pk={7} />);
    expect(screen.queryByText("Гарын үсэг хүлээж буй өөрчлөлт")).toBeNull();
  });

  it("with no job rows the history table has its heading and header only", () => {
    const { container } = render(<WorkJobs work={work()} pk={7} />);
    expect(screen.getByText("Ажлын түүх")).toBeTruthy();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(0);
  });

  it("a cancelled row is struck through and shows its cancel note", () => {
    const cancelled = {
      ...scheduledJob,
      is_cancelled: true,
      scheduled: false,
      position: "—",
      department: "—",
      status: "—",
      order_no: "№ 5 / 2026",
      cancel_note: "(цуцалсан: № 6)",
      period_text: "2026-03-01",
      period_note: "",
      cancellable: false,
      correctable: false,
    };
    const { container } = render(<WorkJobs work={work({ jobs: [cancelled] })} pk={7} />);
    const row = container.querySelector("tbody tr") as HTMLElement;
    expect(row.className).toContain("line-through");
    expect(row.className).toContain("cursor-pointer");
    expect(screen.getByText("(цуцалсан: № 6)").className).toContain("text-xs");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("a clickable row opens the legacy page on click", () => {
    const { container } = render(<WorkJobs work={work({ jobs: [scheduledJob] })} pk={7} />);
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });
});
