import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { LeaveRequestDetailOut, LeaveRequestListOut, LeaveRequestRowOut } from "../../api/leaveRequests";
import { LeaveRequestsPage } from "./LeaveRequestsPage";

// The list and detail hooks are replaced by stubs, so the page's own logic runs against a known answer. The detail
// pop-up is the real one; only its data and its write hooks are stubs.
const h = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn() }));

vi.mock("../../api/leaveRequests", () => ({
  useLeaveRequests: (...args: unknown[]) => h.list(...args),
  useLeaveRequestDetail: (...args: unknown[]) => h.detail(...args),
  useApproveRequest: () => ({ mutateAsync: vi.fn() }),
  useRejectRequest: () => ({ mutateAsync: vi.fn() }),
}));

const DETAIL: LeaveRequestDetailOut = {
  id: 1,
  employee_name: "Бат Болд",
  job_line: "Санхүү · Нягтлан",
  leave_type: "Жилийн амралт",
  start: "2026-03-01",
  end: "2026-03-03",
  working_days: 3,
  created: "2026-02-27",
  waiting: true,
  current_step: 1,
  step_count: 2,
  rule: "Шууд удирдлага",
  override: false,
  balance_after: null,
  warnings: [],
  past: false,
  status_label: "Хүлээгдэж буй",
  reason: "",
  needs_reason: false,
  may: true,
  others: [],
  history: [],
};

const ROW: LeaveRequestRowOut = {
  id: 1,
  employee_name: "Бат Болд",
  leave_type: "Жилийн амралт",
  start: "2026-03-01",
  end: "2026-03-03",
  working_days: 3,
  waiting: true,
  current_step: 1,
  step_count: 2,
  rule: "Шууд удирдлага",
  status_label: "Хүлээгдэж буй",
  since: "2026-02-27",
};

const OTHER: LeaveRequestRowOut = {
  ...ROW,
  id: 2,
  employee_name: "Дорж Сарна",
  waiting: false,
  current_step: null,
  step_count: null,
  status_label: "Татгалзсан",
  since: null,
};

function pageOf(over: Partial<LeaveRequestListOut> = {}): LeaveRequestListOut {
  return {
    can_all: false,
    empty_text: "Хүсэлт олдсонгүй",
    next_offset: null,
    rows: [ROW, OTHER],
    status: "",
    statuses: [
      { value: "waiting", label: "Хүлээгдэж буй" },
      { value: "rejected", label: "Татгалзсан" },
    ],
    tab: "mine",
    ...over,
  };
}

// The shape of the infinite query the page reads.
function answer(over: Partial<LeaveRequestListOut> = {}, extra: Record<string, unknown> = {}) {
  return {
    data: { pages: [pageOf(over)] },
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    ...extra,
  };
}

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderPage(path = "/leave/requests/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/leave/requests/" element={<LeaveRequestsPage />} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return view;
}

// The params the page last sent to the hook.
function lastParams(): { tab?: string; status?: string } {
  const calls = h.list.mock.calls;
  return calls[calls.length - 1][0];
}

function select(container: HTMLElement, name: string): HTMLSelectElement {
  const el = container.querySelector<HTMLSelectElement>(`select[name="${name}"]`);
  if (!el) throw new Error(`no select[name=${name}]`);
  return el;
}

describe("LeaveRequestsPage", () => {
  beforeEach(() => {
    h.list.mockReset();
    h.list.mockReturnValue(answer());
    h.detail.mockReset();
    h.detail.mockReturnValue({ data: DETAIL, isError: false });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the title, the mine hint and the rows of the mine tab", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Чөлөөний хүсэлт" })).toBeTruthy();
    expect(screen.getByText("Таны батлах ээлжинд хүлээгдэж буй хүсэлтүүд. Мөрийг дарж шийдвэрлэнэ.")).toBeTruthy();
    expect(screen.getByText("Бат Болд")).toBeTruthy();
    expect(screen.getByText("Дорж Сарна")).toBeTruthy();
    expect(lastParams()).toEqual({ tab: "mine", status: "" });
  });

  it("the Бүгд tab is hidden without can_all", () => {
    renderPage();
    const tabs = screen.getByRole("navigation", { name: "Хүсэлтийн харагдац" });
    expect(tabs.textContent).toBe("Надад ирсэн");
  });

  it("the Бүгд tab is shown with can_all and links to tab=all", () => {
    h.list.mockReturnValue(answer({ can_all: true }));
    renderPage();
    const link = screen.getByRole("link", { name: "Бүгд" });
    expect(link.getAttribute("href")).toBe("/leave/requests/?tab=all");
  });

  it("a junk tab in the address shows the mine tab", () => {
    renderPage("/leave/requests/?tab=junk");
    expect(lastParams().tab).toBe("mine");
    expect(screen.getByText("Таны батлах ээлжинд хүлээгдэж буй хүсэлтүүд. Мөрийг дарж шийдвэрлэнэ.")).toBeTruthy();
  });

  it("the all tab shows the status select with «Бүх төлөв» first, not the mine hint", () => {
    h.list.mockReturnValue(answer({ can_all: true, tab: "all" }));
    const { container } = renderPage("/leave/requests/?tab=all");
    expect(lastParams()).toEqual({ tab: "all", status: "" });
    expect(screen.queryByText("Таны батлах ээлжинд хүлээгдэж буй хүсэлтүүд. Мөрийг дарж шийдвэрлэнэ.")).toBeNull();
    const options = Array.from(select(container, "status").options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "Бүх төлөв"],
      ["waiting", "Хүлээгдэж буй"],
      ["rejected", "Татгалзсан"],
    ]);
  });

  it("the status select is not shown on the mine tab", () => {
    const { container } = renderPage();
    expect(container.querySelector('select[name="status"]')).toBeNull();
  });

  it("a status change goes to the hook and the address (replaced)", () => {
    h.list.mockReturnValue(answer({ can_all: true, tab: "all" }));
    const { container } = renderPage("/leave/requests/?tab=all");
    fireEvent.change(select(container, "status"), { target: { value: "rejected" } });
    expect(lastParams()).toEqual({ tab: "all", status: "rejected" });
    expect(screen.getByTestId("loc").textContent).toBe("/leave/requests/?tab=all&status=rejected");
  });

  it("the empty text of the server shows when no row matches", () => {
    h.list.mockReturnValue(answer({ rows: [] }));
    renderPage();
    expect(screen.getByText("Хүсэлт олдсонгүй")).toBeTruthy();
  });

  it("a row click mounts the detail pop-up of that request, and Escape closes it", async () => {
    const { container } = renderPage();
    const row = screen.getByText("Бат Болд").closest("tr") as HTMLElement;
    fireEvent.click(row);

    expect(await screen.findByRole("heading", { name: "Бат Болд" })).toBeTruthy();
    expect(screen.getByText("Санхүү · Нягтлан")).toBeTruthy();
    expect(h.detail).toHaveBeenLastCalledWith(1);
    expect((container.firstElementChild as HTMLElement).getAttribute("data-modal")).toBe("detail:1");

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((container.firstElementChild as HTMLElement).getAttribute("data-modal")).toBeNull();
  });

  it("a refused list (403) shows the forbidden screen", () => {
    h.list.mockReturnValue(answer({}, { data: undefined, isError: true, error: { status: 403 } }));
    renderPage();
    expect(screen.getByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("a failed first load shows the load alert and no table", () => {
    h.list.mockReturnValue({
      data: undefined,
      isError: true,
      error: { status: 500 },
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
    });
    renderPage();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("the page title is set while the page is shown", () => {
    renderPage();
    expect(document.title).toBe("Чөлөөний хүсэлт · MACS Human Capital");
  });
});
