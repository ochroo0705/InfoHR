import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCompany } from "./company";
import { useEmployee, useEmployeeActivity, useEmployeeSalary, useReportingLine } from "./employee";
import { openLegacyEmployee } from "../lib/AppLink";
import { isPorted } from "../lib/ported";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), and it
// delegates to a mock that each test sets up. Relative URLs are resolved against the page, as in screens.test.tsx.
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

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function urlOf(index: number): URL {
  return new URL((fetchMock.mock.calls[index][0] as Request).url);
}

function activityPage(nextOffset: number | null) {
  return { empty_label: "", entries: [], next_offset: nextOffset, prev_day: "" };
}

describe("employee and company routes", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "http://dj");
    Object.defineProperty(window, "location", {
      value: { href: "" },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
  });

  it("treats an employee page, the company page and the order register as ported, and a Django-only page as not", () => {
    expect(isPorted("/employees/12/")).toBe(true);
    expect(isPorted("/employees/company/")).toBe(true);
    expect(isPorted("/employees/orders/")).toBe(true);
    expect(isPorted("/reports/orders/excel/")).toBe(false);
  });

  it("openLegacyEmployee sends a full page load to the Django employee page", () => {
    openLegacyEmployee(7);
    expect(window.location.href).toBe("http://dj/employees/7/");
  });
});

describe("employee hooks", () => {
  let client: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("useEmployee reads /api/v1/employees/{pk}", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { pk: 5 }));

    const { result } = renderHook(() => useEmployee(5), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5");
  });

  it("useEmployeeSalary(5, false) makes no request", async () => {
    const { result } = renderHook(() => useEmployeeSalary(5, false), { wrapper: wrapperFor(client) });

    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("useEmployeeActivity asks for offset=50 on fetchNextPage", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, activityPage(50)))
      .mockResolvedValueOnce(jsonResponse(200, activityPage(null)));

    // data and hasNextPage are read during render: React Query re-renders only for the fields a hook reads.
    const { result } = renderHook(
      () => {
        const query = useEmployeeActivity(5);
        return { query, pages: query.data?.pages, hasNextPage: query.hasNextPage };
      },
      { wrapper: wrapperFor(client) },
    );

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/activity");
    expect(urlOf(0).searchParams.get("offset")).toBe("0");

    await act(async () => {
      await result.current.query.fetchNextPage();
    });

    expect(urlOf(1).pathname).toBe("/api/v1/employees/5/activity");
    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    await waitFor(() => expect(result.current.pages).toHaveLength(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useCompany reads /api/v1/company", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { title: "" }));

    const { result } = renderHook(() => useCompany(), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/company");
  });
});

describe("reporting line hook", () => {
  let client: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("useReportingLine with an empty day asks for today's line with no day parameter", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { employee: {}, levels: [] }));

    const { result } = renderHook(() => useReportingLine(5, ""), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/reporting-line");
    expect(urlOf(0).searchParams.has("day")).toBe(false);
  });

  it("useReportingLine with a day asks for that day", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { employee: {}, levels: [] }));

    const { result } = renderHook(() => useReportingLine(5, "2026-03-01"), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/reporting-line");
    expect(urlOf(0).searchParams.get("day")).toBe("2026-03-01");
  });

  it("useReportingLine surfaces a 404 as the query error", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { code: "not_found" }));

    const { result } = renderHook(() => useReportingLine(5, ""), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as { status?: number }).status).toBe(404);
  });
});
