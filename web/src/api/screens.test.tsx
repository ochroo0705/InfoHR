import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import { useDismissNotice, useMe, useTick, useWithdraw } from "./me";
import { useAttentionToggle, useAway, useHires, useToday, type TodayOut } from "./today";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), and it
// delegates to a mock that each test sets up. Relative URLs are resolved against the page, as in client.test.ts.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// The API's CSRF failure, as api/main.py answers it: a JSON 403 with code "csrf_failed".
function csrfFailure(): Response {
  return jsonResponse(403, {
    field_errors: {},
    form_errors: ["CSRF check Failed"],
    code: "csrf_failed",
  });
}

// Django's own CSRF failure page: a 403 with an HTML body.
function htmlCsrfFailure(): Response {
  return new Response("<html>CSRF verification failed</html>", {
    status: 403,
    headers: { "Content-Type": "text/html" },
  });
}

function metaBody(csrf: string) {
  return {
    backend_version: "dev",
    api_version: 1,
    company: { name: "", logo_url: null },
    modules: {},
    csrf,
    user: null,
  };
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

// Runs a mutation that is expected to fail and returns what it rejected with.
async function rejectionOf(run: () => Promise<unknown>): Promise<unknown> {
  let caught: unknown;
  await act(async () => {
    try {
      await run();
    } catch (error) {
      caught = error;
    }
  });
  return caught;
}

function urlOf(index: number): string {
  return (fetchMock.mock.calls[index][0] as Request).url;
}

describe("today and me hooks", () => {
  let client: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    setCsrf("");
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
  });

  it("useAway(null) makes no request", async () => {
    const { result } = renderHook(() => useAway(null), { wrapper: wrapperFor(client) });

    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("useAway(day) asks for that day in the query string", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { day: "2026-11-17", names: [] }));

    const { result } = renderHook(() => useAway("2026-11-17"), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(urlOf(0));
    expect(url.pathname).toBe("/api/v1/today/away");
    expect(url.searchParams.get("day")).toBe("2026-11-17");
  });

  it("a failed query throws an Error that carries the HTTP status", async () => {
    // 404 is used because it is not retried (useToday retries a 5xx up to three times with a delay).
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: [] }));

    const { result } = renderHook(() => useToday(), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error & { status?: number }).status).toBe(404);
  });

  it("useMe reads /api/v1/me", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { full_name: "Test" }));

    const { result } = renderHook(() => useMe(), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(new URL(urlOf(0)).pathname).toBe("/api/v1/me");
  });

  it("after useAttentionToggle resolves, the ['today'] cache box equals the answer's", async () => {
    setCsrf("tok");
    client.setQueryData(["today"], {
      today: "2026-11-17",
      box: { urgent_count: 1 },
    } as unknown as TodayOut);
    fetchMock.mockResolvedValue(jsonResponse(200, { box: { urgent_count: 5 } }));

    const { result } = renderHook(() => useAttentionToggle(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ action: "dismiss", keys: ["late"] });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual({ action: "dismiss", keys: ["late"] });
    expect(client.getQueryData<TodayOut>(["today"])?.box.urgent_count).toBe(5);
  });

  it("useAttentionToggle leaves the cache alone when no ['today'] data exists", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { box: { urgent_count: 5 } }));

    const { result } = renderHook(() => useAttentionToggle(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ action: "restore", keys: ["late"] });
    });

    expect(client.getQueryData(["today"])).toBeUndefined();
  });

  it("useWithdraw on 409 rejects with formErrors equal to the answer's form_errors", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(409, { field_errors: {}, form_errors: ["Батлагдсан хүсэлт"] }),
    );

    const { result } = renderHook(() => useWithdraw(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(7));

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error & { formErrors: string[] }).formErrors).toEqual(["Батлагдсан хүсэлт"]);
    expect((caught as Error & { status: number }).status).toBe(409);
    expect(urlOf(0)).toContain("/api/v1/me/requests/7/withdraw");
  });

  it("useDismissNotice invalidates ['me'] after success", async () => {
    setCsrf("tok");
    // Call order: the My page query, the dismissal, then the refetch that the invalidation triggers.
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { full_name: "Before" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse(200, { full_name: "After" }));

    const { result } = renderHook(() => ({ me: useMe(), dismiss: useDismissNotice() }), {
      wrapper: wrapperFor(client),
    });
    await waitFor(() => expect(result.current.me.isSuccess).toBe(true));
    await act(async () => {
      await result.current.dismiss.mutateAsync({ key: "n1" });
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(urlOf(1)).toContain("/api/v1/me/notice");
    expect(urlOf(2)).toContain("/api/v1/me");
    await waitFor(() => expect(client.getQueryData(["me"])).toEqual({ full_name: "After" }));
  });

  it("useTick invalidates ['me'] and ['today']", async () => {
    setCsrf("tok");
    client.setQueryData(["me"], { full_name: "Me" });
    client.setQueryData(["today"], { today: "2026-11-17" });
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["today"], exact: true });
    expect(urlOf(0)).toContain("/api/v1/checklists/tasks/3/tick");
  });

  it("retries once after a CSRF failure, refetching meta for a fresh token", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(urlOf(1)).toContain("/api/v1/meta");
    const retry = fetchMock.mock.calls[2][0] as Request;
    expect(retry.method).toBe("POST");
    expect(retry.headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("still retries Django's HTML CSRF page (a non-JSON 403)", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(htmlCsrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("does not retry a JSON 403 without the csrf_failed code", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValueOnce(
      jsonResponse(403, { field_errors: {}, form_errors: ["CSRF check Failed"] }),
    );

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(3));

    expect((caught as Error & { status: number }).status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects when the CSRF retry fails again", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(csrfFailure());

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(3));

    expect((caught as Error & { status: number }).status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry a 403 that carries the JSON error shape", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValueOnce(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"] }),
    );

    const { result } = renderHook(() => useWithdraw(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(7));

    expect((caught as Error & { formErrors: string[] }).formErrors).toEqual(["Эрх байхгүй"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("a failed meta refetch inside the CSRF retry rejects with status and formErrors []", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(500, { field_errors: {}, form_errors: [] }));

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync(3));

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error & { status: number }).status).toBe(500);
    expect((caught as Error & { formErrors: string[] }).formErrors).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a toggle does not refetch an open lazy list under ['today', ...]", async () => {
    setCsrf("tok");
    client.setQueryData(["today"], { today: "2026-11-17", box: { urgent_count: 1 } } as unknown as TodayOut);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, [{ full_name: "Bat" }]))
      .mockResolvedValueOnce(jsonResponse(200, { box: { urgent_count: 2 } }));

    const { result } = renderHook(
      () => ({ hires: useHires(true), toggle: useAttentionToggle() }),
      { wrapper: wrapperFor(client) },
    );
    await waitFor(() => expect(result.current.hires.isSuccess).toBe(true));
    await act(async () => {
      await result.current.toggle.mutateAsync({ action: "dismiss", keys: ["x"] });
    });

    // Only the hires GET and the toggle POST: the open hires list is not invalidated.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(urlOf(0)).toContain("/api/v1/today/hires");
    expect(client.getQueryData<TodayOut>(["today"])?.box.urgent_count).toBe(2);
  });
});
