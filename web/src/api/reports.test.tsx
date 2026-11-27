// The harness is imported first: it stubs fetch before ./client (and so ./reports) load.
import {
  csrfFailure,
  fetchMock,
  jsonResponse,
  metaBody,
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
import { getCsrf, setCsrf } from "./client";
import {
  fetchCatalogue,
  reportKeys,
  useColumnsModel,
  useSaveView,
  useUpdateView,
  useViewForm,
  useCatalogue,
  useReportCards,
  useReportPage,
  useReportPrint,
  useReportRows,
  copySelection,
  fetchChecklistForm,
  postSelection,
  printTicket,
  startChecklists,
  type ReportChecklistStartIn,
  type ReportSelectionIn,
  type ReportCardsOut,
  type ReportPageOut,
  type ReportTableOut,
  type ReportViewIn,
} from "./reports";

const CARDS_FIRST = {
  items: [{ title: "Нэг", href: "/a/1" }],
  next_offset: 2,
  total: 3,
} as unknown as ReportCardsOut;

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

  it("cards_request_adds_offset: the seeded first batch is not requested again, the next batch is", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { items: [], next_offset: null, total: 3 }));

    const { result } = renderHook(() => useReportCards("staff", "q=a&add=branch", CARDS_FIRST, 1), {
      wrapper: wrapperFor(client),
    });

    // The first batch comes from the page answer: nothing is sent on mount.
    expect(result.current.data?.pages[0].next_offset).toBe(2);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/cards");
    expect(urlOf(0).search).toBe("?q=a&add=branch&offset=2");
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

  it("columns model path sends query verbatim, without an offset", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { groups: [], group: "", group_text: "", group_choices: [], keep: [] }));

    const { result } = renderHook(() => useColumnsModel("staff", "?q=a%20b&add=branch&cols=name", true), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/columns");
    expect(urlOf(0).search).toBe("?q=a%20b&add=branch&cols=name");
    expect(urlOf(0).searchParams.has("offset")).toBe(false);
  });

  it("model hooks do not fetch while closed", async () => {
    const { result } = renderHook(() => useColumnsModel("staff", "q=a", false), { wrapper: wrapperFor(client) });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("view form for a new view sends the address as its query", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { title: "Харагдац хадгалах", name: "", visibility: "shared", is_default: false, query: "q=a", can_delete: false, view_id: null }),
    );

    const { result } = renderHook(() => useViewForm({ key: "staff", query: "q=a&sort=-name" }, true), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/views/new");
    expect(urlOf(0).search).toBe("?q=a&sort=-name");
  });

  it("view form for an edit reads the view by its id, and sends nothing while closed", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { title: "Харагдац засах", name: "A", visibility: "private", is_default: false, query: "", can_delete: true, view_id: 4 }));

    const { result } = renderHook(() => useViewForm({ pk: 4 }, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/reports/views/4");

    const closed = renderHook(() => useViewForm({ pk: 9 }, false), { wrapper: wrapperFor(client) });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
    expect(closed.result.current.fetchStatus).toBe("idle");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("save view posts body and returns result", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true, redirect: "/reports/staff/?view=7", error: "", field_errors: {}, form_errors: [] }));
    const body: ReportViewIn = { name: "Миний", visibility: "shared", is_default: false, query: "q=a" };

    const { result } = renderHook(() => useSaveView(), { wrapper: wrapperFor(client) });
    let saved: unknown;
    await act(async () => {
      saved = await result.current.mutateAsync({ key: "staff", body });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/views");
    expect(JSON.parse(await request.text())).toEqual(body);
    expect(saved).toMatchObject({ ok: true, redirect: "/reports/staff/?view=7" });
  });

  it("update view posts to its pk path and a refused save answers ok false", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: false, redirect: "", error: "", field_errors: { name: ["Ийм нэртэй харагдац байна."] }, form_errors: [] }));
    const body: ReportViewIn = { name: "Дубль", visibility: "shared", is_default: true, query: "" };

    const { result } = renderHook(() => useUpdateView(3), { wrapper: wrapperFor(client) });
    let saved: unknown;
    await act(async () => {
      saved = await result.current.mutateAsync(body);
    });

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/views/3");
    expect(saved).toMatchObject({ ok: false, field_errors: { name: ["Ийм нэртэй харагдац байна."] } });
  });

  it("view write 404 is a typed error and a 404 on a view by id is not a 403", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(404, { field_errors: {}, form_errors: [] }));
    const { result } = renderHook(() => useViewForm({ pk: 11 }, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 404 });

    fetchMock.mockResolvedValueOnce(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));
    const { result: update } = renderHook(() => useUpdateView(11), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() =>
      update.current.mutateAsync({ name: "x", visibility: "shared", is_default: false, query: "" }),
    );
    expect(caught).toMatchObject({ status: 403 });
  });

  it("print query sends the address query verbatim, sel included, and is not refetched on focus", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { title: "Ажилтны жагсаалт" }));

    const { result } = renderHook(() => useReportPrint("staff", "?sel=abc.def&q=a%20b"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/print");
    expect(urlOf(0).search).toBe("?sel=abc.def&q=a%20b");
    expect(result.current.data).toEqual({ title: "Ажилтны жагсаалт" });

    focusManager.setFocused(false);
    focusManager.setFocused(true);
    onlineManager.setOnline(false);
    onlineManager.setOnline(true);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("postSelection reads the file name from Content-Disposition and sends the three fields as JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("xlsx-bytes", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="staff-selected-2026-11-27.xlsx"' },
      }),
    );

    const body = { query: "q=a&add=branch", ids: ["3", "11"], all: false };
    const file = await postSelection(client, "staff", "excel", body);

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/selected/excel");
    expect(JSON.parse(await request.text())).toEqual(body);
    expect(file.filename).toBe("staff-selected-2026-11-27.xlsx");
    expect(await file.blob.text()).toBe("xlsx-bytes");
  });

  it("postSelection falls back to the key's selected name when no Content-Disposition comes back", async () => {
    fetchMock.mockResolvedValueOnce(new Response("a,b", { status: 200 }));
    const excel = await postSelection(client, "staff", "excel", { query: "", ids: ["1"], all: false });
    expect(excel.filename).toBe("staff-selected.xlsx");

    fetchMock.mockResolvedValueOnce(new Response("a,b", { status: 200 }));
    const csv = await postSelection(client, "staff", "csv", { query: "", ids: ["1"], all: false });
    expect(csv.filename).toBe("staff-selected.csv");
    expect(urlOf(1).pathname).toBe("/api/v1/reports/staff/selected/csv");
  });

  it("postSelection reads an RFC 5987 file name", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("x", {
        status: 200,
        headers: { "Content-Disposition": "attachment; filename*=UTF-8''staff%20sel.csv" },
      }),
    );
    const file = await postSelection(client, "staff", "csv", { query: "", ids: ["1"], all: false });
    expect(file.filename).toBe("staff sel.csv");
  });

  it("a 400 refusal is thrown as ApiFailure with the first form error as its message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { field_errors: {}, form_errors: ["Сонгосон хүн алга."] }));

    const caught = await rejectionOf(() =>
      postSelection(client, "staff", "excel", { query: "", ids: [], all: false }),
    );
    expect(caught).toMatchObject({ status: 400, message: "Сонгосон хүн алга.", formErrors: ["Сонгосон хүн алга."] });
  });

  it("a 403 with no form error is thrown as ApiFailure with its status", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));

    const caught = await rejectionOf(() => copySelection(client, "staff", { query: "", ids: ["1"], all: false }));
    expect(caught).toMatchObject({ status: 403, code: "forbidden", message: "Татаж чадсангүй. Дахин оролдоно уу." });
  });

  it("a network failure is thrown with the exact network text", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const caught = await rejectionOf(() => printTicket(client, "staff", { query: "", ids: ["1"], all: false }));
    expect((caught as Error).message).toBe("Холбогдож чадсангүй. Дахин оролдоно уу.");
  });

  it("copySelection returns the text, count and dropped, and posts the three fields", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { text: "Бат\nДорж", count: 2, dropped: 1 }));

    const body = { query: "q=a", ids: ["1", "2", "9"], all: false };
    const copied = await copySelection(client, "staff", body);

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/selected/copy");
    expect(JSON.parse(await request.text())).toEqual(body);
    expect(copied).toEqual({ text: "Бат\nДорж", count: 2, dropped: 1 });
  });

  it("printTicket returns the ticket string and posts to the print route", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ticket: "t-123" }));

    const ticket = await printTicket(client, "staff", { query: "", ids: [], all: true });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/selected/print");
    expect(JSON.parse(await request.text())).toEqual({ query: "", ids: [], all: true });
    expect(ticket).toBe("t-123");
  });

  it("a selection POST refused for a stale CSRF token is sent once more with the fresh token", async () => {
    setCsrf("old-token");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh-token")))
      .mockResolvedValueOnce(jsonResponse(200, { text: "Бат", count: 1, dropped: 0 }));

    const copied = await copySelection(client, "staff", { query: "", ids: ["1"], all: false });

    expect(copied).toEqual({ text: "Бат", count: 1, dropped: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[0][0] as Request).headers.get("X-CSRFToken")).toBe("old-token");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh-token");
    expect(getCsrf()).toBe("fresh-token");
  });

  it("a file POST refused for a stale CSRF token takes its file name from the answer that succeeded", async () => {
    setCsrf("old-token");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh-token")))
      .mockResolvedValueOnce(
        new Response("xlsx-bytes", {
          status: 200,
          headers: { "Content-Disposition": 'attachment; filename="staff-selected-2026-11-27.xlsx"' },
        }),
      );

    const file = await postSelection(client, "staff", "excel", { query: "", ids: ["1"], all: false });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(file.filename).toBe("staff-selected-2026-11-27.xlsx");
    expect(await file.blob.text()).toBe("xlsx-bytes");
    expect(getCsrf()).toBe("fresh-token");
  });

  it("a second CSRF refusal is thrown with the Mongolian fallback when the body has no form error", async () => {
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh-token")))
      .mockResolvedValueOnce(jsonResponse(500, {}));

    const caught = await rejectionOf(() => printTicket(client, "staff", { query: "", ids: ["1"], all: false }));
    expect(caught).toMatchObject({ status: 500, message: "Татаж чадсангүй. Дахин оролдоно уу." });
  });

  it("fetchChecklistForm posts the address, the ids and the all flag only, to the checklist form route", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        all: false,
        anchor_max: "",
        anchor_min: "",
        count: 2,
        reasons: [{ label: "Ажлаас гарсан", value: "resigned" }],
        template_missing: false,
        today: "2026-11-27",
      }),
    );

    const body = { query: "q=a", ids: ["3", "11"], all: false, reason: "resigned" } as unknown as ReportSelectionIn;
    const form = await fetchChecklistForm(client, "staff", body);

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/selected/checklist/form");
    expect(JSON.parse(await request.text())).toEqual({ query: "q=a", ids: ["3", "11"], all: false });
    expect(form).toMatchObject({ count: 2, template_missing: false, today: "2026-11-27" });
  });

  it("fetchChecklistForm refusal is a 400 with the Mongolian first form error as its message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { field_errors: {}, form_errors: ["Сонгосон хүн алга."] }));

    const caught = await rejectionOf(() =>
      fetchChecklistForm(client, "staff", { query: "", ids: [], all: false }),
    );
    expect(caught).toMatchObject({ status: 400, message: "Сонгосон хүн алга.", formErrors: ["Сонгосон хүн алга."] });
  });

  it("fetchChecklistForm network failure is thrown with the exact network text", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const caught = await rejectionOf(() => fetchChecklistForm(client, "staff", { query: "", ids: ["1"], all: false }));
    expect((caught as Error).message).toBe("Холбогдож чадсангүй. Дахин оролдоно уу.");
  });

  it("startChecklists posts the reason and anchor day to the checklist route and returns the counts", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        counts: { started: 1, skipped: 1 },
        dropped: 0,
        rows: [
          { code: "101", name: "Бат", outcome: "started" },
          { code: "102", name: "Дорж", outcome: "skipped" },
        ],
      }),
    );

    const body: ReportChecklistStartIn = {
      query: "q=a",
      ids: ["1", "2"],
      all: false,
      reason: "resigned",
      anchor_day: "2026-11-30",
    };
    const result = await startChecklists(client, "staff", body);

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/selected/checklist");
    expect(JSON.parse(await request.text())).toEqual(body);
    expect(result.counts).toEqual({ started: 1, skipped: 1 });
    expect(result.rows).toHaveLength(2);
  });

  it("startChecklists refusal keeps every form error on the thrown error, the first one as its message", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(400, { field_errors: {}, form_errors: ["Шалтгаанаа сонгоно уу.", "Огноо буруу байна."] }),
    );

    const caught = await rejectionOf(() =>
      startChecklists(client, "staff", { query: "", ids: ["1"], all: false, reason: "", anchor_day: "" }),
    );
    expect(caught).toMatchObject({
      status: 400,
      message: "Шалтгаанаа сонгоно уу.",
      formErrors: ["Шалтгаанаа сонгоно уу.", "Огноо буруу байна."],
    });
  });
});
