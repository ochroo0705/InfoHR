// The harness is imported first: it stubs fetch before ./client (and so ./leave) load.
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
  useCancelLeave,
  useCheckLeave,
  useCreateLeave,
  useLeaveCancelInfo,
  useLeaveEdit,
  useLeaveList,
  useLeaveOptions,
  useUpdateLeave,
  type LeaveListOut,
  type LeaveWriteIn,
} from "./leave";
import type { ApiFailure } from "./mutate";

const ROW = {
  id: 7,
  employee_id: 3,
  employee_name: "Бат Болд",
  leave_type: "Жирийн амралт",
  start: "2026-11-20",
  end: "2026-11-21",
  days: 2,
  comment: "",
  state: "",
  state_chip: false,
  counts: true,
  cancel_label: "Цуцлах",
};

const LIST_PAGE_1: LeaveListOut = {
  can_record: true,
  can_settings: false,
  empty_text: "",
  filters: { date_from: "", date_to: "", employee: null, q: "", status: "recorded", type_id: null },
  missing_holidays: [],
  next_offset: 50,
  not_configured: "",
  report_url: null,
  rows: [ROW],
  types: [],
};

const LIST_PAGE_2: LeaveListOut = { ...LIST_PAGE_1, next_offset: null, rows: [] };

const LOADED = { leave_type: 2, date1: "2026-11-20", date2: "2026-11-21", status: null, adays: 2, comment: null };

const OK = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED = { ok: false, error: "", field_errors: { end_date: ["Буруу"] }, form_errors: [] };

const BODY: LeaveWriteIn = {
  employee: 3,
  leave_type: 2,
  start_date: "2026-11-20",
  end_date: "2026-11-21",
  note: "",
  override_reason: "",
};

// The invalidation that matches an employee's activity log (any employee): its predicate, as the write sends it.
function isActivity(filter: unknown): boolean {
  const predicate = (filter as { predicate?: (q: { queryKey: unknown[] }) => boolean }).predicate;
  return predicate !== undefined && predicate({ queryKey: ["employee", 1, "activity"] });
}

describe("leave API", () => {
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

  it("useLeaveList sends only the filters that have a value, plus offset 0", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(
      () => useLeaveList({ q: "Бат", employee: "", status: "all", type: undefined, from: "2026-01-01", to: "" }),
      { wrapper: wrapperFor(client) },
    );
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/leave");
    expect(url.searchParams.get("q")).toBe("Бат");
    expect(url.searchParams.get("status")).toBe("all");
    expect(url.searchParams.get("from")).toBe("2026-01-01");
    expect(url.searchParams.has("employee")).toBe(false);
    expect(url.searchParams.has("type")).toBe(false);
    expect(url.searchParams.has("to")).toBe(false);
    expect(url.searchParams.get("offset")).toBe("0");
  });

  it("useLeaveList loads the next batch at next_offset and stops when next_offset is null", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useLeaveList({}), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useLeaveList fails with the status when the user may not view the list (403)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));

    const { result } = renderHook(() => useLeaveList({}), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as ApiFailure).status).toBe(403);
  });

  it("useLeaveOptions asks for the options with the given values only", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        assisted: null,
        employees: [],
        initial: { employee: null, end_date: "", leave_type: null, start_date: "" },
        not_configured: "",
        types: [],
      }),
    );

    const { result } = renderHook(() => useLeaveOptions({ employee: "3", from: "assistant", start: "" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/leave/options");
    expect(url.searchParams.get("employee")).toBe("3");
    expect(url.searchParams.get("from")).toBe("assistant");
    expect(url.searchParams.has("start")).toBe(false);
  });

  it("useLeaveEdit and useLeaveCancelInfo ask for leave 7 at its own paths", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(200, {}));

    const edit = renderHook(() => useLeaveEdit(7), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(edit.result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/leave/7");

    const cancel = renderHook(() => useLeaveCancelInfo(7), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(cancel.result.current.isSuccess).toBe(true));
    expect(urlOf(1).pathname).toBe("/api/v1/leave/7/cancel");
  });

  it("useCreateLeave posts the form to /api/v1/leave and refreshes the leave, me, today and work data on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeave(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(BODY));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave"] });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["me"] });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["today"] });

    const workCall = spy.mock.calls.find((call) => "predicate" in (call[0] as object));
    const predicate = (workCall?.[0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }).predicate;
    expect(predicate({ queryKey: ["employee", 3, "work"] })).toBe(true);
    expect(predicate({ queryKey: ["employee", 3, "salary"] })).toBe(false);
  });

  it("a saved leave also refreshes the employee activity and the employee log", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeave(), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync(BODY));

    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["logs-employee"] });
    const activityCall = spy.mock.calls.find((call) => "predicate" in (call[0] as object) && isActivity(call[0]));
    const predicate = (activityCall?.[0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }).predicate;
    expect(predicate({ queryKey: ["employee", 3, "activity"] })).toBe(true);
    expect(predicate({ queryKey: ["employee", 3, "work"] })).toBe(false);
  });

  it("a refused write refreshes neither the activity nor the employee log", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: false, error: "", form_errors: [], field_errors: {} }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeave(), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync(BODY));

    expect(invalidatedKeys(spy)).not.toContainEqual({ queryKey: ["logs-employee"] });
    expect(spy.mock.calls.some((call) => isActivity(call[0]))).toBe(false);
  });

  it("useCreateLeave returns a refused write (ok false) and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeave(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(BODY));

    expect(saved.ok).toBe(false);
    expect(saved.field_errors).toEqual({ end_date: ["Буруу"] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("useCreateLeave rejects with the status when the user may not record (403) and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLeave(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(BODY));

    expect((caught as ApiFailure).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useUpdateLeave posts the change with the loaded row to /api/v1/leave/{pk}", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const { result } = renderHook(() => useUpdateLeave(7), { wrapper: wrapperFor(client) });

    await act(() => result.current.mutateAsync({ ...BODY, loaded: LOADED }));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/7");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent.loaded).toEqual(LOADED);
  });

  it("useUpdateLeave answers a stale row (ok false) and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, error: "Өөрчлөгдсөн", field_errors: {}, form_errors: ["Өөрчлөгдсөн"] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useUpdateLeave(7), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ ...BODY, loaded: null }));

    expect(saved.ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useCancelLeave posts the reason to /api/v1/leave/{pk}/cancel and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCancelLeave(7), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ loaded: LOADED, reason: "" }));

    expect(saved.ok).toBe(true);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/7/cancel");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave"] });
  });

  it("useCheckLeave posts to /api/v1/leave/check and invalidates nothing", async () => {
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

    const { result } = renderHook(() => useCheckLeave(), { wrapper: wrapperFor(client) });
    const checked = await act(() => result.current.mutateAsync({ employee: 3, start_date: "2026-11-20", note: "", override_reason: "" }),
    );

    expect(checked.working_days).toBe(2);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/check");
    expect(spy).not.toHaveBeenCalled();
  });
});
