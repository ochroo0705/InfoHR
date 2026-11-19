// Shared harness for the api module tests: the fetch and Request stubs, JSON answers, the query-client wrapper and query
// observers. A test file must import this module BEFORE any api module (./client captures fetch when it loads), so the
// stubs below are in place first; ES imports run in source order, so keep this import at the top of each test file.
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { vi } from "vitest";

export const fetchMock = vi.fn();

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

// A query client that never retries, for the mutation and query tests.
export function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// The API's CSRF failure, as api/main.py answers it: a JSON 403 with code "csrf_failed".
export function csrfFailure(): Response {
  return jsonResponse(403, { field_errors: {}, form_errors: ["CSRF check Failed"], code: "csrf_failed" });
}

export function metaBody(csrf: string) {
  return {
    backend_version: "dev",
    api_version: 1,
    company: { name: "", logo_url: null },
    modules: {},
    csrf,
    user: null,
  };
}

export function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

// Runs a call that is expected to fail and returns what it rejected with.
export async function rejectionOf(run: () => Promise<unknown>): Promise<unknown> {
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

// Observers that keep a query active, so an invalidation refetches it. resetHarness() unsubscribes them all.
const unsubscribes: (() => void)[] = [];

export function observe(client: QueryClient, queryKey: unknown[]) {
  const queryFn = vi.fn(async () => ({ at: Date.now() }));
  const observer = new QueryObserver(client, { queryKey, queryFn });
  unsubscribes.push(observer.subscribe(() => undefined));
  return queryFn;
}

// The URL of the request sent at call `index` of fetchMock.
export function urlOf(index: number): URL {
  return new URL((fetchMock.mock.calls[index][0] as Request).url);
}

// The invalidations a spy saw, as the filter objects it was called with.
export function invalidatedKeys(spy: { mock: { calls: unknown[][] } }) {
  return spy.mock.calls.map((call) => call[0] as { queryKey: unknown[]; exact?: boolean });
}

// Per-test reset: an empty fetch mock and no observers left over. Call it from beforeEach (fetch) and afterEach (observers).
export function resetFetch() {
  fetchMock.mockReset();
}

export function resetObservers() {
  while (unsubscribes.length > 0) unsubscribes.pop()?.();
}
