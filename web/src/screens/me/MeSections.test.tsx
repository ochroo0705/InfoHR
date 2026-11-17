import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTick, useWithdraw, type MeOut } from "../../api/me";
import { confirm } from "../../widgets/confirm";
import { Balance } from "./Balance";
import { Holidays } from "./Holidays";
import { MyRequests } from "./MyRequests";
import { MyTasks } from "./MyTasks";
import { Recorded } from "./Recorded";
import { TeamAway } from "./TeamAway";

vi.mock("../../api/me", () => ({
  useMe: vi.fn(),
  useDismissNotice: vi.fn(),
  useTick: vi.fn(),
  useWithdraw: vi.fn(),
}));

vi.mock("../../widgets/confirm", () => ({
  confirm: vi.fn(),
}));

// Every test starts from an empty document (globals are off, so testing-library does not clean up by itself).
afterEach(() => {
  cleanup();
});

type BalanceData = MeOut["balance"];
type Task = MeOut["tasks"][number];
type Request = MeOut["requests"][number];

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 5,
    title: "Компьютер тохируулах",
    employee: "Бат Дорж",
    kind_label: "Ажилд орох",
    due: "2026-11-20",
    overdue: false,
    can_tick: true,
    ...overrides,
  };
}

function makeRequest(overrides: Partial<Request> = {}): Request {
  return {
    id: 9,
    leave_type: "Ээлжийн амралт",
    start: "2026-12-01",
    end: "2026-12-05",
    working_days: 5,
    status: "waiting",
    status_label: "Хүлээгдэж буй · шат 1/2",
    tone: "waiting",
    step: "1/2",
    rule: "Шууд удирдлага",
    reason: "",
    can_withdraw: true,
    ...overrides,
  };
}

function makeBalance(overrides: Partial<BalanceData> = {}): BalanceData {
  return { start_missing: false, configured: true, started: true, periods: [], nowhere: 0, ...overrides };
}

function renderIn(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

// The mutations are replaced: each test decides what mutate does (succeed, or fail with form errors).
function mockWithdraw(mutate: ReturnType<typeof vi.fn>) {
  vi.mocked(useWithdraw).mockReturnValue({ mutate } as unknown as ReturnType<typeof useWithdraw>);
}

function mockTick(mutate: ReturnType<typeof vi.fn>) {
  vi.mocked(useTick).mockReturnValue({ mutate } as unknown as ReturnType<typeof useTick>);
}

function refusal(message: string): Error {
  return Object.assign(new Error("request failed"), { status: 409, formErrors: [message], fieldErrors: {} });
}

describe("TeamAway", () => {
  it("shows 8 entries and «+2» for 10 people away", () => {
    const teamAway = Array.from({ length: 10 }, (_, i) => ({
      full_name: `Ажилтан ${i + 1}`,
      start: "2026-11-20",
      end: "2026-11-22",
    }));
    const { container } = renderIn(<TeamAway hasTeam={true} teamAway={teamAway} />);
    expect(container.querySelector("[data-team-away]")).not.toBeNull();
    expect(container.querySelectorAll("[data-team-away] li")).toHaveLength(8);
    expect(screen.getByText("+2")).toBeTruthy();
  });

  it("shows the grey line when nobody is away", () => {
    renderIn(<TeamAway hasTeam={true} teamAway={[]} />);
    expect(screen.getByText("Ойрын 14 хоногт чөлөөтэй хүн алга.")).toBeTruthy();
  });

  it("renders nothing without a team", () => {
    const { container } = renderIn(<TeamAway hasTeam={false} teamAway={[]} />);
    expect(container.querySelector("[data-team-away]")).toBeNull();
  });
});

describe("Holidays", () => {
  it("shows at most 3 names then «+N»", () => {
    const holidays = [
      { day: "2026-01-01", name: "Шинэ жил" },
      { day: "2026-02-18", name: "Цагаан сар" },
      { day: "2026-03-08", name: "Эмэгтэйчүүдийн баяр" },
      { day: "2026-07-11", name: "Naadam" },
    ];
    const { container } = renderIn(<Holidays holidays={holidays} />);
    const line = container.querySelector("[data-holidays]");
    expect(line?.textContent).toBe(
      "Баяр ёслол: 2026-01-01 Шинэ жил · 2026-02-18 Цагаан сар · 2026-03-08 Эмэгтэйчүүдийн баяр +1",
    );
  });
});

describe("Balance", () => {
  it("shows the amber text and no list when the start date is missing", () => {
    const { container } = renderIn(<Balance balance={makeBalance({ start_missing: true })} />);
    const text = screen.getByText("Ажилд орсон огноо бүртгэлгүй тул ээлжийн амралтыг тооцох боломжгүй.");
    expect(text.classList.contains("text-amber-700")).toBe(true);
    expect(container.querySelector("ul")).toBeNull();
  });

  it("shows the grey text when no annual leave type is set up", () => {
    const { container } = renderIn(<Balance balance={makeBalance({ configured: false })} />);
    const text = screen.getByText("Ээлжийн амралтын төрөл тохируулаагүй байна.");
    expect(text.classList.contains("text-slate-500")).toBe(true);
    expect(container.querySelector("ul")).toBeNull();
  });

  it("gives the balance text red when the balance is negative", () => {
    const period = {
      start: "2026-01-01",
      end: "2026-12-31",
      current: true,
      granted: "12",
      taken: "14.5",
      left: "-2.5",
      negative: true,
    };
    renderIn(<Balance balance={makeBalance({ periods: [period] })} />);
    expect(screen.getByText("Одоо")).toBeTruthy();
    expect(screen.getByText("Үлдэгдэл -2.5 хоног").classList.contains("text-red-700")).toBe(true);
  });

  it("shows «Ажлын жил эхлээгүй байна.» when the leave year has not started", () => {
    renderIn(<Balance balance={makeBalance({ started: false, periods: [] })} />);
    expect(screen.getByText("Ажлын жил эхлээгүй байна.")).toBeTruthy();
  });

  it("shows no line when the year started but no period is current or upcoming", () => {
    const { container } = renderIn(<Balance balance={makeBalance({ started: true, periods: [] })} />);
    expect(screen.queryByText("Ажлын жил эхлээгүй байна.")).toBeNull();
    expect(container.querySelectorAll("ul li")).toHaveLength(0);
  });

  it("shows the nowhere line when counted leave is outside every period", () => {
    renderIn(<Balance balance={makeBalance({ nowhere: 2 })} />);
    expect(screen.getByText("Эрхийн хугацаагүй чөлөө: 2", { exact: false })).toBeTruthy();
  });
});

describe("MyTasks", () => {
  beforeEach(() => {
    mockTick(vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("links the heading to the checklist list", () => {
    renderIn(<MyTasks tasks={[makeTask()]} />);
    const link = screen.getByText("Миний даалгавар").closest("a");
    expect(link?.getAttribute("href")).toBe("/checklists/mine/");
  });

  it("shows «Хийгдсэн» only when can_tick is true", () => {
    renderIn(<MyTasks tasks={[makeTask({ can_tick: false })]} />);
    expect(screen.queryByText("Хийгдсэн")).toBeNull();
  });

  it("shows a 409 text as a red line under the list", () => {
    const mutate = vi.fn((_pk: number, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(refusal("Даалгавар аль хэдийн хаагдсан")),
    );
    mockTick(mutate);
    renderIn(<MyTasks tasks={[makeTask()]} />);
    fireEvent.click(screen.getByText("Хийгдсэн"));
    expect(mutate).toHaveBeenCalledWith(5, expect.anything());
    expect(screen.getByText("Даалгавар аль хэдийн хаагдсан").classList.contains("text-red-700")).toBe(true);
  });

  it("renders nothing without tasks", () => {
    renderIn(<MyTasks tasks={[]} />);
    expect(screen.queryByText("Миний даалгавар")).toBeNull();
  });

  it("sends one tick for a double click, since the button is disabled while pending", () => {
    let pending = false;
    const mutate = vi.fn(() => {
      pending = true;
    });
    vi.mocked(useTick).mockImplementation(() => ({ mutate, isPending: pending }) as unknown as ReturnType<typeof useTick>);
    const { rerender } = renderIn(<MyTasks tasks={[makeTask()]} />);
    fireEvent.click(screen.getByText("Хийгдсэн"));
    rerender(<MemoryRouter><MyTasks tasks={[makeTask()]} /></MemoryRouter>);
    const button = screen.getByText("Хийгдсэн") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("clears an earlier refusal line when a tick succeeds", () => {
    let attempt = 0;
    const mutate = vi.fn((_pk: number, opts?: { onError?: (e: unknown) => void; onSuccess?: () => void }) => {
      attempt += 1;
      if (attempt === 1) opts?.onError?.(refusal("Даалгавар хаагдсан"));
      else opts?.onSuccess?.();
    });
    mockTick(mutate);
    renderIn(<MyTasks tasks={[makeTask()]} />);
    fireEvent.click(screen.getByText("Хийгдсэн"));
    expect(screen.getByText("Даалгавар хаагдсан")).toBeTruthy();
    fireEvent.click(screen.getByText("Хийгдсэн"));
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Даалгавар хаагдсан")).toBeNull();
  });
});

describe("MyRequests", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    mockWithdraw(mutate);
    vi.mocked(confirm).mockReset();
  });

  it("disables «Буцаах» while the withdrawal is pending", () => {
    vi.mocked(useWithdraw).mockImplementation(
      () => ({ mutate, isPending: true }) as unknown as ReturnType<typeof useWithdraw>,
    );
    renderIn(<MyRequests requests={[makeRequest()]} />);
    expect((screen.getByText("Буцаах") as HTMLButtonElement).disabled).toBe(true);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not withdraw when the confirm is cancelled", async () => {
    vi.mocked(confirm).mockResolvedValue(false);
    renderIn(<MyRequests requests={[makeRequest()]} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Буцаах"));
    });
    expect(confirm).toHaveBeenCalledWith("Хүсэлтээ буцаах уу?");
    expect(mutate).not.toHaveBeenCalled();
  });

  it("puts a 409 text in #me-error when the withdrawal is refused", async () => {
    vi.mocked(confirm).mockResolvedValue(true);
    mutate.mockImplementation((_pk: number, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(refusal("Хүсэлтийг буцаах боломжгүй")),
    );
    const { container } = renderIn(<MyRequests requests={[makeRequest()]} />);
    fireEvent.click(screen.getByText("Буцаах"));
    await waitFor(() => expect(mutate).toHaveBeenCalledWith(9, expect.anything()));
    const error = container.querySelector("#me-error p");
    expect(error?.textContent).toBe("Хүсэлтийг буцаах боломжгүй");
    expect(error?.classList.contains("text-red-700")).toBe(true);
  });

  it("shows the badge colour from tone and the waiting rule", () => {
    renderIn(<MyRequests requests={[makeRequest()]} />);
    expect(screen.getByText("Хүлээгдэж буй · шат 1/2").classList.contains("bg-amber-100")).toBe(true);
    expect(screen.getByText("Батлах: Шууд удирдлага")).toBeTruthy();
  });

  it("shows the rejection reason", () => {
    renderIn(
      <MyRequests
        requests={[makeRequest({ status: "rejected", tone: "rejected", status_label: "Татгалзсан", rule: "", reason: "Ажлын ачаалал", can_withdraw: false })]}
      />,
    );
    expect(screen.getByText("Шалтгаан: Ажлын ачаалал").classList.contains("text-red-700")).toBe(true);
    expect(screen.queryByText("Буцаах")).toBeNull();
  });

  it("shows the empty line with no requests", () => {
    renderIn(<MyRequests requests={[]} />);
    expect(screen.getByText("Хүсэлт гаргаагүй байна.")).toBeTruthy();
  });
});

describe("Recorded", () => {
  it("shows the list of recorded leave", () => {
    renderIn(
      <Recorded recorded={[{ leave_type: "Ээлжийн амралт", start: "2026-06-01", end: "2026-06-03", days: "3" }]} />,
    );
    expect(screen.getByText("Ээлжийн амралт · 2026-06-01 – 2026-06-03")).toBeTruthy();
    expect(screen.getByText("3 өдөр")).toBeTruthy();
  });

  it("shows «Бүртгэгдээгүй» when nothing is recorded", () => {
    renderIn(<Recorded recorded={[]} />);
    expect(screen.getByText("Бүртгэгдээгүй")).toBeTruthy();
  });
});
