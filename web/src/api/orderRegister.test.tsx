// The harness is imported first: it stubs fetch before ./client (and so ./orderRegister) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import { invalidateEventWrites } from "./events";
import { retryMe } from "./me";
import { fetchPrintStatus, useOrderPrint, useOrderRegister, useStartPrintJob, type RegisterParams } from "./orderRegister";

const PARAMS: RegisterParams = { q: "", sort: "", year: "", order_type: "", department: "", state: "" };

const REGISTER_PAGE_1 = {
  all_labels: { department: "" },
  background_from: 0,
  can_manage: false,
  next_offset: 60,
  options: { departments: [], states: [], types: [], years: [] },
  query: { department: null, order_type: null, q: "", sort: "", state: "", year: null },
  report_link: false,
  rows: [],
  sort_heads: {},
};

const REGISTER_PAGE_2 = { ...REGISTER_PAGE_1, next_offset: null };

const PRINT_OUT = { company: "", empty: true, groups: [], today: "" };

describe("order register and print API", () => {
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
    // Back to focused and online for the next test. (undefined would fall back to navigator.onLine, which is false in
    // this environment and pauses every query and mutation.)
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  it("useOrderRegister loads the next page with the offset", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, REGISTER_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, REGISTER_PAGE_2));

    const { result } = renderHook(() => useOrderRegister(PARAMS), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/orders/register");
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("60");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useOrderRegister restarts at offset 0 when params change", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REGISTER_PAGE_2));

    const { result, rerender } = renderHook(
      (params: RegisterParams) => useOrderRegister(params),
      { wrapper: wrapperFor(client), initialProps: PARAMS },
    );
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ ...PARAMS, q: "Бат" });
    // The old filter's rows are not kept: the new key has no data until its first batch arrives.
    expect(result.current.data).toBeUndefined();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(urlOf(1).searchParams.get("q")).toBe("Бат");
    expect(urlOf(1).searchParams.get("offset")).toBe("0");
  });

  it("invalidateEventWrites also invalidates the register key", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REGISTER_PAGE_2));
    const spy = vi.spyOn(client, "invalidateQueries");

    await invalidateEventWrites(client, 5);

    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["orders-register"] });
  });

  it("useOrderPrint loads the print page once and reads the route", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(200, PRINT_OUT)));

    const { result } = renderHook(() => useOrderPrint(PARAMS), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/orders/print");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useOrderPrint does not refetch on a window focus or a reconnect (each GET writes an audit row)", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(200, PRINT_OUT)));

    const { result } = renderHook(() => useOrderPrint(PARAMS), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("a control query with default options DOES refetch on the same focus and reconnect (the trigger works here)", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(200, PRINT_OUT)));

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ["control-focus"],
          queryFn: () => fetch("/api/v1/orders/print").then((r) => r.json()),
        }),
      { wrapper: wrapperFor(client) },
    );
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("useOrderPrint is not kept after the page goes: a new mount fetches again", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(200, PRINT_OUT)));

    const first = renderHook(() => useOrderPrint(PARAMS), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();
    // gcTime 0 removes the query on the next timer tick after the last observer leaves.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(client.getQueryCache().find({ queryKey: ["orders-print", PARAMS] })).toBeUndefined();

    const second = renderHook(() => useOrderPrint(PARAMS), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(second.result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retryMe retries a server error up to three times and never a 401, 403 or 404", () => {
    expect(retryMe(0, { status: 500 })).toBe(true);
    expect(retryMe(2, { status: 500 })).toBe(true);
    expect(retryMe(3, { status: 500 })).toBe(false);
    expect(retryMe(0, { status: 404 })).toBe(false);
    expect(retryMe(0, { status: 403 })).toBe(false);
    expect(retryMe(0, { status: 401 })).toBe(false);
  });

  it("startPrintJob posts ids as form values with repeated ids", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { token: "t1", status: "/s", file: "/f" }));

    const { result } = renderHook(() => useStartPrintJob(), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync([3, 4]);
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/orders/print/start");
    expect(request.headers.get("Content-Type")).toContain("application/x-www-form-urlencoded");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(await request.text()).toBe("ids=3&ids=4");
    expect((answer as { token: string }).token).toBe("t1");
  });

  it("fetchPrintStatus reads the job's status route by token", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { state: "running", message: "", count: 12 }));

    const status = await fetchPrintStatus("t1");

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/orders/print/t1/status");
    expect(status.state).toBe("running");
  });

  it("fetchPrintStatus on a 404 (another user's or an unknown job) rejects with status 404", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: [] }));

    await expect(fetchPrintStatus("nope")).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
