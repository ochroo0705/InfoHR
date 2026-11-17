import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { api } from "../api/client";
import PasswordChangePage from "./PasswordChangePage";

vi.mock("../api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const NEW_PASSWORD = "Abcdefg1";

function metaWith(mustChange: boolean) {
  return {
    data: {
      backend_version: "dev",
      api_version: 1,
      company: { name: "", logo_url: null },
      modules: {},
      csrf: "tok",
      user: {
        id: 7,
        username: "bat",
        first_name: "Эрдэнэ",
        full_name: "Бат Эрдэнэ",
        must_change_password: mustChange,
        perms: [],
        own_record: false,
      },
    },
    response: { status: 200 },
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/password/change"]}>
        <Routes>
          <Route path="/password/change" element={<PasswordChangePage />} />
          <Route path="/" element={<p>НҮҮР ХУУДАС</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fill(container: HTMLElement, values: Record<string, string>) {
  for (const [name, value] of Object.entries(values)) {
    const input = container.querySelector(`input[name="${name}"]`) as HTMLInputElement;
    fireEvent.change(input, { target: { value } });
  }
}

describe("PasswordChangePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows no old-password field for a forced user, and the forced hint", async () => {
    vi.mocked(api.GET).mockResolvedValue(metaWith(true) as never);

    const { container } = renderPage();

    expect(await screen.findByRole("button", { name: "Хадгалах" })).toBeTruthy();
    expect(container.querySelector('input[name="old_password"]')).toBeNull();
    expect(container.querySelector('input[name="new_password1"]')).not.toBeNull();
    expect(screen.getByText("Түр нууц үгээ өөрийн шинэ нууц үгээр солино уу.")).toBeTruthy();
  });

  it("shows the old-password field for a user who changes a normal password", async () => {
    vi.mocked(api.GET).mockResolvedValue(metaWith(false) as never);

    const { container } = renderPage();

    await screen.findByRole("button", { name: "Хадгалах" });
    expect(container.querySelector('input[name="old_password"]')).not.toBeNull();
    expect(screen.queryByText("Түр нууц үгээ өөрийн шинэ нууц үгээр солино уу.")).toBeNull();
  });

  it("shows a 400 field error under its field", async () => {
    vi.mocked(api.GET).mockResolvedValue(metaWith(true) as never);
    vi.mocked(api.POST).mockResolvedValue({
      error: { field_errors: { new_password2: ["Хоёр нууц үг таарахгүй байна."] }, form_errors: [] },
      response: { status: 400, ok: false },
    } as never);

    const { container } = renderPage();
    await screen.findByRole("button", { name: "Хадгалах" });
    fill(container, { new_password1: NEW_PASSWORD, new_password2: "Other1234" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Хоёр нууц үг таарахгүй байна.");
    expect(message.className).toContain("text-red-600");
    expect(message.parentElement?.querySelector('input[name="new_password2"]')).not.toBeNull();
  });

  it("navigates to / after a 204, once the meta answer is fresh", async () => {
    vi.mocked(api.GET).mockResolvedValueOnce(metaWith(true) as never).mockResolvedValue(metaWith(false) as never);
    vi.mocked(api.POST).mockResolvedValue({ response: { status: 204, ok: true }, data: undefined } as never);

    const { container } = renderPage();
    await screen.findByRole("button", { name: "Хадгалах" });
    fill(container, { new_password1: NEW_PASSWORD, new_password2: NEW_PASSWORD });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("НҮҮР ХУУДАС")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/auth/password", {
      body: { old_password: "", new_password1: NEW_PASSWORD, new_password2: NEW_PASSWORD },
    });
    await waitFor(() => expect(vi.mocked(api.GET).mock.calls.length).toBeGreaterThanOrEqual(2));
  });
});
