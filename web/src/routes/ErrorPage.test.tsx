import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import App from "../App";
import { Forbidden } from "./ErrorPage";

// Signed in: the meta answer carries a user, so RequireAuth lets the shell render. The nav has no groups.
vi.mock("../api/client", () => ({
  api: {
    GET: vi.fn(async (url: string) => {
      if (url === "/api/v1/meta") {
        return {
          data: {
            backend_version: "dev",
            api_version: 1,
            company: { name: "", logo_url: null },
            modules: {},
            csrf: "tok",
            user: {
              id: 1,
              username: "bat",
              first_name: "",
              full_name: "Бат",
              must_change_password: false,
              perms: [],
              own_record: false,
            },
          },
          response: { status: 200 },
        };
      }
      return { data: [], response: { status: 200 } };
    }),
  },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

afterEach(() => {
  cleanup();
});

describe("error pages", () => {
  it("shows the 404 text and a home link for an unknown path, inside the shell", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/no-such-page"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Хуудас олдсонгүй" })).toBeTruthy();
    expect(screen.getByText("404")).toBeTruthy();
    expect(screen.getByText("Хаяг буруу байна эсвэл хуудас өөр газар шилжсэн байж магадгүй.")).toBeTruthy();
    const home = screen.getByRole("link", { name: "Нүүр хуудас руу буцах" });
    expect(home.getAttribute("href")).toBe("/");
    // The shell is there: the brand link is in the top bar.
    expect(screen.getByRole("link", { name: /MACS/ })).toBeTruthy();
  });

  it("shows the 403 text and a home link", () => {
    render(
      <MemoryRouter>
        <Forbidden />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Хандах эрх байхгүй" })).toBeTruthy();
    expect(screen.getByText("403")).toBeTruthy();
    expect(
      screen.getByText("Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу."),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Нүүр хуудас руу буцах" }).getAttribute("href")).toBe("/");
  });
});
