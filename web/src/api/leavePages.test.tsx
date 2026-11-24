// The harness is imported first: it stubs fetch before ./client (and so ./leavePages) load.
import {
  fetchMock,
  jsonResponse,
  newClient,
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
import { useLeaveBalances, useLeaveCalendar, type LeaveBalanceListOut, type LeaveCalendarOut } from "./leavePages";
import type { ApiFailure } from "./mutate";

const ROW = {
  employee_id: 3,
  employee_name: "Бат Болд",
  waiting: null,
  period: { start: "2026-01-01", end: "2026-12-31", granted: 15, taken: 5, left: 10 },
};

const BALANCES_PAGE_1: LeaveBalanceListOut = {
  can_settings: false,
  empty_text: "",
  next_offset: 50,
  not_configured: "",
  rows: [ROW],
  today: "2026-11-24",
};

const BALANCES_PAGE_2: LeaveBalanceListOut = { ...BALANCES_PAGE_1, next_offset: null, rows: [] };

const CALENDAR: LeaveCalendarOut = {
  can_settings: false,
  days: [],
  department: null,
  departments: [],
  lines: [],
  month: "2026-11",
  next: "2026-12",
  not_configured: "",
  prev: "2026-10",
  this_month: "",
  title: "2026-11",
};

describe("leave balances and calendar API", () => {
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

  it("useLeaveBalances asks for the first batch at offset 0 under the balances key", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, BALANCES_PAGE_2));

    const { result } = renderHook(() => useLeaveBalances(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/leave/balances");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(client.getQueryCache().find({ queryKey: ["leave", "balances"] })).toBeDefined();
  });

  it("useLeaveBalances loads the next batch at next_offset and stops when next_offset is null", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, BALANCES_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, BALANCES_PAGE_2));

    const { result } = renderHook(() => useLeaveBalances(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useLeaveBalances fails with the status 403 when the user may not view balances", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"], code: "forbidden" }));

    const { result } = renderHook(() => useLeaveBalances(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(403);
  });

  it("useLeaveCalendar sends the month and department that have a value", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, CALENDAR));

    const { result } = renderHook(() => useLeaveCalendar({ month: "2026-11", department: "4" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/leave/calendar");
    expect(url.searchParams.get("month")).toBe("2026-11");
    expect(url.searchParams.get("department")).toBe("4");
  });

  it("useLeaveCalendar leaves out empty values, so an empty filter sends no query at all", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, CALENDAR));

    const { result } = renderHook(() => useLeaveCalendar({ month: "", department: "" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.searchParams.has("month")).toBe(false);
    expect(url.searchParams.has("department")).toBe(false);
  });

  it("useLeaveCalendar keys the query by its params, so a changed month is a new query", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, CALENDAR));

    const { result } = renderHook(() => useLeaveCalendar({ month: "2026-11" }), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryCache().find({ queryKey: ["leave", "calendar", { month: "2026-11" }] })).toBeDefined();
  });

  it("useLeaveCalendar fails with the status 403 when the user may not view the calendar", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"], code: "forbidden" }));

    const { result } = renderHook(() => useLeaveCalendar({}), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(403);
  });
});
