import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { api, redirectToLogin } from "../api/client";
import { RequireAuth } from "./RequireAuth";

vi.mock("../api/client", () => ({
  api: { GET: vi.fn() },
  setCsrf: vi.fn(),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const USER = {
  id: 1,
  username: "bat",
  full_name: "Бат Эрдэнэ",
  must_change_password: false,
  perms: [],
  own_record: false,
};

function metaWith(user: unknown) {
  return {
    data: {
      backend_version: "dev",
      api_version: 1,
      company: { name: "", logo_url: null },
      modules: {},
      csrf: "tok",
      user,
    },
    response: { status: 200 },
  };
}

function renderGuarded(allowForced = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <RequireAuth allowForced={allowForced}>
                <p>ГОЛ АГУУЛГА</p>
              </RequireAuth>
            }
          />
          <Route path="/password/change" element={<p>НУУЦ ҮГ СОЛИХ</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RequireAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("redirects an anonymous visitor to login exactly once", async () => {
    vi.mocked(api.GET).mockResolvedValue(metaWith(null) as never);

    renderGuarded();

    await waitFor(() => expect(redirectToLogin).toHaveBeenCalled());
    expect(redirectToLogin).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("ГОЛ АГУУЛГА")).toBeNull();
  });

  it("sends a user who must change the password to /password/change", async () => {
    vi.mocked(api.GET).mockResolvedValue(
      metaWith({ ...USER, must_change_password: true }) as never,
    );

    renderGuarded();

    expect(await screen.findByText("НУУЦ ҮГ СОЛИХ")).toBeTruthy();
    expect(screen.queryByText("ГОЛ АГУУЛГА")).toBeNull();
    expect(redirectToLogin).not.toHaveBeenCalled();
  });

  it("renders the children for a forced user when allowForced is set (the password change page)", async () => {
    vi.mocked(api.GET).mockResolvedValue(
      metaWith({ ...USER, must_change_password: true }) as never,
    );

    renderGuarded(true);

    expect(await screen.findByText("ГОЛ АГУУЛГА")).toBeTruthy();
    expect(screen.queryByText("НУУЦ ҮГ СОЛИХ")).toBeNull();
    expect(redirectToLogin).not.toHaveBeenCalled();
  });

  it("renders the children for a signed-in user", async () => {
    vi.mocked(api.GET).mockResolvedValue(metaWith(USER) as never);

    renderGuarded();

    expect(await screen.findByText("ГОЛ АГУУЛГА")).toBeTruthy();
    expect(redirectToLogin).not.toHaveBeenCalled();
  });

  it("shows the server-unreachable line when the meta request has no answer (network failure)", async () => {
    vi.mocked(api.GET).mockRejectedValue(new TypeError("Failed to fetch"));

    renderGuarded();

    expect(
      await screen.findByText("Компанийн сервертэй холбогдож чадсангүй. Дахин оролдож байна…"),
    ).toBeTruthy();
    expect(screen.queryByText("ГОЛ АГУУЛГА")).toBeNull();
    expect(redirectToLogin).not.toHaveBeenCalled();
  });

  it("shows the server-unreachable line when the meta request fails with a 5xx status", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: { status: 503 },
    } as never);

    renderGuarded();

    expect(
      await screen.findByText("Компанийн сервертэй холбогдож чадсангүй. Дахин оролдож байна…"),
    ).toBeTruthy();
    expect(screen.queryByText("ГОЛ АГУУЛГА")).toBeNull();
  });

  it("keeps the children when a background refetch of meta fails without a status", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(api.GET).mockResolvedValueOnce(metaWith(USER) as never);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route
              path="/"
              element={
                <RequireAuth>
                  <p>ГОЛ АГУУЛГА</p>
                </RequireAuth>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("ГОЛ АГУУЛГА")).toBeTruthy();

    vi.mocked(api.GET).mockRejectedValue(new TypeError("Failed to fetch"));
    await client.invalidateQueries({ queryKey: ["meta"] });

    await waitFor(() => expect(client.getQueryState(["meta"])?.status).toBe("error"));
    expect(screen.getByText("ГОЛ АГУУЛГА")).toBeTruthy();
    expect(
      screen.queryByText("Компанийн сервертэй холбогдож чадсангүй. Дахин оролдож байна…"),
    ).toBeNull();
  });
});
