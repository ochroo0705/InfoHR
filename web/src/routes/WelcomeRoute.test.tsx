// testSupport must be imported first: it stubs fetch before ../api/client captures it.
import { fetchMock, jsonResponse, metaBody, newClient, resetFetch } from "../api/testSupport";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { WelcomeRoute } from "./WelcomeRoute";

function renderWith(client: QueryClient, path = "/welcome") {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/welcome" element={<WelcomeRoute />} />
          <Route path="/" element={<p>HOME PAGE</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderAt(path = "/welcome") {
  return renderWith(newClient(), path);
}

function metaWithWelcome(enabled: boolean) {
  return { ...metaBody("tok"), welcome_enabled: enabled };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("WelcomeRoute", () => {
  beforeEach(() => {
    resetFetch();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders nothing while the meta request is still loading, and does not redirect late", async () => {
    fetchMock.mockReturnValue(new Promise(() => undefined));
    renderAt();
    await tick();

    expect(screen.queryByTestId("welcome-page")).toBeNull();
    expect(screen.queryByText("HOME PAGE")).toBeNull();
  });

  it("renders the welcome page when welcome_enabled is true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, metaWithWelcome(true)));
    renderAt();

    expect(await screen.findByTestId("welcome-page")).toBeTruthy();
    expect(screen.queryByText("HOME PAGE")).toBeNull();
  });

  it("redirects to / when welcome_enabled is false", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, metaWithWelcome(false)));
    renderAt();

    expect(await screen.findByText("HOME PAGE")).toBeTruthy();
    expect(screen.queryByTestId("welcome-page")).toBeNull();
  });

  it("redirects to / when the meta request returns HTTP 500, instead of rendering a blank page", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    renderAt();

    await waitFor(() => expect(screen.getByText("HOME PAGE")).toBeTruthy());
    expect(screen.queryByTestId("welcome-page")).toBeNull();
  });

  it("redirects to / when the meta request rejects (network error)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderAt();

    await waitFor(() => expect(screen.getByText("HOME PAGE")).toBeTruthy());
    expect(screen.queryByTestId("welcome-page")).toBeNull();
  });

  it("redirects at once with the production default retry (no ~7 s wait for retries)", async () => {
    // main.tsx builds a plain new QueryClient(), whose default retry is 3 with backoff. The route must not depend on it.
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    renderWith(new QueryClient());

    await waitFor(() => expect(screen.getByText("HOME PAGE")).toBeTruthy());
    expect(screen.queryByTestId("welcome-page")).toBeNull();
  });
});
