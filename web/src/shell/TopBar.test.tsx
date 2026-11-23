import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router";
import { api } from "../api/client";
import { TopBar } from "./TopBar";
import { AssistantPanel } from "./palette/AssistantPanel";
import { PalettePanelProvider } from "./palette/PalettePanelContext";
import { PalettePopupsContext } from "./palette/PalettePopups";

vi.mock("../api/client", () => ({
  api: { GET: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

// jsdom has no scrollIntoView. Keep whatever was there before the file and put it back after each test.
const originalScrollIntoView = Element.prototype.scrollIntoView;

const META = {
  backend_version: "dev",
  api_version: 1,
  company: { name: "", logo_url: null },
  modules: {},
  csrf: "token",
  user: null,
};

const SINGLE = {
  key: "employees",
  label: "Ажилтан",
  active: true,
  badge: 3,
  items: [
    {
      label: "Ажилтан",
      url: "/employees/",
      active: true,
      badge: 3,
      icon: "people",
      hint: "",
      compact: false,
      section: "",
    },
  ],
};

const MENU = {
  key: "settings",
  label: "Тохиргоо",
  active: false,
  badge: 0,
  items: [
    { label: "Хэрэглэгч", url: "/users/", active: false, badge: 0, icon: "user", hint: "", compact: false, section: "" },
    { label: "Албан тушаал", url: "/slots/", active: false, badge: 0, icon: "list", hint: "", compact: true, section: "" },
    { label: "Тайлан", url: "/reports/", active: false, badge: 0, icon: "chart", hint: "", compact: true, section: "" },
  ],
};

// A signed-in answer: the user menu renders only when there is a user.
const SIGNED_IN = {
  ...META,
  user: { id: 1, username: "bat", first_name: "", full_name: "", must_change_password: false, perms: [], own_record: false },
};

// The nav groups for the page at `path`; the meta answer is the same for every page.
function mockApi(groupsFor: (path: string) => unknown[], meta: unknown = META) {
  vi.mocked(api.GET).mockImplementation((async (url: string, init?: { params?: { query?: { path?: string } } }) => {
    if (url === "/api/v1/meta") return { data: meta, response: { status: 200 } };
    // The assistant panel's search answers with an empty list; the nav answers with the groups.
    if (url === "/api/v1/palette") {
      return {
        data: { empty: false, empty_text: "", fallback: [], fallback_heading: "", groups: [] },
        response: { status: 200, ok: true },
      };
    }
    return { data: groupsFor(init?.params?.query?.path ?? ""), response: { status: 200 } };
  }) as never);
}

function wrap(children: ReactNode, path = "/employees/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <PalettePanelProvider>
          <PalettePopupsContext.Provider value={{ open: () => {} }}>{children}</PalettePopupsContext.Provider>
        </PalettePanelProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderBar(groups: unknown[]) {
  mockApi(() => groups);
  return render(wrap(<TopBar />));
}

function GoTo({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(to)}>
      Өөр хуудас
    </button>
  );
}

describe("TopBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
    if (originalScrollIntoView) Element.prototype.scrollIntoView = originalScrollIntoView;
    else delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("TopBar button opens the panel, and a second press closes it", async () => {
    mockApi(() => [SINGLE], SIGNED_IN);
    const { container } = render(
      wrap(
        <>
          <TopBar />
          <AssistantPanel />
        </>,
      ),
    );
    const aside = container.querySelector<HTMLElement>("[data-assistant-panel]");
    expect(aside?.hidden).toBe(true);
    await screen.findByRole("button", { name: "Хайх" });
    await waitFor(() => expect(container.querySelector('[data-nav-trigger="ui:user"]')).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хайх" }));
    expect(aside?.hidden).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Хайх" }));
    expect(aside?.getAttribute("data-leaving")).not.toBeNull();
  });

  it("renders the brand text", async () => {
    renderBar([SINGLE, MENU]);
    expect(screen.getByText("Human Capital")).toBeTruthy();
    expect(await screen.findByText("3")).toBeTruthy();
  });

  it("sends a nav item for a Django-only page to a full load into Django (legacy origin prefixed)", async () => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "http://dj");
    try {
      renderBar([SINGLE, MENU]);
      const link = await screen.findByRole("link", { name: /Ажилтан/ });
      expect(link.getAttribute("href")).toBe("http://dj/employees/");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("renders a single-item group as a link with aria-current when it is the active one", async () => {
    renderBar([SINGLE, MENU]);
    const link = await screen.findByRole("link", { name: /Ажилтан/ });
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("/employees/");
    expect(link.getAttribute("aria-current")).toBe("page");
  });

  it("shows the badge number on the single link", async () => {
    renderBar([SINGLE]);
    expect(await screen.findByText("3")).toBeTruthy();
  });

  it("renders a group with several items as a drop-down menu button", async () => {
    renderBar([SINGLE, MENU]);
    expect(await screen.findByRole("button", { name: /Тохиргоо/ })).toBeTruthy();
  });

  it("scrolls the active item into view on mount", async () => {
    renderBar([SINGLE, MENU]);
    await screen.findByRole("link", { name: /Ажилтан/ });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ inline: "nearest", block: "nearest" });
  });

  it("scrolls the active item into view again after each navigation", async () => {
    const USERS = {
      key: "users",
      label: "Хэрэглэгч",
      active: true,
      badge: 0,
      items: [
        { label: "Хэрэглэгч", url: "/users/", active: true, badge: 0, icon: "user", hint: "", compact: false, section: "" },
      ],
    };
    mockApi((path) => (path === "/users/" ? [USERS] : [SINGLE]));
    render(
      wrap(
        <>
          <TopBar />
          <GoTo to="/users/" />
        </>,
      ),
    );
    await screen.findByRole("link", { name: /Ажилтан/ });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Өөр хуудас" }));

    await screen.findByRole("link", { name: /Хэрэглэгч/ });
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(2));
  });

  it("still renders the brand and the theme and user menus when there are no groups", async () => {
    mockApi(() => [], SIGNED_IN);
    const { container } = render(wrap(<TopBar />));
    expect(screen.getByText("Human Capital")).toBeTruthy();
    await screen.findByRole("button", { name: "Хайх" });
    expect(container.querySelector('[data-nav-trigger="ui:theme"]')).not.toBeNull();
    await waitFor(() => expect(container.querySelector('[data-nav-trigger="ui:user"]')).not.toBeNull());
  });

  it("makes the theme and user menu roots direct flex items of the nav, as base.html does", async () => {
    mockApi(() => [SINGLE], SIGNED_IN);
    const { container } = render(wrap(<TopBar />));
    await screen.findByRole("link", { name: /Ажилтан/ });
    await waitFor(() => expect(container.querySelector('[data-nav-trigger="ui:user"]')).not.toBeNull());
    const nav = container.querySelector("header nav");
    expect(nav).not.toBeNull();
    for (const id of ["ui:theme", "ui:user"]) {
      const root = container.querySelector(`[data-nav-trigger="${id}"]`)?.parentElement;
      expect(root?.hasAttribute("data-nav-menu")).toBe(true);
      expect(root?.parentElement).toBe(nav);
    }
  });

  it("makes no nav request for a user who must change the password", async () => {
    const FORCED = { ...META, user: { ...SIGNED_IN.user, must_change_password: true } };
    mockApi(() => [SINGLE], FORCED);
    const { container } = render(wrap(<TopBar />));
    // The user menu renders from the meta answer, so its appearance shows that meta has resolved.
    await waitFor(() => expect(container.querySelector('[data-nav-trigger="ui:user"]')).not.toBeNull());
    const urls = vi.mocked(api.GET).mock.calls.map((call) => call[0]);
    expect(urls).toContain("/api/v1/meta");
    expect(urls).not.toContain("/api/v1/nav");
  });
});
