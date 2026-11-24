import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RequestRejectModal } from "./RequestRejectModal";

// The API client is replaced by a stub that answers by path, so the real helpers and hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), confirm: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../../widgets/confirm", () => ({ confirm: (...args: unknown[]) => h.confirm(...args) }));

const REQUEST = { id: 5, leave_type: "Жилийн амралт", start: "2026-03-01", end: "2026-03-03" };
const REJECT = "/api/v1/leave/requests/{pk}/reject";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

function rejectPosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === REJECT);
}

function reasonBox(): HTMLTextAreaElement {
  const el = document.querySelector<HTMLTextAreaElement>('textarea[name="reason"]');
  if (!el) throw new Error("no reason box");
  return el;
}

function renderReject(onClose = vi.fn(), onDone = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RequestRejectModal request={REQUEST} onClose={onClose} onDone={onDone} />
    </QueryClientProvider>,
  );
  return { onClose, onDone };
}

function submitButton(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name: "Татгалзах" }) as HTMLButtonElement;
}

describe("RequestRejectModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
    h.post.mockImplementation(async () => answer({}));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the title, the type and dates line, and a required reason box with the star", () => {
    renderReject();

    expect(screen.getByRole("heading", { name: "Хүсэлт татгалзах" })).toBeTruthy();
    expect(screen.getByText("Жилийн амралт 2026-03-01 – 2026-03-03")).toBeTruthy();
    const label = screen.getByText("Татгалзсан шалтгаан *");
    expect(label.closest("label")?.querySelector("textarea")).toBe(reasonBox());
    expect(reasonBox().required).toBe(true);
    expect(screen.getByRole("button", { name: "Болих" })).toBeTruthy();
  });

  it("an empty reason is refused by the server: its message shows under the box and the pop-up stays open", async () => {
    h.post.mockImplementation(async () => answer({ field_errors: { reason: ["Татгалзсан шалтгаан бичнэ үү."] } }));
    const { onDone, onClose } = renderReject();

    fireEvent.click(submitButton());

    const message = await screen.findByText("Татгалзсан шалтгаан бичнэ үү.");
    expect(message.className).toContain("text-red-600");
    expect(message.closest("label")).toBeNull();
    expect(reasonBox().getAttribute("aria-describedby")).toBe(message.parentElement?.id);
    expect(reasonBox().getAttribute("aria-invalid")).toBe("true");
    expect(onDone).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("ok posts the reason and calls onDone", async () => {
    h.post.mockImplementation(async () => ok({ error: "", field_errors: {}, form_errors: [], ok: true }));
    const { onDone } = renderReject();

    fireEvent.change(reasonBox(), { target: { value: "Төслийн хугацаа" } });
    fireEvent.click(submitButton());

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledWith(REJECT, { params: { path: { pk: 5 } }, body: { reason: "Төслийн хугацаа" } });
  });

  it("ok false shows the service message in the red box and keeps the typed reason", async () => {
    h.post.mockImplementation(async () => answer({ error: "Хүсэлт өөрчлөгдсөн байна" }));
    const { onDone } = renderReject();

    fireEvent.change(reasonBox(), { target: { value: "Гэр бүл" } });
    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Хүсэлт өөрчлөгдсөн байна");
    expect(alert.className).toContain("text-red-700");
    expect(onDone).not.toHaveBeenCalled();
    expect(reasonBox().value).toBe("Гэр бүл");
  });

  it("reject answering 404 (decided meanwhile) shows the decided text and locks the submit", async () => {
    h.post.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    const { onDone } = renderReject();

    fireEvent.change(reasonBox(), { target: { value: "Гэр бүл" } });
    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Энэ хүсэлт шийдэгдсэн байна.");
    expect(submitButton().disabled).toBe(true);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("a second click while the reject is pending posts once", async () => {
    h.post.mockImplementation(async () => new Promise(() => {}));
    renderReject();

    fireEvent.change(reasonBox(), { target: { value: "Гэр бүл" } });
    const submit = submitButton();
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(rejectPosts()).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(rejectPosts()).toHaveLength(1);
  });

  it("Болих closes a clean pop-up at once without asking", () => {
    const { onClose, onDone } = renderReject();

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    expect(h.confirm).not.toHaveBeenCalled();
  });
});
