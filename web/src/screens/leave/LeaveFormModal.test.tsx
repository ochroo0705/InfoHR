import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../api/schema";
import { Modal } from "../../widgets/Modal";
import { LeaveFormModal } from "./LeaveFormModal";
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

type Options = components["schemas"]["LeaveOptionsOut"];
type Edit = components["schemas"]["LeaveEditOut"];

const OPTIONS: Options = {
  assisted: null,
  employees: [
    { value: 3, label: "Ажилтан Нэг" },
    { value: 4, label: "Ажилтан Хоёр" },
  ],
  initial: { employee: 3, end_date: "2026-12-03", leave_type: 2, start_date: "2026-12-01" },
  not_configured: "",
  types: [
    { value: 2, label: "Ээлжийн амралт" },
    { value: 5, label: "Өвчний амралт" },
  ],
};

const EDIT: Edit = {
  id: 7,
  employees: OPTIONS.employees,
  initial: {
    employee: 3,
    end_date: "2026-12-03",
    leave_type: 2,
    note: "Гэр бүл",
    override_reason: "",
    start_date: "2026-12-01",
  },
  loaded: { adays: 3, comment: null, date1: "2026-12-01", date2: "2026-12-03", leave_type: 2, status: 1 },
  not_configured: "",
  types: OPTIONS.types,
};

const STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

function checkAnswer() {
  return ok({ balance_after: null, errors: [], period: null, valid: true, warnings: [], working_days: 3 });
}

// The live checks sent (the check writes nothing, but it is asked only on a commit).
function checkPosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === "/api/v1/leave/check");
}

// The posts that save (not the live check).
function savePosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === "/api/v1/leave" || path === "/api/v1/leave/{pk}");
}

const NOT_CONFIGURED = "Жилийн амралтын төрөл тохируулаагүй байна.";

function renderPop(mode: Parameters<typeof LeaveFormModal>[0]["mode"], onClose = vi.fn(), canSettings = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LeaveFormModal mode={mode} canSettings={canSettings} onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onClose, unmount: view.unmount };
}

// The value of a posted box: the hidden field of a typing box, or the field itself.
function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Хадгалах" });
}

describe("LeaveFormModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/leave/options") return ok(OPTIONS);
      if (path === "/api/v1/leave/{pk}") return ok(EDIT);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check" ? checkAnswer() : answer({}),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("add starts from the server's first values and shows the required marks", async () => {
    renderPop({ kind: "add" });
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Чөлөө бүртгэх" })).toBeTruthy();
    expect(valueOf("employee")).toBe("3");
    expect(valueOf("leave_type")).toBe("2");
    expect(valueOf("start_date")).toBe("2026-12-01");
    expect(valueOf("end_date")).toBe("2026-12-03");
    expect(screen.getByText("Ажилтан *")).toBeTruthy();
    expect(screen.getByText("Үлдэгдэл хүрэлцэхгүй бол шалтгаан")).toBeTruthy();
  });

  it("the not-configured notice links to the leave settings only for who may change them", async () => {
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/options"
        ? ok({ ...OPTIONS, not_configured: NOT_CONFIGURED })
        : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    const first = renderPop({ kind: "add" }, vi.fn(), false);
    await waitForForm();
    expect(screen.getByText(NOT_CONFIGURED)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Тохируулах" })).toBeNull();
    first.unmount();

    renderPop({ kind: "add" }, vi.fn(), true);
    await waitForForm();
    expect(screen.getByRole("link", { name: "Тохируулах" }).getAttribute("href")).toBe("/leave/settings/");
  });

  it("the edit pop-up's not-configured notice follows the same rule", async () => {
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/{pk}"
        ? ok({ ...EDIT, not_configured: NOT_CONFIGURED })
        : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    renderPop({ kind: "edit", id: 7 }, vi.fn(), true);
    await waitForForm();
    expect(screen.getByRole("link", { name: "Тохируулах" }).getAttribute("href")).toBe("/leave/settings/");
  });

  it("the live check waits for a commit: typing in the note sends nothing until the box loses focus", async () => {
    renderPop({ kind: "add" });
    await waitForForm();
    const note = document.querySelector<HTMLTextAreaElement>('textarea[name="note"]');
    if (!note) throw new Error("no note box");

    fireEvent.change(note, { target: { value: "Гэр" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(checkPosts()).toHaveLength(0);

    fireEvent.blur(note);
    await waitFor(() => expect(checkPosts()).toHaveLength(1));
  });

  it("a partial date sends no check; a whole date does", async () => {
    renderPop({ kind: "add" });
    await waitForForm();
    const end = document.querySelector<HTMLInputElement>('input[name="end_date"]');
    if (!end) throw new Error("no end box");

    fireEvent.change(end, { target: { value: "2026-12-0" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(checkPosts()).toHaveLength(0);

    fireEvent.change(end, { target: { value: "2026-12-05" } });
    await waitFor(() => expect(checkPosts()).toHaveLength(1));
    expect(checkPosts()[0][1]).toMatchObject({ body: expect.objectContaining({ end_date: "2026-12-05" }) });
  });

  it("edit mode asks no check on mount", async () => {
    renderPop({ kind: "edit", id: 7 });
    await waitForForm();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    expect(checkPosts()).toHaveLength(0);
  });

  it("add sends the list's prefill to the options", async () => {
    renderPop({ kind: "add", employee: 3, type: 2, start: "2026-12-01", end: "2026-12-03", from: "assistant" });
    await waitForForm();

    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/options", {
      params: { query: { employee: "3", type: "2", start: "2026-12-01", end: "2026-12-03", from: "assistant" } },
    });
  });

  it("successful save closes the pop-up", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check" ? checkAnswer() : ok({ error: "", field_errors: {}, form_errors: [], ok: true }),
    );
    const { onClose } = renderPop({ kind: "add" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave", {
      body: {
        employee: 3,
        leave_type: 2,
        start_date: "2026-12-01",
        end_date: "2026-12-03",
        note: "",
        override_reason: "",
      },
    });
  });

  it("refused save shows the messages under their boxes and keeps the typed values", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check"
        ? checkAnswer()
        : answer({ field_errors: { end_date: ["Дуусах огноо буруу байна."] }, form_errors: ["Ийм чөлөө бүртгэгдсэн байна."] }),
    );
    const { onClose } = renderPop({ kind: "add" });
    await waitForForm();

    fireEvent.change(document.querySelector<HTMLTextAreaElement>('textarea[name="note"]')!, {
      target: { value: "Гэр бүл" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Ийм чөлөө бүртгэгдсэн байна.")).toBeTruthy();
    expect(screen.getByText("Дуусах огноо буруу байна.").className).toContain("text-red-600");
    expect(onClose).not.toHaveBeenCalled();
    expect(valueOf("note")).toBe("Гэр бүл");
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("a field error sits outside its box, and the control names it in aria-describedby", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check"
        ? checkAnswer()
        : answer({ field_errors: { end_date: ["Дуусах огноо буруу байна."] } }),
    );
    renderPop({ kind: "add" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Дуусах огноо буруу байна.");
    const box = message.parentElement;
    expect(box?.id).toBeTruthy();
    expect(message.closest("label")).toBeNull();
    const control = document.querySelector<HTMLInputElement>('input[name="end_date"]');
    expect(control?.getAttribute("aria-describedby")).toBe(box?.id);
    expect(control?.getAttribute("aria-invalid")).toBe("true");
  });

  it("stale row text from the server is shown in the red box", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check" ? checkAnswer() : answer({ error: STALE }),
    );
    const { onClose } = renderPop({ kind: "edit", id: 7 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const text = await screen.findByText(STALE);
    expect(text.closest("div")?.className).toContain("text-red-700");
    expect(text.closest('[role="alert"]')).not.toBeNull();
    // The second line tells the user to reopen; the text is the API's own stale wording.
    expect(STALE_TEXT).toBe(STALE);
    expect(screen.getByText(STALE_REOPEN_TEXT)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a failed request shows its form errors and keeps the pop-up open", async () => {
    h.post.mockImplementation(async (path: string) => {
      if (path === "/api/v1/leave/check") return checkAnswer();
      throw Object.assign(new Error("request failed"), { status: 403, formErrors: ["Чөлөө бүртгэх эрх байхгүй."], fieldErrors: {} });
    });
    const { onClose } = renderPop({ kind: "add" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Чөлөө бүртгэх эрх байхгүй.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a second click while the save is pending does not post again", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check" ? checkAnswer() : new Promise(() => {}),
    );
    renderPop({ kind: "add" });
    await waitForForm();

    const save = screen.getByRole("button", { name: "Хадгалах" });
    fireEvent.click(save);
    fireEvent.click(save);

    await waitFor(() => expect(savePosts()).toHaveLength(1));
    // Give a second post, if one were sent, time to reach the mock before the count is read.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(savePosts()).toHaveLength(1);
  });

  it("edit sends the loaded row back untouched and keeps the employee", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/check" ? checkAnswer() : ok({ error: "", field_errors: {}, form_errors: [], ok: true }),
    );
    const { onClose } = renderPop({ kind: "edit", id: 7 });
    await waitForForm();

    expect(valueOf("note")).toBe("Гэр бүл");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/{pk}", {
      params: { path: { pk: 7 } },
      body: expect.objectContaining({ employee: 3, loaded: EDIT.loaded, note: "Гэр бүл" }),
    });
  });

  it("reopening an edit reads the row again: the loading shell first, then the new row, not a cached copy", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const pop = () => (
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LeaveFormModal mode={{ kind: "edit", id: 7 }} onClose={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    const first = render(pop());
    await waitForForm();
    expect(valueOf("note")).toBe("Гэр бүл");
    first.unmount();
    // Let the cache drop what no pop-up shows (gcTime 0 removes it on the next timer tick).
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/{pk}"
        ? ok({ ...EDIT, initial: { ...EDIT.initial, note: "Шинэ тайлбар" } })
        : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    render(pop());
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    await waitForForm();
    expect(valueOf("note")).toBe("Шинэ тайлбар");
  });

  it("Escape closes only the top pop-up", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const parentClose = vi.fn();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <Modal open onClose={parentClose} title="Доод цонх">
          Доод
        </Modal>
        <LeaveFormModal mode={{ kind: "add" }} onClose={onClose} />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(parentClose).not.toHaveBeenCalled();
  });
});
