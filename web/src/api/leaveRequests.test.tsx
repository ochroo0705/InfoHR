// The harness is imported first: it stubs fetch before ./client (and so ./leaveRequests) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  rejectionOf,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  useApproveRequest,
  useCheckLeaveRequest,
  useCreateLeaveRequest,
  useLeaveRequestDetail,
  useLeaveRequestOptions,
  useLeaveRequests,
  useRejectRequest,
  type LeaveRequestDetailOut,
  type LeaveRequestFormIn,
  type LeaveRequestListOut,
} from "./leaveRequests";
import type { ApiFailure } from "./mutate";

const ROW = {
  id: 9,
  current_step: 1,
  employee_name: "Бат Болд",
  end: "2026-11-21",
  leave_type: "Жирийн амралт",
  rule: "",
  since: null,
  start: "2026-11-20",
  status_label: "Хүлээгдэж байна",
  step_count: 2,
  waiting: true,
  working_days: 2,
};

const LIST_PAGE_1: LeaveRequestListOut = {
  can_all: true,
  empty_text: "",
  next_offset: 50,
  rows: [ROW],
  status: "",
  statuses: [],
  tab: "mine",
};

const LIST_PAGE_2: LeaveRequestListOut = { ...LIST_PAGE_1, next_offset: null, rows: [] };

const DETAIL: LeaveRequestDetailOut = {
  balance_after: null,
  created: "2026-11-19",
  current_step: 1,
  employee_name: "Бат Болд",
  end: "2026-11-21",
  history: [],
  id: 9,
  job_line: "",
  leave_type: "Жирийн амралт",
  may: true,
  needs_reason: false,
  others: [],
  override: false,
  past: false,
  reason: "",
  rule: "",
  start: "2026-11-20",
  status_label: "Хүлээгдэж байна",
  step_count: 2,
  waiting: true,
  warnings: [],
  working_days: 2,
};

const DETAIL_KEY = ["leave", "requests", "detail", 9];

const OK = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED = { ok: false, error: "Өөрчлөгдсөн", field_errors: {}, form_errors: ["Өөрчлөгдсөн"] };

const FORM: LeaveRequestFormIn = { leave_type: 2, start_date: "2026-11-20", end_date: "2026-11-21", note: "" };

// The keys a successful request write must refresh (besides the leave prefix, which refreshAfterLeaveWrite covers).
const WRITE_KEYS = [{ queryKey: ["leave", "requests"] }, { queryKey: ["attention"] }, { queryKey: ["nav"] }];

describe("leave request API", () => {
  let client: QueryClient;

  beforeEach(() => {
    resetFetch();
    setCsrf("");
    client = newClient();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetObservers();
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  it("useLeaveRequests sends only the filters that have a value, plus offset 0", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useLeaveRequests({ tab: "all", status: "" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/leave/requests");
    expect(url.searchParams.get("tab")).toBe("all");
    expect(url.searchParams.has("status")).toBe(false);
    expect(url.searchParams.get("offset")).toBe("0");
  });

  it("useLeaveRequests loads the next batch at next_offset and stops when next_offset is null", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useLeaveRequests({ tab: "mine" }), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useLeaveRequests fails with the status when the list is refused (403)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));

    const { result } = renderHook(() => useLeaveRequests({}), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(403);
  });

  it("useLeaveRequestDetail asks for request 9 at its path and drops the row from the cache once unused (gcTime 0)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, DETAIL));

    const { result, unmount } = renderHook(() => useLeaveRequestDetail(9), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests/9");
    unmount();
    await vi.waitFor(() => expect(client.getQueryCache().find({ queryKey: DETAIL_KEY })).toBeUndefined());
  });

  it("useLeaveRequestDetail fails with 404 when the user may not act on the request", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["no"] }));

    const { result } = renderHook(() => useLeaveRequestDetail(9), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
  });

  it("useLeaveRequestOptions asks for the staff request types at /api/v1/leave/requests/options", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { types: [] }));

    const { result } = renderHook(() => useLeaveRequestOptions(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests/options");
  });

  it("useApproveRequest posts the body to /{pk}/approve and refreshes leave, requests, attention, nav and me on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useApproveRequest(9), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ override_reason: "", step: 1 }));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests/9/approve");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent).toEqual({ override_reason: "", step: 1 });

    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave"] });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["me"] });
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("an approve that answers ok false refreshes only the detail, not the lists, attention or nav", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useApproveRequest(9), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ override_reason: "", step: 1 }));

    expect(saved.ok).toBe(false);
    expect(invalidatedKeys(spy)).toEqual([{ queryKey: DETAIL_KEY }]);
  });

  it("an approve refused with 403 rejects with the status and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useApproveRequest(9), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync({ override_reason: "", step: 1 }));

    expect((caught as ApiFailure).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useRejectRequest posts the reason to /{pk}/reject and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useRejectRequest(9), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ reason: "Буруу" }));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests/9/reject");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent).toEqual({ reason: "Буруу" });
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("a reject that answers ok false refreshes only the detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useRejectRequest(9), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ reason: "Буруу" }));

    expect(invalidatedKeys(spy)).toEqual([{ queryKey: DETAIL_KEY }]);
  });

  it("useCreateLeaveRequest posts the form to /api/v1/leave/requests and refreshes leave, requests, attention, nav and me on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeaveRequest(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(FORM));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave"] });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["me"] });
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useCreateLeaveRequest returns a refused create (ok false) and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...REFUSED, field_errors: { end_date: ["Буруу"] } }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeaveRequest(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(FORM));

    expect(saved.ok).toBe(false);
    expect(saved.field_errors).toEqual({ end_date: ["Буруу"] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("useCreateLeaveRequest rejects with the status when the create is refused (403) and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeaveRequest(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(FORM));

    expect((caught as ApiFailure).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useCheckLeaveRequest posts to /api/v1/leave/requests/check and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        valid: true,
        errors: [],
        warnings: [],
        working_days: 2,
        balance_after: 10,
        period: { start: "2026-11-20", end: "2026-11-21" },
      }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCheckLeaveRequest(), { wrapper: wrapperFor(client) });
    const checked = await act(() => result.current.mutateAsync(FORM));

    expect(checked.working_days).toBe(2);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/requests/check");
    expect(spy).not.toHaveBeenCalled();
  });
});
