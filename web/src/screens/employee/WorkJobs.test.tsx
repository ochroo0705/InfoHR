import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeWorkOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { WorkJobs } from "./WorkJobs";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// The job and waiting rows call the pop-up openers from the provider. The test renders WorkJobs alone, so the hook returns stubs.
const popups = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
  openOrderDetail: vi.fn(),
}));
vi.mock("./EmployeePopups", () => ({ useEmployeePopups: () => popups }));

// fetch is stubbed before the api client is imported (the «Засвар» pop-up loads its form through it), as in RowModal.test.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

// The job correction form the pop-up gets back (only the title matters to these tests).
const JOB_FORM = {
  title: "Ажлын түүх засварлах",
  fields: [
    { name: "position", label: "Албан тушаал", required: false, kind: "text", value: "Ахлах мэргэжилтэн", checked: false, placeholder: "", choice: "", combo: false, choices: [], help: "", max_length: null, errors: [] },
    { name: "reason", label: "Шалтгаан", required: true, kind: "text", value: "", checked: false, placeholder: "", choice: "", combo: false, choices: [], help: "", max_length: null, errors: [] },
  ],
  hidden: {},
  empty_lists: [],
  can_delete: false,
};

// WorkJobs with a query client, for the «Засвар» pop-up (its form is a query).
function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

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
  event_id: null,
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
  event_id: 31,
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
  Object.values(popups).forEach((open) => open.mockClear());
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path.endsWith("/correct/form")) {
      return new Response(JSON.stringify(JOB_FORM), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
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

  it("a cancellable row shows «Цуцлах», and a click calls openEventCancel with the row's event id", () => {
    render(<WorkJobs work={work({ jobs: [cancellableJob] })} pk={7} />);
    const button = screen.getByRole("button", { name: "Цуцлах" });
    expect(button.className).toContain("text-red-600");
    fireEvent.click(button);
    expect(popups.openEventCancel).toHaveBeenCalledWith(31);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a job row with no event id (null) shows «Цуцлах», but a click calls no opener", () => {
    render(<WorkJobs work={work({ jobs: [{ ...cancellableJob, event_id: null }] })} pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(popups.openEventCancel).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
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

  it("a waiting row shows its chip and «Цуцлах» when cancellable, and calls openEventCancel with event_pk", () => {
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
    expect(popups.openEventCancel).toHaveBeenCalledWith(9);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
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

  it("clicking a job or waiting row with an order opens the detail; a row without one does nothing", () => {
    const waiting = {
      event_pk: 9,
      label: "Гэрээ сунгасан",
      effective: "2027-02-01",
      order_no: "№ 14 / 2027",
      order_pk: 14,
      chip: { label: "Гарын үсэг хүлээж байна", tone: "x" },
      cancellable: false,
      clickable: true,
      order_no_muted: false,
    };
    const { container } = render(<WorkJobs work={work({ waiting: [waiting], jobs: [scheduledJob] })} pk={7} />);
    const rows = container.querySelectorAll("tbody tr");
    fireEvent.click(rows[0] as HTMLElement);
    expect(popups.openOrderDetail).toHaveBeenLastCalledWith(14);
    fireEvent.click(rows[1] as HTMLElement);
    expect(popups.openOrderDetail).toHaveBeenLastCalledWith(40);
    expect(popups.openOrderDetail).toHaveBeenCalledTimes(2);

    popups.openOrderDetail.mockClear();
    const noOrder = { ...waiting, order_pk: null, clickable: false, order_no: "—", order_no_muted: true };
    const { container: bare } = render(<WorkJobs work={work({ waiting: [noOrder], jobs: [cancellableJob] })} pk={7} />);
    fireEvent.click(bare.querySelectorAll("tbody tr")[0] as HTMLElement);
    fireEvent.click(bare.querySelectorAll("tbody tr")[1] as HTMLElement);
    expect(popups.openOrderDetail).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("no openLegacyEmployee call remains in WorkJobs.tsx and WorkOrders.tsx", () => {
    const sources = import.meta.glob(["./WorkJobs.tsx", "./WorkOrders.tsx"], {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(sources)).toHaveLength(2);
    for (const source of Object.values(sources)) {
      expect(source).not.toContain("openLegacyEmployee");
    }
  });

  it("a «Цуцлах» button inside the page form does not submit it: the click only opens the cancel pop-up", () => {
    const submit = vi.fn();
    render(
      <form
        id="emp-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <WorkJobs work={work({ jobs: [cancellableJob] })} pk={7} />
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(popups.openEventCancel).toHaveBeenCalledWith(31);
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("WorkJobs: «Засвар» opens the job correction pop-up (Task 16a)", () => {
  // A correctable row of a job record (pk 2) with an order, so the row itself is also clickable.
  const correctable = { ...scheduledJob, pk: 2, scheduled: false, cancellable: false, correctable: true };

  it("«Засвар» opens the pop-up of that job record, and the row click does not open the legacy page", async () => {
    renderWithClient(<WorkJobs work={work({ jobs: [correctable] })} pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Засвар" }));
    await screen.findByRole("heading", { name: "Ажлын түүх засварлах" });
    const paths = fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url).pathname);
    expect(paths).toContain("/api/v1/employees/7/job/2/correct/form");
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a correctable row with no job record id shows no «Засвар» button (nothing to correct)", () => {
    renderWithClient(<WorkJobs work={work({ jobs: [{ ...correctable, pk: null, clickable: false }] })} pk={7} />);
    expect(screen.queryByRole("button", { name: "Засвар" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("«Цуцлах» opens the event cancel pop-up, not the legacy page and not the correction pop-up", () => {
    renderWithClient(<WorkJobs work={work({ jobs: [cancellableJob] })} pk={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));
    expect(popups.openEventCancel).toHaveBeenCalledWith(31);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
