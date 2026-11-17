import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, nav } from "../api/client";
import { NavMenuProvider } from "./NavMenu";
import { UserMenu } from "./UserMenu";

vi.mock("../api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

function metaWith(ownRecord: boolean, firstName = "Эрдэнэ") {
  return {
    backend_version: "dev",
    api_version: 1,
    company: { name: "", logo_url: null },
    modules: {},
    csrf: "token",
    user: {
      id: 7,
      username: "bat",
      first_name: firstName,
      full_name: "Бат Эрдэнэ",
      must_change_password: false,
      perms: [],
      own_record: ownRecord,
    },
  };
}

function renderUserMenu(ownRecord: boolean, firstName = "Эрдэнэ") {
  vi.mocked(api.GET).mockResolvedValue({ data: metaWith(ownRecord, firstName), response: { status: 200 } } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <NavMenuProvider stripRef={createRef<HTMLElement>()}>
          <UserMenu />
        </NavMenuProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openMenu() {
  fireEvent.click(await screen.findByRole("button", { name: "Бат Эрдэнэ" }));
}

describe("UserMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // A plain browser without a hover mouse: the menu opens on click.
    window.matchMedia = (() => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  });

  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("hides «Миний хуудас» when the user has no own record", async () => {
    renderUserMenu(false);
    await openMenu();
    expect(screen.getByText("Нууц үг солих")).toBeTruthy();
    expect(screen.queryByText("Миний хуудас")).toBeNull();
  });

  it("shows «Миний хуудас» when the user has an own record", async () => {
    renderUserMenu(true);
    await openMenu();
    expect(screen.getByRole("link", { name: /Миний хуудас/ }).getAttribute("href")).toBe("/me/");
  });

  it("Гарах posts the logout, then clears this user's assistant thread, then goes to /login", async () => {
    sessionStorage.setItem("assistant-thread-7", "[]");
    const order: string[] = [];
    vi.mocked(api.POST).mockImplementation((async () => {
      order.push("post");
      return { response: { status: 204, ok: true }, data: undefined };
    }) as never);
    vi.mocked(nav.assign).mockImplementation(() => {
      order.push(sessionStorage.getItem("assistant-thread-7") === null ? "assign:cleared" : "assign:kept");
    });

    renderUserMenu(false);
    await openMenu();
    fireEvent.click(screen.getByRole("button", { name: /Гарах/ }));

    await waitFor(() => expect(nav.assign).toHaveBeenCalledWith("/login"));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/auth/logout");
    expect(order).toEqual(["post", "assign:cleared"]);
  });
  it("opens on hover, like the nav menus", async () => {
    window.matchMedia = ((query: string) => ({
      matches: query.includes("hover"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    renderUserMenu(false);
    const trigger = await screen.findByRole("button", { name: "Бат Эрдэнэ" });
    expect(screen.queryByText("Нууц үг солих")).toBeNull();

    fireEvent.mouseEnter(trigger.parentElement as HTMLElement);

    expect(await screen.findByText("Нууц үг солих")).toBeTruthy();
  });

  it("links «Нууц үг солих» to the React route /password/change", async () => {
    renderUserMenu(false);
    await openMenu();
    expect(screen.getByRole("link", { name: /Нууц үг солих/ }).getAttribute("href")).toBe("/password/change");
  });

  it("shows the first letter of the first name, upper case", async () => {
    renderUserMenu(false, "эрдэнэ");
    await screen.findByRole("button", { name: "Бат Эрдэнэ" });
    expect(screen.getByText("Э")).toBeTruthy();
  });

  it("falls back to the first letter of the username when there is no first name", async () => {
    renderUserMenu(false, "");
    await screen.findByRole("button", { name: "Бат Эрдэнэ" });
    expect(screen.getByText("B")).toBeTruthy();
  });

  it("stays on the page and keeps the thread when the logout answer is an HTTP error", async () => {
    sessionStorage.setItem("assistant-thread-7", "[]");
    vi.mocked(api.POST).mockResolvedValue({ error: {}, response: { ok: false, status: 403 } } as never);

    renderUserMenu(false);
    await openMenu();
    fireEvent.click(screen.getByRole("button", { name: /Гарах/ }));

    expect(await screen.findByText("Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.")).toBeTruthy();
    expect(nav.assign).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("assistant-thread-7")).toBe("[]");
  });

  it("stays on the page when the logout request throws", async () => {
    vi.mocked(api.POST).mockRejectedValue(new TypeError("Failed to fetch"));

    renderUserMenu(false);
    await openMenu();
    fireEvent.click(screen.getByRole("button", { name: /Гарах/ }));

    expect(await screen.findByText("Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.")).toBeTruthy();
    expect(nav.assign).not.toHaveBeenCalled();
  });
});
