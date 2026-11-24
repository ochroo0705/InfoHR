import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { LeaveSettingsOut, LeaveTypeOut } from "../../api/leaveSetup";
import { LeaveSettingsPage } from "./LeaveSettingsPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const TYPE: LeaveTypeOut = {
  id: 7,
  name: "Жилийн амралт",
  is_paid: true,
  uses_annual_balance: true,
  is_active: true,
  order: 0,
  staff_may_request: true,
};

const SETTINGS: LeaveSettingsOut = {
  approval: { step1: "manager", step2: "" },
  auto_annual_grant: true,
  step1_choices: [
    { value: "", label: "Батлахгүй" },
    { value: "manager", label: "Шууд удирдлага" },
  ],
  step2_choices: [{ value: "", label: "—" }],
  types: [TYPE],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LeaveSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LeaveSettingsPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/leave/settings") return ok(SETTINGS);
      if (path === "/api/v1/leave/settings/types/{pk}") return ok(TYPE);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
  });

  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("shows the title, the holidays link, the add button, the types table and the two forms", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Чөлөөний тохиргоо" })).toBeTruthy();
    const link = screen.getByRole("link", { name: "Баярын өдрүүд" });
    expect(link.getAttribute("href")).toBe("/leave/holidays/");
    expect(screen.getByRole("button", { name: "Төрөл нэмэх" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Чөлөөний төрөл" })).toBeTruthy();
    expect(screen.getByText("Жилийн амралт")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Чөлөөний хүсэлтийг хэн батлах вэ" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ээлжийн амралтын эрхийг автоматаар нэмэх" })).toBeTruthy();
  });

  it("sets the page title with the product name", async () => {
    renderPage();

    await screen.findByRole("heading", { level: 1, name: "Чөлөөний тохиргоо" });
    expect(document.title).toBe("Чөлөөний тохиргоо · MACS Human Capital");
  });

  it("a row opens the type's pop-up in edit mode with its loaded values", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("Жилийн амралт"));

    // The loading shell has the same title, so wait for the form's own «Болих» button.
    await screen.findByRole("button", { name: "Болих" });
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Чөлөөний төрөл засах" })).toBeTruthy();
    expect((within(dialog).getByRole("textbox", { name: /Нэр/ }) as HTMLInputElement).value).toBe("Жилийн амралт");
    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/settings/types/{pk}", { params: { path: { pk: 7 } } });
  });

  it("Төрөл нэмэх opens the pop-up in add mode", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Төрөл нэмэх" }));

    expect(await screen.findByRole("heading", { name: "Чөлөөний төрөл нэмэх" })).toBeTruthy();
    expect(h.get).not.toHaveBeenCalledWith("/api/v1/leave/settings/types/{pk}", expect.anything());
  });

  it("closing the pop-up with its ✕ removes it", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Төрөл нэмэх" }));
    await screen.findByRole("heading", { name: "Чөлөөний төрөл нэмэх" });

    fireEvent.click(screen.getByRole("button", { name: "Хаах" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
