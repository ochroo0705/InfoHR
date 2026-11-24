import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AutoGrantForm } from "./AutoGrantForm";

// The API client is replaced by a stub that answers by path, so the real helpers and hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function renderForm(auto: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AutoGrantForm auto={auto} />
    </QueryClientProvider>,
  );
}

function box(): HTMLInputElement {
  return screen.getByRole("checkbox", { name: /Ээлжийн амралтын эрхийг автоматаар нэмэх/ }) as HTMLInputElement;
}

describe("AutoGrantForm", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the title, the help sentence and the switch in its saved state", () => {
    renderForm(true);

    expect(screen.getByRole("heading", { name: "Ээлжийн амралтын эрхийг автоматаар нэмэх" })).toBeTruthy();
    expect(screen.getByText(/Унтраалттай үед эрхийг гараар нэмнэ/)).toBeTruthy();
    expect(box().checked).toBe(true);
  });

  it("saves the flag as the user left it and shows the saved line on ok", async () => {
    h.post.mockImplementation(async () => ok({ error: "", field_errors: {}, form_errors: [], ok: true }));
    renderForm(true);

    fireEvent.click(box());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText("Хадгалагдлаа");
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/auto", { body: { auto_annual_grant: false } });
  });

  it("a double click posts once", async () => {
    h.post.mockImplementation(async () => ok({ error: "", field_errors: {}, form_errors: [], ok: true }));
    renderForm(false);

    const button = screen.getByRole("button", { name: "Хадгалах" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByText("Хадгалагдлаа")).toBeTruthy());
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("while the save runs the save button is locked", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderForm(false);

    const button = screen.getByRole("button", { name: "Хадгалах" }) as HTMLButtonElement;
    fireEvent.click(button);

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(button.disabled).toBe(true);
  });

  it("a refused save shows its form error at the top and no saved line", async () => {
    h.post.mockImplementation(async () =>
      ok({ error: "", field_errors: {}, form_errors: ["Хадгалах боломжгүй."], ok: false }),
    );
    renderForm(false);

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Хадгалах боломжгүй.")).toBeTruthy();
    expect(screen.queryByText("Хадгалагдлаа")).toBeNull();
  });
});
