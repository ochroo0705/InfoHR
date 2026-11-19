import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeWorkOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { WorkOrders } from "./WorkOrders";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn(), legacyOrigin: () => "http://legacy.test" };
});

// The own-order row, its «Файл хавсаргах» and «Түүх» call the pop-up openers from the provider. The test renders
// WorkOrders alone, so the hook returns stubs.
const popups = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
  openOrderDetail: vi.fn(),
}));
vi.mock("./EmployeePopups", () => ({ useEmployeePopups: () => popups }));

// A work payload as the API sends it. Only the fields this part reads matter; the rest is filled so the shape is complete.
function work(overrides: Partial<EmployeeWorkOut> = {}): EmployeeWorkOut {
  return {
    order_warning: "",
    orders: [],
    orders_count: 0,
    ...overrides,
  } as EmployeeWorkOut;
}

const SIGNED_CHIP = { label: "Гарын үсэг зурсан", tone: "seal" };
const REGISTERED_CHIP = { label: "Бүртгэгдсэн", tone: "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900" };

// One of our orders: a signed one with a scan (scan_url set) and a Word/PDF pair.
const ownOrder = {
  order_pk: 5,
  legacy: false,
  number: "№ 3 / 2026",
  number_muted: false,
  date: "2026-02-01",
  type_label: "Албан тушаал өөрчлөх",
  hire_note: "",
  summary: "Тест тушаал",
  cancel_prefix: "",
  cancel_number: "",
  cancel_suffix: "",
  cancelled_by_pk: null,
  cancels: [],
  chip: SIGNED_CHIP,
  cancelled: false,
  can_edit: false,
  can_upload: false,
  scan_url: "/employees/7/order/5/file/",
  word_url: "/employees/7/order/5/document/",
  pdf_url: "/employees/7/order/5/document/pdf/",
};

const macsRow = {
  order_pk: null,
  legacy: true,
  number: "№ 88",
  number_muted: false,
  date: "2020-01-01",
  type_label: "—",
  hire_note: "",
  summary: "MACS команд",
  cancel_prefix: "",
  cancel_number: "",
  cancel_suffix: "",
  cancelled_by_pk: null,
  cancels: [],
  chip: { label: "MACS", tone: "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700" },
  cancelled: false,
  can_edit: false,
  can_upload: false,
  scan_url: "",
  word_url: "",
  pdf_url: "",
};

function withOrders(rows: object[], extra: Partial<EmployeeWorkOut> = {}): EmployeeWorkOut {
  return work({ orders: rows as EmployeeWorkOut["orders"], orders_count: rows.length, ...extra });
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
  Object.values(popups).forEach((open) => open.mockClear());
});

afterEach(() => {
  cleanup();
});

describe("WorkOrders", () => {
  it("shows the one-shot order warning above the heading, and nothing without one", () => {
    const { container, rerender } = render(
      <WorkOrders work={work({ order_warning: "Тушаалын дугаар давхардсан." })} pk={7} />,
    );
    expect(screen.getByText("Тушаалын дугаар давхардсан.").className).toBe(
      "mt-8 rounded-lg bg-amber-50 p-3 text-sm text-amber-800",
    );
    rerender(<WorkOrders work={work()} pk={7} />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("renders no heading and no table when there are no orders", () => {
    const { container } = render(<WorkOrders work={work()} pk={7} />);
    expect(screen.queryByText("Бусад тушаал")).toBeNull();
    expect(container.querySelector("table")).toBeNull();
  });

  it("wraps the table frame in the scroll host, as scrollbars.js does for ptable-fit", () => {
    const { container } = render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    const frame = container.querySelector(".sbar-host .ptable-fit");
    expect(frame).not.toBeNull();
    expect(frame?.querySelector("table")).not.toBeNull();
  });

  it("shows the count next to the heading", () => {
    render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    const heading = screen.getByRole("heading", { name: /Бусад тушаал/ });
    expect(heading.className).toBe("sec-title mt-10 mb-3 flex items-baseline gap-2");
    expect(heading.querySelector("span")?.textContent).toBe("1");
  });

  it("shows the scan link as the API path when the row has a scan_url", () => {
    render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    const scan = screen.getByText("Файл харах").closest("a");
    expect(scan?.getAttribute("href")).toBe("/employees/7/order/5/file/");
    expect(scan?.getAttribute("target")).toBe("_blank");
  });

  it("hides the scan link when scan_url is empty (scan_ok is false)", () => {
    render(<WorkOrders work={withOrders([{ ...ownOrder, scan_url: "" }])} pk={7} />);
    expect(screen.queryByText("Файл харах")).toBeNull();
  });

  it("file, Word and PDF links are the API paths without legacyOrigin", () => {
    render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    expect(screen.getByText("Word татах").closest("a")?.getAttribute("href")).toBe("/employees/7/order/5/document/");
    expect(screen.getByText("PDF татах").closest("a")?.getAttribute("href")).toBe("/employees/7/order/5/document/pdf/");
    expect(screen.getByText("Файл харах").closest("a")?.getAttribute("href")).not.toContain("legacy.test");
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("omits the Word and PDF links when their URLs are empty", () => {
    render(<WorkOrders work={withOrders([{ ...ownOrder, word_url: "", pdf_url: "" }])} pk={7} />);
    expect(screen.queryByText("Word татах")).toBeNull();
    expect(screen.queryByText("PDF татах")).toBeNull();
  });

  it("shows the upload item only when can_upload, and it opens the upload pop-up with the order's pk", () => {
    render(<WorkOrders work={withOrders([{ ...ownOrder, can_upload: true }])} pk={7} />);
    fireEvent.click(screen.getByText("Файл хавсаргах"));
    expect(popups.openOrderUpload).toHaveBeenCalledWith(5);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("does not show the upload item without can_upload", () => {
    render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    expect(screen.queryByText("Файл хавсаргах")).toBeNull();
  });

  it("an upload item on a row with no order pk calls no opener", () => {
    render(<WorkOrders work={withOrders([{ ...ownOrder, order_pk: null, can_upload: true }])} pk={7} />);
    fireEvent.click(screen.getByText("Файл хавсаргах"));
    expect(popups.openOrderUpload).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("always shows the history item «Түүх», and it opens the history pop-up with the order's pk", () => {
    render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    fireEvent.click(screen.getByText("Түүх"));
    expect(popups.openOrderHistory).toHaveBeenCalledWith(5);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a history item on a row with no order pk calls no opener", () => {
    render(<WorkOrders work={withOrders([{ ...ownOrder, order_pk: null }])} pk={7} />);
    fireEvent.click(screen.getByText("Түүх"));
    expect(popups.openOrderHistory).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("gives an editable row its id, the hover classes and a click that opens the edit pop-up with the order's pk", () => {
    const { container } = render(<WorkOrders work={withOrders([{ ...ownOrder, can_edit: true }])} pk={7} />);
    const row = container.querySelector("#order-5");
    expect(row?.className).toBe("cursor-pointer hover:bg-violet-50");
    fireEvent.click(row as Element);
    expect(popups.openOrderEdit).toHaveBeenCalledWith(5);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("an editable row with no order pk calls no opener on click", () => {
    const { container } = render(<WorkOrders work={withOrders([{ ...ownOrder, order_pk: null, can_edit: true }])} pk={7} />);
    fireEvent.click(container.querySelector("tbody tr") as Element);
    expect(popups.openOrderEdit).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("does not open anything on a row that cannot be edited", () => {
    const { container } = render(<WorkOrders work={withOrders([ownOrder])} pk={7} />);
    fireEvent.click(container.querySelector("#order-5") as Element);
    expect(popups.openOrderEdit).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("strikes through a cancelled row and shows the cancel note with a link to the cancelling order", () => {
    const cancelled = {
      ...ownOrder,
      cancelled: true,
      cancel_prefix: "(цуцлах тушаал: ",
      cancel_number: "№ 9",
      cancel_suffix: ")",
      cancelled_by_pk: 12,
      chip: { label: "Цуцлагдсан", tone: "rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700" },
    };
    const { container } = render(<WorkOrders work={withOrders([cancelled])} pk={7} />);
    expect(container.querySelector("#order-5")?.className).toBe("text-slate-400 line-through");
    const note = screen.getByText("№ 9").closest("span");
    expect(note?.className).toBe("text-xs no-underline");
    expect(note?.textContent).toBe("(цуцлах тушаал: № 9)");
    const link = screen.getByText("№ 9").closest("a");
    expect(link?.className).toBe("text-violet-700 hover:underline");
    fireEvent.click(link as Element);
    expect(popups.openOrderDetail).toHaveBeenCalledWith(12);
    expect(popups.openOrderDetail).toHaveBeenCalledTimes(1);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("cancelled-by link opens that order's detail", () => {
    const cancelled = {
      ...ownOrder,
      cancelled: true,
      cancel_prefix: "(цуцлах тушаал: ",
      cancel_number: "№ 9",
      cancel_suffix: ")",
      cancelled_by_pk: 12,
    };
    render(<WorkOrders work={withOrders([cancelled])} pk={7} />);
    fireEvent.click(screen.getByText("№ 9"));
    expect(popups.openOrderDetail).toHaveBeenCalledWith(12);
    expect(popups.openOrderDetail).toHaveBeenCalledTimes(1);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("shows the cancelling number as plain text when the cancelling order is not one of ours", () => {
    const cancelled = {
      ...ownOrder,
      cancelled: true,
      cancel_prefix: "(цуцлах тушаал: ",
      cancel_number: "№ 9",
      cancel_suffix: ")",
      cancelled_by_pk: null,
    };
    render(<WorkOrders work={withOrders([cancelled])} pk={7} />);
    expect(screen.getByText("(цуцлах тушаал: № 9)")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "№ 9" })).toBeNull();
  });

  it("shows the grey span for a number-less order and the «(ажилд авсан)» note in its own span", () => {
    const hire = { ...ownOrder, number: "—", number_muted: true, hire_note: "(ажилд авсан)" };
    render(<WorkOrders work={withOrders([hire])} pk={7} />);
    expect(screen.getByText("—").className).toBe("text-slate-400");
    expect(screen.getByText("(ажилд авсан)").className).toBe("text-xs text-slate-500");
  });

  it("lists a cancelled order's cancellers with their «харах» links", () => {
    const withCancels = {
      ...ownOrder,
      cancels: [{ order_pk: 21, text_prefix: "(№ 4 тушаалыг цуцалсан: ", link_text: "харах", suffix: ")" }],
    };
    render(<WorkOrders work={withOrders([withCancels])} pk={7} />);
    const span = screen.getByText("харах").closest("span");
    expect(span?.textContent).toBe("(№ 4 тушаалыг цуцалсан: харах)");
    expect(span?.className).toBe("text-xs text-slate-500");
    fireEvent.click(screen.getByText("харах"));
    expect(popups.openOrderDetail).toHaveBeenCalledWith(21);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("renders a MACS command row read-only, with no menu and the muted type", () => {
    const { container } = render(<WorkOrders work={withOrders([macsRow])} pk={7} />);
    expect(screen.getByText("MACS команд")).toBeTruthy();
    expect(screen.getByText("—").className).toBe("text-slate-400");
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector("[id^=order-]")).toBeNull();
  });
});
