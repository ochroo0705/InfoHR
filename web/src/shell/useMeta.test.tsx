import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, getCsrf } from "../api/client";
import { useMeta } from "./useMeta";

// A small stand-in for client.ts's CSRF slot, so the test can read back what setCsrf stored.
vi.mock("../api/client", () => {
  let token = "";
  return {
    api: { GET: vi.fn() },
    setCsrf: vi.fn((next: string) => {
      token = next;
    }),
    getCsrf: vi.fn(() => token),
    redirectToLogin: vi.fn(),
    nav: { assign: vi.fn() },
  };
});

function metaBody(user: unknown) {
  return {
    backend_version: "dev",
    api_version: 1,
    company: { name: "", logo_url: null },
    modules: {},
    csrf: "tok-42",
    user,
  };
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useMeta", () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    cleanup();
  });

  it("fetches /api/v1/meta once and stores the csrf token before data reaches a consumer", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: metaBody(null),
      response: { status: 200 },
    } as never);

    // The consumer reads getCsrf() during its first render, and it only renders once data exists.
    function Consumer() {
      return <p>csrf:{getCsrf()}</p>;
    }
    function Gate() {
      const { data } = useMeta();
      return data ? <Consumer /> : null;
    }

    render(<Gate />, { wrapper: wrapperFor(client) });

    expect(await screen.findByText("csrf:tok-42")).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/meta");
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("throws an error that carries the HTTP status when the request fails", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      error: { form_errors: ["down"] },
      response: { status: 503 },
    } as never);

    const { result } = renderHook(() => useMeta(), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error & { status?: number }).status).toBe(503);
  });
});
