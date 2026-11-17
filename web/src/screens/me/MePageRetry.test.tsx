import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { retryMe } from "../../api/me";
import { MePage } from "./MePage";

// The real useMe runs here (no hook mock): only the HTTP client is replaced.
vi.mock("../../api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

describe("retryMe", () => {
  it("does not retry 401, 403 or 404", () => {
    for (const status of [401, 403, 404]) {
      expect(retryMe(1, Object.assign(new Error("x"), { status }))).toBe(false);
    }
  });

  it("retries other failures up to three times", () => {
    expect(retryMe(1, Object.assign(new Error("x"), { status: 500 }))).toBe(true);
    expect(retryMe(2, new Error("network"))).toBe(true);
    expect(retryMe(3, new Error("network"))).toBe(false);
  });
});

describe("MePage with a 404 from /me", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows NotFound at once, without waiting for retries", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: {},
      response: new Response(null, { status: 404 }),
    } as never);
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <MePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // Default retries would wait over a second before the error shows; 500 ms is enough only without retries.
    await waitFor(() => expect(screen.getByText("Хуудас олдсонгүй")).toBeTruthy(), { timeout: 500 });
    expect(vi.mocked(api.GET)).toHaveBeenCalledTimes(1);
  });
});
