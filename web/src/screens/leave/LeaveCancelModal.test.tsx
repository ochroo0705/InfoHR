import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { Modal } from "../../widgets/Modal";
import { LeaveCancelModal } from "./LeaveCancelModal";
import { STALE_REOPEN_TEXT, STALE_TEXT } from "./leaveTexts";

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

type Info = components["schemas"]["LeaveCancelInfoOut"];

const LOADED = { adays: 3, comment: null, date1: "2026-03-01", date2: "2026-03-03", leave_type: 2, status: 1 };

const NORMAL: Info = {
  end: "2026-03-03",
  label: "Жилийн амралт",
  loaded: LOADED,
  mistake: false,
  restores_balance: false,
  start: "2026-03-01",
};

const MISTAKE: Info = { ...NORMAL, mistake: true, restores_balance: true };

const STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

// The posts that cancel (not any other write).
function cancelPosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === "/api/v1/leave/{pk}/cancel");
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderPop(info: Info, onClose = vi.fn()) {
  h.get.mockImplementation(async (path: string) =>
    path === "/api/v1/leave/{pk}/cancel"
      ? ok(info)
      : { data: undefined, error: {}, response: { ok: false, status: 404 } },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LeaveCancelModal id={7} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

function reasonBox(): HTMLInputElement {
  const el = document.querySelector<HTMLInputElement>('input[name="reason"]');
  if (!el) throw new Error("no reason box");
  return el;
}

// The submit button inside the pop-up (the page behind it has no buttons of this name in these tests).
function submitButton(name: string): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name }) as HTMLButtonElement;
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Болих" });
}

describe("LeaveCancelModal", () => {
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

  it("a leave that has not started asks to cancel it, with its label and dates", async () => {
    renderPop(NORMAL);
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Чөлөө цуцлах" })).toBeTruthy();
    expect(screen.getByText("Жилийн амралт 2026-03-01 – 2026-03-03")).toBeTruthy();
    expect(screen.queryByText(/Эхэлсэн чөлөөг устгахгүй/)).toBeNull();
    expect(submitButton("Цуцлах").className).toContain("bg-red-600");
    expect(screen.getByText("Шалтгаан *")).toBeTruthy();
  });

  it("a started leave is marked as a mistake, and says the balance comes back when it does", async () => {
    renderPop(MISTAKE);
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Буруу гэж тэмдэглэх" })).toBeTruthy();
    expect(
      screen.getByText("Эхэлсэн чөлөөг устгахгүй, буруу бүртгэл гэж тэмдэглэнэ. Үлдэгдэл буцаж нэмэгдэнэ."),
    ).toBeTruthy();
    expect(submitButton("Буруу гэж тэмдэглэх").className).toContain("bg-red-600");
  });

  it("a mistake that does not restore the balance leaves out the balance sentence", async () => {
    renderPop({ ...MISTAKE, restores_balance: false });
    await waitForForm();

    expect(screen.getByText("Эхэлсэн чөлөөг устгахгүй, буруу бүртгэл гэж тэмдэглэнэ.")).toBeTruthy();
    expect(screen.queryByText(/Үлдэгдэл буцаж нэмэгдэнэ/)).toBeNull();
  });

  it("ok closes the pop-up and sends the reason with the loaded row untouched", async () => {
    h.post.mockImplementation(async () => ok({ error: "", field_errors: {}, form_errors: [], ok: true }));
    const { onClose } = renderPop(NORMAL);
    await waitForForm();

    fireEvent.change(reasonBox(), { target: { value: "Гэр бүл" } });
    fireEvent.click(submitButton("Цуцлах"));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/{pk}/cancel", {
      params: { path: { pk: 7 } },
      body: { reason: "Гэр бүл", loaded: LOADED },
    });
  });

  it("ok false shows the field message under the reason box and keeps the typed reason", async () => {
    h.post.mockImplementation(async () => answer({ field_errors: { reason: ["Шалтгаан заавал бөглөнө."] } }));
    const { onClose } = renderPop(NORMAL);
    await waitForForm();

    fireEvent.change(reasonBox(), { target: { value: "   " } });
    fireEvent.click(submitButton("Цуцлах"));

    const message = await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(message.className).toContain("text-red-600");
    // The message sits outside the label, and the box names it.
    expect(message.closest("label")).toBeNull();
    expect(message.parentElement?.id).toBeTruthy();
    expect(reasonBox().getAttribute("aria-describedby")).toBe(message.parentElement?.id);
    expect(reasonBox().getAttribute("aria-invalid")).toBe("true");
    expect(onClose).not.toHaveBeenCalled();
    expect(reasonBox().value).toBe("   ");
  });

  it("ok false shows the service message in the red box at the top and keeps the pop-up open", async () => {
    h.post.mockImplementation(async () => answer({ error: STALE }));
    const { onClose } = renderPop(NORMAL);
    await waitForForm();

    fireEvent.change(reasonBox(), { target: { value: "Гэр бүл" } });
    fireEvent.click(submitButton("Цуцлах"));

    const text = await screen.findByText(STALE);
    expect(text.closest("div")?.className).toContain("text-red-700");
    expect(text.closest('[role="alert"]')).not.toBeNull();
    expect(STALE_TEXT).toBe(STALE);
    expect(screen.getByText(STALE_REOPEN_TEXT)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(reasonBox().value).toBe("Гэр бүл");
  });

  it("a failed request shows its form errors and keeps the pop-up open", async () => {
    h.post.mockImplementation(async () => {
      throw Object.assign(new Error("request failed"), {
        status: 403,
        formErrors: ["Цуцлах эрх байхгүй."],
        fieldErrors: {},
      });
    });
    const { onClose } = renderPop(NORMAL);
    await waitForForm();

    fireEvent.click(submitButton("Цуцлах"));

    expect(await screen.findByText("Цуцлах эрх байхгүй.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("while the info loads the title is «Чөлөө цуцлах», and it switches to the mistake title once the info says so", async () => {
    h.get.mockImplementation(() => new Promise(() => {}));
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <LeaveCancelModal id={7} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "Чөлөө цуцлах" })).toBeTruthy();
    cleanup();

    h.get.mockImplementation(async () => ok(MISTAKE));
    renderPop(MISTAKE);
    await waitForForm();
    expect(screen.getByRole("heading", { name: "Буруу гэж тэмдэглэх" })).toBeTruthy();
  });

  it("a failed info load keeps the title «Чөлөө цуцлах» and says it failed", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <LeaveCancelModal id={7} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.getByRole("heading", { name: "Чөлөө цуцлах" })).toBeTruthy();
  });

  it("a double click while the cancel is pending posts once", async () => {
    h.post.mockImplementation(async () => new Promise(() => {}));
    renderPop(NORMAL);
    await waitForForm();

    const submit = submitButton("Цуцлах");
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(cancelPosts()).toHaveLength(1));
    // Give a second post, if one were sent, time to reach the mock before the count is read.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(cancelPosts()).toHaveLength(1);
  });

  it("Болих closes a clean pop-up at once", async () => {
    const { onClose } = renderPop(NORMAL);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("Escape closes only the top pop-up", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/{pk}/cancel"
        ? ok(NORMAL)
        : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    const parentClose = vi.fn();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <Modal open onClose={parentClose} title="Доод цонх">
          Доод
        </Modal>
        <LeaveCancelModal id={7} onClose={onClose} />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(parentClose).not.toHaveBeenCalled();
  });
});
