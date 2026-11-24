import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LeaveRequestModal } from "./LeaveRequestModal";

// The API client is replaced by a stub that answers by path, so the real helpers and hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../../widgets/confirm", () => ({ confirm: vi.fn(() => false) }));

const OPTIONS = {
  types: [
    { value: 2, label: "Ээлжийн амралт" },
    { value: 5, label: "Өвчний амралт" },
  ],
};

const CHECK_PATH = "/api/v1/leave/requests/check";
const SAVE_PATH = "/api/v1/leave/requests";
const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

function checkAnswer() {
  return ok({ balance_after: null, errors: [], period: null, valid: true, warnings: [], working_days: 3 });
}

function checkPosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === CHECK_PATH);
}

function savePosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === SAVE_PATH);
}

function renderModal(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <LeaveRequestModal onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose, invalidate };
}

// The value of a posted box: the real select, the date box or the text box.
function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Хүсэлт илгээх" });
}

// A pick of the type and whole dates, as the user makes them (each change is a commit of the form).
function fillType(value: string) {
  fireEvent.change(document.querySelector<HTMLSelectElement>('select[name="leave_type"]')!, { target: { value } });
}
function fillDate(name: "start_date" | "end_date", value: string) {
  fireEvent.change(document.querySelector<HTMLInputElement>(`input[name="${name}"]`)!, { target: { value } });
}
function fillRequest() {
  fillType("2");
  fillDate("start_date", "2026-12-01");
  fillDate("end_date", "2026-12-03");
}

describe("LeaveRequestModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/requests/options" ? ok(OPTIONS) : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    h.post.mockImplementation(async (path: string) =>
      path === CHECK_PATH ? checkAnswer() : answer({}),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the title, the grey sentence and the four fields with their marks", async () => {
    renderModal();
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Чөлөө хүсэх" })).toBeTruthy();
    expect(
      screen.getByText("Хүсэлт батлагдах хүртэл хүлээгдэнэ. Бүх шат батлагдсаны дараа чөлөө бүртгэгдэнэ."),
    ).toBeTruthy();
    expect(screen.getByText("Төрөл *")).toBeTruthy();
    expect(screen.getByText("Эхлэх *")).toBeTruthy();
    expect(screen.getByText("Дуусах *")).toBeTruthy();
    expect(screen.getByText("Тайлбар")).toBeTruthy();
    expect(screen.queryByText("Ажилтан *")).toBeNull();
  });

  it("loads the types from the request options", async () => {
    renderModal();
    await waitForForm();

    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/requests/options");
    expect(document.querySelector('select[name="leave_type"]')?.textContent).toContain("Ээлжийн амралт");
  });

  it("success posts the own record's form, closes and refreshes the me key", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === CHECK_PATH ? checkAnswer() : ok({ error: "", field_errors: {}, form_errors: [], ok: true }),
    );
    const { onClose, invalidate } = renderModal();
    await waitForForm();
    fillRequest();

    fireEvent.click(screen.getByRole("button", { name: "Хүсэлт илгээх" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me"] });
    expect(h.post).toHaveBeenCalledWith(SAVE_PATH, {
      body: { leave_type: 2, start_date: "2026-12-01", end_date: "2026-12-03", note: "" },
    });
  });

  it("the posted body never has an employee key", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === CHECK_PATH ? checkAnswer() : ok({ error: "", field_errors: {}, form_errors: [], ok: true }),
    );
    const { onClose } = renderModal();
    await waitForForm();
    fillRequest();

    fireEvent.click(screen.getByRole("button", { name: "Хүсэлт илгээх" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const body = savePosts()[0][1] as { body: Record<string, unknown> };
    expect(Object.keys(body.body)).not.toContain("employee");
  });

  it("a refused save keeps the typed values and shows the error, form and field messages", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === CHECK_PATH
        ? checkAnswer()
        : answer({
            error: "Хүсэлт илгээж чадсангүй.",
            form_errors: ["Ийм хүсэлт байна."],
            field_errors: { end_date: ["Дуусах огноо буруу байна."] },
          }),
    );
    const { onClose } = renderModal();
    await waitForForm();
    fillRequest();
    fireEvent.change(document.querySelector<HTMLTextAreaElement>('textarea[name="note"]')!, {
      target: { value: "Гэр бүл" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Хүсэлт илгээх" }));

    expect(await screen.findByText("Хүсэлт илгээж чадсангүй.")).toBeTruthy();
    expect(screen.getByText("Ийм хүсэлт байна.")).toBeTruthy();
    expect(screen.getByText("Дуусах огноо буруу байна.").className).toContain("text-red-600");
    expect(onClose).not.toHaveBeenCalled();
    expect(valueOf("note")).toBe("Гэр бүл");
    expect(valueOf("leave_type")).toBe("2");
    expect(valueOf("start_date")).toBe("2026-12-01");
    expect(valueOf("end_date")).toBe("2026-12-03");
  });

  it("a double click posts once and disables the button while the request runs", async () => {
    h.post.mockImplementation(async (path: string) => (path === CHECK_PATH ? checkAnswer() : new Promise(() => {})));
    renderModal();
    await waitForForm();
    fillRequest();

    const send = screen.getByRole("button", { name: "Хүсэлт илгээх" });
    fireEvent.click(send);
    fireEvent.click(send);

    await waitFor(() => expect(savePosts()).toHaveLength(1));
    await waitFor(() => expect((screen.getByRole("button", { name: "Хүсэлт илгээх" }) as HTMLButtonElement).disabled).toBe(true));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(savePosts()).toHaveLength(1);
  });

  it("the check line asks nothing on mount, and only once the type and both dates are set", async () => {
    renderModal();
    await waitForForm();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(checkPosts()).toHaveLength(0);

    fillType("2");
    fillDate("start_date", "2026-12-01");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(checkPosts()).toHaveLength(0);

    fillDate("end_date", "2026-12-03");
    await waitFor(() => expect(checkPosts()).toHaveLength(1));
    expect(checkPosts()[0][1]).toEqual({
      body: { leave_type: 2, start_date: "2026-12-01", end_date: "2026-12-03", note: "" },
    });
  });

  it("a 403 from the options shows the load failure, with no form to send", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderModal();

    expect(await screen.findByText(LOAD_FAILED_TEXT)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хүсэлт илгээх" })).toBeNull();
  });

  it("Escape closes the pop-up", async () => {
    const { onClose } = renderModal();
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
