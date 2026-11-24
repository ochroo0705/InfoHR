import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaveCheckOut } from "../../api/leave";
import { LeaveCheck, type LeaveCheckValues } from "./LeaveCheck";

// The API client is replaced by a stub that answers by path, so the real helpers and hooks run.
const h = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: vi.fn(), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const READY: LeaveCheckValues = {
  employee: "3",
  leave_type: "2",
  start_date: "2026-12-01",
  end_date: "2026-12-03",
  note: "",
  override_reason: "",
};

function answer(data: Partial<LeaveCheckOut>): LeaveCheckOut {
  return { valid: true, errors: [], warnings: [], working_days: 3, balance_after: null, period: null, ...data };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

// Wraps the check in the query client the hooks need. A test keeps one client for all its renders.
let client = makeClient();
function tree(values: LeaveCheckValues, leaveId?: number | null): ReactNode {
  return (
    <QueryClientProvider client={client}>
      <LeaveCheck values={values} leaveId={leaveId} />
    </QueryClientProvider>
  );
}

// A commit of the form: the values change to `values` (a pick, a whole date, a box left). The first render is the form
// before that change, which asks nothing; the rerender is the commit.
function committed(values: LeaveCheckValues, leaveId?: number | null) {
  const view = render(tree({ ...values, end_date: "" }, leaveId));
  view.rerender(tree(values, leaveId));
  return view;
}

describe("LeaveCheck", () => {
  beforeEach(() => {
    h.post.mockReset();
    client = makeClient();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("keeps the live region mounted and empty before any answer", () => {
    const { container } = render(tree({ ...READY, end_date: "" }));
    const region = container.querySelector('[aria-live="polite"]');
    expect(region).not.toBeNull();
    expect(region?.textContent).toBe("");
  });

  it("asks nothing while one of the four boxes is empty", async () => {
    render(tree({ ...READY, end_date: "" }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();
  });

  it("asks nothing on mount, in edit mode too", async () => {
    render(tree(READY, 7));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();
  });

  it("a burst of commits gives one question, 300 ms after the last one, and none before", async () => {
    vi.useFakeTimers();
    h.post.mockResolvedValue(ok(answer({})));
    const view = render(tree({ ...READY, end_date: "" }));

    view.rerender(tree({ ...READY, end_date: "2026-12-04" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    view.rerender(tree({ ...READY, end_date: "2026-12-05" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(h.post).not.toHaveBeenCalled();

    view.rerender(tree({ ...READY, end_date: "2026-12-06" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(h.post).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(h.post).toHaveBeenCalledTimes(1);
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { end_date: "2026-12-06" } });
  });

  it("asks after the 300 ms pause and shows the days and the balance after", async () => {
    h.post.mockResolvedValue(
      ok(answer({ working_days: 3, balance_after: 10, period: { start: "2026-12-01", end: "2026-12-03" } })),
    );
    const { container } = committed(READY);

    await waitFor(() => expect(container.textContent).toContain("3 ажлын өдөр · үлдэх: 10"));
    expect(container.textContent).toContain("Хугацаа: 2026-12-01 – 2026-12-03");
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/check", {
      body: { employee: 3, leave_type: 2, start_date: "2026-12-01", end_date: "2026-12-03", leave_id: null, note: "", override_reason: "" },
    });
  });

  it("leaves the balance out when it is not known", async () => {
    h.post.mockResolvedValue(ok(answer({ working_days: 2, balance_after: null })));
    const { container } = committed(READY);

    await waitFor(() => expect(container.textContent).toContain("2 ажлын өдөр"));
    expect(container.textContent).not.toContain("үлдэх");
  });

  it("shows the errors in red and no day count", async () => {
    h.post.mockResolvedValue(ok(answer({ valid: false, errors: ["Хугацаа буруу байна."] })));
    const { container, findByText } = committed(READY);

    const message = await findByText("Хугацаа буруу байна.");
    expect(message.className).toContain("text-red-700");
    expect(container.textContent).not.toContain("ажлын өдөр");
  });

  it("shows the warnings in amber", async () => {
    h.post.mockResolvedValue(ok(answer({ warnings: ["Урт чөлөө."] })));
    const { findByText } = committed(READY);

    const message = await findByText("Урт чөлөө.");
    expect(message.className).toContain("text-amber-700");
  });

  it("shows nothing when the answer is not valid and has no lists", async () => {
    h.post.mockResolvedValue(ok(answer({ valid: false })));
    const { container } = committed(READY);

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(container.textContent).toBe("");
  });

  it("sends the leave's id in edit mode", async () => {
    h.post.mockResolvedValue(ok(answer({})));
    committed(READY, 7);

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/check", { body: expect.objectContaining({ leave_id: 7 }) });
  });

  it("shows the latest answer only, even when an older one arrives last", async () => {
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    h.post
      .mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
      .mockReturnValueOnce(new Promise((resolve) => (resolveSecond = resolve)));

    const { container, rerender } = committed(READY);
    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));

    rerender(tree({ ...READY, end_date: "2026-12-04" }));
    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveSecond(ok(answer({ working_days: 4 })));
    });
    await waitFor(() => expect(container.textContent).toContain("4 ажлын өдөр"));

    await act(async () => {
      resolveFirst(ok(answer({ working_days: 9 })));
    });
    expect(container.textContent).toContain("4 ажлын өдөр");
    expect(container.textContent).not.toContain("9 ажлын өдөр");
  });
});

// The staff request form's check (mode "request"): no employee, no leave id, and the request check endpoint.
describe("LeaveCheck request mode", () => {
  const REQUEST_READY: LeaveCheckValues = {
    employee: "",
    leave_type: "2",
    start_date: "2026-12-01",
    end_date: "2026-12-03",
    note: "",
    override_reason: "",
  };

  function requestTree(values: LeaveCheckValues): ReactNode {
    return (
      <QueryClientProvider client={client}>
        <LeaveCheck values={values} mode="request" />
      </QueryClientProvider>
    );
  }

  // The form's commit in request mode: the first render is the form before the change, the rerender is the commit.
  function requestCommitted(values: LeaveCheckValues) {
    const view = render(requestTree({ ...values, end_date: "" }));
    view.rerender(requestTree(values));
    return view;
  }

  beforeEach(() => {
    h.post.mockReset();
    client = makeClient();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("asks nothing on mount in request mode", async () => {
    render(requestTree(REQUEST_READY));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();
  });

  it("asks once type and both dates are set, with no employee and no leave id", async () => {
    h.post.mockResolvedValue(ok(answer({})));
    requestCommitted(REQUEST_READY);

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/requests/check", {
      body: { leave_type: 2, start_date: "2026-12-01", end_date: "2026-12-03", note: "" },
    });
    const body = (h.post.mock.calls[0][1] as { body: Record<string, unknown> }).body;
    expect(Object.keys(body)).not.toContain("employee");
    expect(Object.keys(body)).not.toContain("leave_id");
  });

  it("asks nothing while the type or a date is empty, even with an employee in the values", async () => {
    requestCommitted({ ...REQUEST_READY, leave_type: "" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();

    requestCommitted({ ...REQUEST_READY, start_date: "", employee: "3" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();
  });

  it("shows the day count of the request answer", async () => {
    h.post.mockResolvedValue(ok(answer({ working_days: 3, balance_after: 7 })));
    const { container } = requestCommitted(REQUEST_READY);

    await waitFor(() => expect(container.textContent).toContain("3 ажлын өдөр · үлдэх: 7"));
  });

  it("record mode still asks nothing without an employee", async () => {
    committed({ ...READY, employee: "" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(h.post).not.toHaveBeenCalled();
  });
});
