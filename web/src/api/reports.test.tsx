// The harness is imported first: it stubs fetch before ./client (and so ./reports) load.
import { fetchMock, jsonResponse, newClient, rejectionOf, resetFetch, resetObservers, urlOf, wrapperFor } from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  fetchCatalogue,
  reportKeys,
  useCatalogue,
  useReportPage,
  useReportRows,
  type ReportPageOut,
  type ReportTableOut,
} from "./reports";

const TABLE_FIRST = {
  address: "/reports/staff/",
  check_css: "",
  check_style: "",
  clear_rules_url: "",
  count: 120,
  footer: null,
  groups: [],
  heads: [],
  next_offset: 50,
  note: "",
  pin: 0,
  query: "",
  rules_text: "",
  selectable: false,
  shows_count: true,
  table_span: 1,
} as unknown as ReportTableOut;

const PAGE_TABLE = {
  redirect: "",
  title: "Ажилтны жагсаалт",
  layout: "table",
  head: null,
  bar: null,
  table: TABLE_FIRST,
} as unknown as ReportPageOut;

const ROWS_LAST = { groups: [], next_offset: null };

describe("report API", () => {
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

  it("catalogue_path: fetchCatalogue reads /api/v1/reports/catalogue", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { sections: [] }));

    const catalogue = await fetchCatalogue();

    expect(catalogue).toEqual({ sections: [] });
    expect(urlOf(0).pathname).toBe("/api/v1/reports/catalogue");
    expect(urlOf(0).search).toBe("");
  });

  it("useCatalogue loads the catalogue under reportKeys.catalogue", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { sections: [] }));

    const { result } = renderHook(() => useCatalogue(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(reportKeys.catalogue).toEqual(["reports", "catalogue"]);
    expect(urlOf(0).pathname).toBe("/api/v1/reports/catalogue");
  });

  it("page_request_sends_query_verbatim_and_offset_zero", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, PAGE_TABLE));

    const query = "q=a%20b&add=branch&add=position&sort=-name&empty=";
    const { result } = renderHook(() => useReportPage("staff", query), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff");
    // The address query is sent as typed: the percent-encoding, repeated keys and order are kept.
    expect(urlOf(0).search).toBe("?q=a%20b&add=branch&add=position&sort=-name&empty=&offset=0");
    expect(urlOf(0).searchParams.getAll("add")).toEqual(["branch", "position"]);
    expect(result.current.data?.table?.count).toBe(120);
  });

  it("page_request_with_empty_query_sends_only_offset", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, PAGE_TABLE));

    const { result } = renderHook(() => useReportPage("staff", ""), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).search).toBe("?offset=0");
  });

  it("page query is not refetched on window focus and is stale at once", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, PAGE_TABLE));

    const { result } = renderHook(() => useReportPage("staff", "q=a"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rows_request_adds_offset: the seeded first batch is not requested again, the next batch is", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ROWS_LAST));

    const { result } = renderHook(() => useReportRows("staff", "q=a&add=branch", TABLE_FIRST, 1), {
      wrapper: wrapperFor(client),
    });

    // The first batch comes from the page answer: nothing is sent on mount.
    expect(result.current.data?.pages[0].next_offset).toBe(50);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/rows");
    expect(urlOf(0).search).toBe("?q=a&add=branch&offset=50");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("two_seed_versions_are_two_cache_entries: a refetched page starts its own seeded query", async () => {
    const { result: first } = renderHook(() => useReportRows("staff", "q=a", TABLE_FIRST, 1), {
      wrapper: wrapperFor(client),
    });
    const renewed = { ...TABLE_FIRST, next_offset: 20 } as unknown as ReportTableOut;
    const { result: second } = renderHook(() => useReportRows("staff", "q=a", renewed, 2), {
      wrapper: wrapperFor(client),
    });

    expect(first.current.data?.pages[0].next_offset).toBe(50);
    expect(second.current.data?.pages[0].next_offset).toBe(20);
    expect(client.getQueryCache().findAll({ queryKey: ["reports", "staff", "rows"] })).toHaveLength(2);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("seed_change_does_not_refetch_the_seeded_first_batch: no /rows?offset=0 after a new seed, once the tick has run", async () => {
    const { rerender } = renderHook(({ seed }: { seed: number }) => useReportRows("staff", "q=a", TABLE_FIRST, seed), {
      wrapper: wrapperFor(client),
      initialProps: { seed: 1 },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(fetchMock).not.toHaveBeenCalled();

    // The page refetched: a new seed is a new query, with its own first batch as data.
    rerender({ seed: 2 });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const offsets = fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url).searchParams.get("offset"));
    expect(offsets).not.toContain("0");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("403_and_404_are_thrown_as_typed_errors", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));

    const { result } = renderHook(() => useReportPage("staff", ""), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 403, code: "forbidden" });

    fetchMock.mockResolvedValueOnce(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));
    const caught = await rejectionOf(() => fetchCatalogue());
    expect(caught).toMatchObject({ status: 404, formErrors: ["Олдсонгүй"] });

    fetchMock.mockResolvedValueOnce(jsonResponse(404, { field_errors: {}, form_errors: [] }));
    const rows = renderHook(() => useReportRows("nope", "", TABLE_FIRST, 1), { wrapper: wrapperFor(client) });
    // A screen reads the error state while it draws, so React Query tracks it and re-renders on the failure.
    expect(rows.result.current.isError).toBe(false);
    await act(async () => {
      await rows.result.current.fetchNextPage();
    });
    await vi.waitFor(() => expect(rows.result.current.isError).toBe(true));
    expect(rows.result.current.error).toMatchObject({ status: 404 });
  });

  it("redirect_answer_is_returned_not_followed_here", async () => {
    const redirect = "/reports/staff/?view=plain";
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...PAGE_TABLE, redirect, table: null, title: "" }));

    const { result } = renderHook(() => useReportPage("staff", ""), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.redirect).toBe(redirect);
    expect(result.current.data?.table).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
