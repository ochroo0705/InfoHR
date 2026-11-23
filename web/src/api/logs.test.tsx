// The harness is imported first: it stubs fetch before ./client (and so ./logs) load.
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers, urlOf, wrapperFor } from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import { excelHref, useEmployeeLog, useSystemLog, type EmployeeLogParams, type SystemLogParams } from "./logs";

const EMPLOYEE_PARAMS: EmployeeLogParams = {
  q: "",
  emp: "",
  employee: "",
  by: "",
  kind: [],
  area: "",
  field: "",
  from: "",
  to: "",
  system: "",
  oldest: "",
};

const SYSTEM_PARAMS: SystemLogParams = {
  q: "",
  by: "",
  target: "",
  ip: "",
  category: [],
  action: "",
  from: "",
  to: "",
  oldest: "",
};

const EMPLOYEE_PAGE_1 = {
  address: "",
  chip: null,
  next_offset: 60,
  options: { kinds: [], areas: [] },
  query: {},
  rows: [],
  tabs: { employee: true, system: false, export: false },
};

const EMPLOYEE_PAGE_2 = { ...EMPLOYEE_PAGE_1, next_offset: null };

const SYSTEM_PAGE = {
  address: "",
  next_offset: null,
  options: { categories: [], actions: [] },
  query: {},
  rows: [],
  tabs: { employee: false, system: true, export: false },
};

describe("log API", () => {
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

  it("useEmployeeLog sends repeated kind values and loads the next page with the offset", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, EMPLOYEE_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, EMPLOYEE_PAGE_2));

    const params = { ...EMPLOYEE_PARAMS, kind: ["correction", "note"] };
    const { result } = renderHook(() => useEmployeeLog(params), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/logs/employee");
    expect(urlOf(0).search).toContain("kind=correction&kind=note");
    expect(urlOf(0).searchParams.getAll("kind")).toEqual(["correction", "note"]);
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("60");
    expect(urlOf(1).searchParams.getAll("kind")).toEqual(["correction", "note"]);
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useEmployeeLog restarts at offset 0 when params change", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, EMPLOYEE_PAGE_2));

    const { result, rerender } = renderHook((params: EmployeeLogParams) => useEmployeeLog(params), {
      wrapper: wrapperFor(client),
      initialProps: EMPLOYEE_PARAMS,
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ ...EMPLOYEE_PARAMS, q: "Бат" });
    // The old address's rows are not kept: the new key has no data until its first batch arrives.
    expect(result.current.data).toBeUndefined();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(urlOf(1).searchParams.get("q")).toBe("Бат");
    expect(urlOf(1).searchParams.get("offset")).toBe("0");
  });

  it("useSystemLog sends category repeated and from/to under their URL names", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, SYSTEM_PAGE));

    const params = { ...SYSTEM_PARAMS, category: ["auth", "orders"], from: "2026-01-01", to: "2026-02-01" };
    const { result } = renderHook(() => useSystemLog(params), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/logs/system");
    expect(urlOf(0).searchParams.getAll("category")).toEqual(["auth", "orders"]);
    expect(urlOf(0).searchParams.get("from")).toBe("2026-01-01");
    expect(urlOf(0).searchParams.get("to")).toBe("2026-02-01");
    expect(urlOf(0).searchParams.get("date_from")).toBeNull();
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
  });

  it("excelHref adds the address only when it is not empty", () => {
    expect(excelHref("employee", "")).toBe("/api/v1/logs/employee/export");
    expect(excelHref("system", "")).toBe("/api/v1/logs/system/export");
    expect(excelHref("employee", "q=a&kind=note")).toBe("/api/v1/logs/employee/export?q=a&kind=note");
    expect(excelHref("system", "category=auth")).toBe("/api/v1/logs/system/export?category=auth");
  });
});
