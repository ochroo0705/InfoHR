import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { TodayOut } from "../../api/today";
import { PalettePanelContext, type PalettePanelApi } from "../../shell/palette/PalettePanelContext";
import { TodayHeader } from "./TodayHeader";

// The API client is replaced by a stub that answers by path: the add pop-up loads its options through it.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const LEAVE_OPTIONS = {
  assisted: null,
  employees: [{ value: 3, label: "Ажилтан Нэг" }],
  initial: { employee: null, end_date: "", leave_type: null, start_date: "" },
  not_configured: "",
  types: [{ value: 2, label: "Ээлжийн амралт" }],
};

const DATA = {
  has_own_page: false,
  shortcuts: { add_employee: false, orders: false, record_leave: true },
  today: "2026-11-17",
} as unknown as TodayOut;

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const panel = { toggle: vi.fn() } as unknown as PalettePanelApi;
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/employees/today/"]}>
        <PalettePanelContext.Provider value={panel}>
          <TodayHeader data={DATA} />
        </PalettePanelContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TodayHeader", () => {
  beforeEach(() => {
    h.get.mockImplementation(async () => ({
      data: LEAVE_OPTIONS,
      error: undefined,
      response: { ok: true, status: 200 },
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("«Чөлөө бүртгэх» opens the leave add pop-up on the page, with nobody preselected", async () => {
    renderHeader();
    expect(screen.queryByRole("heading", { name: "Чөлөө бүртгэх" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Чөлөө бүртгэх" }));
    expect(await screen.findByRole("heading", { name: "Чөлөө бүртгэх" })).toBeTruthy();
    await waitFor(() => expect(h.get).toHaveBeenCalledWith("/api/v1/leave/options", { params: { query: {} } }));
    expect(h.get).not.toHaveBeenCalledWith("/api/v1/leave/requests/options");
  });
});
