import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { api, nav, setCsrf } from "../api/client";
import LoginPage from "./LoginPage";

vi.mock("../api/client", () => ({
  api: { GET: vi.fn(), POST: vi.fn() },
  setCsrf: vi.fn(),
  nav: { assign: vi.fn() },
}));

const NETWORK_ERROR = "Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.";

const LOCK_MESSAGE =
  "Нэвтрэх оролдлого хэт олон удаа буруу боллоо. 15 минутын дараа дахин оролдоно уу.";

function renderLogin(path = "/login") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/reports" element={<p>REPORTS PAGE</p>} />
        <Route path="/" element={<p>HOME PAGE</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.GET).mockResolvedValue({
      data: { csrf: "tok", must_change_password: false },
      response: { status: 200 },
    } as never);
  });

  it("renders both labels and the submit button", async () => {
    renderLogin();

    expect(screen.getByLabelText("Нэвтрэх нэр")).toBeTruthy();
    expect(screen.getByLabelText("Нууц үг")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Нэвтрэх" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "MACS Human Capital — Нэвтрэх" }),
    ).toBeTruthy();
    await waitFor(() => expect(setCsrf).toHaveBeenCalledWith("tok"));
  });

  it("shows the exact lock message from a 400 response", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      error: { field_errors: {}, form_errors: [LOCK_MESSAGE] },
      response: { status: 400 },
    } as never);
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    const message = await screen.findByText(LOCK_MESSAGE);
    expect(message.tagName).toBe("P");
    expect(message.className).toContain("text-red-600");
  });

  it("navigates to the next query value after a 200 response", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      data: { ok: true, must_change_password: false },
      response: { status: 200 },
    } as never);
    renderLogin("/login?next=%2Freports");
    await waitFor(() => expect(setCsrf).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    expect(await screen.findByText("REPORTS PAGE")).toBeTruthy();
    expect(nav.assign).not.toHaveBeenCalled();
  });

  it("assigns /password/change when the user must change the password", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      data: { ok: true, must_change_password: true },
      response: { status: 200 },
    } as never);
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    await waitFor(() => expect(nav.assign).toHaveBeenCalledWith("/password/change"));
  });

  it("stores the CSRF token from the login response before navigating", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      data: { ok: true, must_change_password: false, csrf: "rotated" },
      response: { status: 200 },
    } as never);
    renderLogin("/login?next=%2Freports");
    await waitFor(() => expect(setCsrf).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    expect(await screen.findByText("REPORTS PAGE")).toBeTruthy();
    expect(setCsrf).toHaveBeenLastCalledWith("rotated");
  });

  it("keeps submit disabled until the CSRF token is set", async () => {
    vi.mocked(api.GET).mockReturnValue(new Promise(() => undefined) as never);
    renderLogin();

    const button = screen.getByRole("button", { name: "Нэвтрэх" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(setCsrf).not.toHaveBeenCalled();
  });

  it("disables submit while a login request is in flight", async () => {
    vi.mocked(api.POST).mockReturnValue(new Promise(() => undefined) as never);
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalledWith("tok"));

    const button = screen.getByRole("button", { name: "Нэвтрэх" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(button);

    await waitFor(() => expect(button.disabled).toBe(true));
  });

  it("clears the password and focuses the username after a 400 response", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      error: { field_errors: {}, form_errors: [LOCK_MESSAGE] },
      response: { status: 400 },
    } as never);
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalled());

    const password = screen.getByLabelText("Нууц үг") as HTMLInputElement;
    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(password, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    await screen.findByText(LOCK_MESSAGE);
    expect(password.value).toBe("");
    expect(document.activeElement?.id).toBe("id_username");
  });

  it("shows the network error when the login request rejects", async () => {
    vi.mocked(api.POST).mockRejectedValue(new TypeError("Failed to fetch"));
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalledWith("tok"));

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    expect(await screen.findByText(NETWORK_ERROR)).toBeTruthy();
  });

  it("shows the network error on an unexpected status such as 500", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      error: { detail: "boom" },
      response: { status: 500 },
    } as never);
    renderLogin();
    await waitFor(() => expect(setCsrf).toHaveBeenCalledWith("tok"));

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    expect(await screen.findByText(NETWORK_ERROR)).toBeTruthy();
  });

  it("shows the network error when the meta request rejects", async () => {
    vi.mocked(api.GET).mockRejectedValue(new TypeError("Failed to fetch"));
    renderLogin();

    expect(await screen.findByText(NETWORK_ERROR)).toBeTruthy();
  });

  it("falls back to / when next contains a backslash", async () => {
    vi.mocked(api.POST).mockResolvedValue({
      data: { ok: true, must_change_password: false, csrf: "tok" },
      response: { status: 200 },
    } as never);
    renderLogin("/login?next=%2F%5Cevil");
    await waitFor(() => expect(setCsrf).toHaveBeenCalledWith("tok"));

    fireEvent.change(screen.getByLabelText("Нэвтрэх нэр"), { target: { value: "bat" } });
    fireEvent.change(screen.getByLabelText("Нууц үг"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх" }));

    expect(await screen.findByText("HOME PAGE")).toBeTruthy();
  });
});
