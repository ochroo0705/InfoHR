import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaveRequestDetailOut } from "../../api/leaveRequests";
import { Modal } from "../../widgets/Modal";
import { RequestDetailModal } from "./RequestDetailModal";

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

const DETAIL: LeaveRequestDetailOut = {
  id: 5,
  employee_name: "Бат Болд",
  job_line: "Санхүү · Нягтлан",
  leave_type: "Жилийн амралт",
  start: "2026-03-01",
  end: "2026-03-03",
  working_days: 3,
  created: "2026-02-27",
  waiting: true,
  current_step: 2,
  step_count: 3,
  rule: "Шууд удирдлага",
  override: false,
  balance_after: 4,
  warnings: [],
  past: false,
  status_label: "Хүлээгдэж буй",
  reason: "",
  needs_reason: false,
  may: true,
  others: [],
  history: [],
};

const APPROVE = "/api/v1/leave/requests/{pk}/approve";
const REJECT = "/api/v1/leave/requests/{pk}/reject";
const DETAIL_PATH = "/api/v1/leave/requests/{pk}";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

function postsTo(path: string): unknown[][] {
  return h.post.mock.calls.filter(([called]) => called === path);
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderPop(detail: LeaveRequestDetailOut | null, onClose = vi.fn(), client = makeClient()) {
  h.get.mockImplementation(async (path: string) =>
    path === DETAIL_PATH && detail
      ? ok(detail)
      : { data: undefined, error: {}, response: { ok: false, status: 404 } },
  );
  render(
    <QueryClientProvider client={client}>
      <RequestDetailModal id={5} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose, client };
}

// The pop-up that is on top (the reject pop-up sits over this one).
function topDialog(): HTMLElement {
  const dialogs = screen.getAllByRole("dialog");
  return dialogs[dialogs.length - 1];
}

function reasonBox(): HTMLInputElement | null {
  return document.querySelector<HTMLInputElement>('input[name="override_reason"]');
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Болих" });
}

describe("RequestDetailModal", () => {
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

  it("shows the name, the job line, the leave facts and the step line while the request waits", async () => {
    renderPop(DETAIL);
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Бат Болд" })).toBeTruthy();
    expect(screen.getByText("Санхүү · Нягтлан")).toBeTruthy();
    expect(screen.getByText("Жилийн амралт")).toBeTruthy();
    expect(screen.getByText("2026-03-01 – 2026-03-03")).toBeTruthy();
    expect(screen.getByText("2/3 · Шууд удирдлага")).toBeTruthy();
    expect(screen.getByText("4")).toBeTruthy();
    expect(screen.queryByText(/Энэ хүсэлт шийдэгдсэн/)).toBeNull();
  });

  it("the past-date line shows only while the request waits and is past", async () => {
    renderPop({ ...DETAIL, past: true });
    await waitForForm();
    expect(screen.getByText("Энэ хүсэлт өнгөрсөн огноотой байна.")).toBeTruthy();
  });

  it("a decided request does not show the past-date line, and shows its status and reason instead", async () => {
    renderPop({
      ...DETAIL,
      waiting: false,
      past: true,
      status_label: "Татгалзсан",
      reason: "Ажлын ачаалал",
      balance_after: null,
    });
    await waitForForm();

    expect(screen.queryByText("Энэ хүсэлт өнгөрсөн огноотой байна.")).toBeNull();
    expect(screen.queryByText(/Шат /)).toBeNull();
    expect(screen.getByText("Энэ хүсэлт шийдэгдсэн: Татгалзсан · Ажлын ачаалал")).toBeTruthy();
  });

  it("the balance line is left out when the balance after is not known", async () => {
    renderPop({ ...DETAIL, balance_after: null });
    await waitForForm();
    expect(screen.queryByText("Энэ чөлөөг авсны дараах үлдэгдэл")).toBeNull();
  });

  it("a history line shows its date once: the text from the API already starts with the date", async () => {
    renderPop({
      ...DETAIL,
      history: [{ at: "2026-11-04", text: "2026-11-04 · Хүсэлт гаргасан · Бат Болд" }],
    });
    await waitForForm();

    expect(screen.getByText("2026-11-04 · Хүсэлт гаргасан · Бат Болд")).toBeTruthy();
    expect(screen.queryByText(/2026-11-04 · 2026-11-04/)).toBeNull();
  });

  it("the others and the history show their empty texts when there are none", async () => {
    renderPop(DETAIL);
    await waitForForm();
    expect(screen.getByText("Давхцсан хүн алга")).toBeTruthy();
    expect(screen.getByText("Түүх бүртгэгдээгүй")).toBeTruthy();
  });

  it("approve posts the loaded step and the typed reason; ok closes the pop-up and refreshes the requests", async () => {
    h.post.mockImplementation(async () => ok({ error: "", field_errors: {}, form_errors: [], ok: true }));
    const { onClose, client } = renderPop({ ...DETAIL, current_step: 3, step_count: 3 });
    const spy = vi.spyOn(client, "invalidateQueries");
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Батлах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(postsTo(APPROVE)).toHaveLength(1);
    expect(h.post).toHaveBeenCalledWith(APPROVE, {
      params: { path: { pk: 5 } },
      body: { step: 3, override_reason: "" },
    });
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["leave", "requests"] }));
  });

  it("approve ok false keeps the pop-up open, shows the error in the red box and keeps the typed text", async () => {
    h.post.mockImplementation(async () =>
      answer({ error: "Шат өөрчлөгдсөн байна", field_errors: { override_reason: ["Шалтгаан заавал бөглөнө."] } }),
    );
    const { onClose } = renderPop({ ...DETAIL, needs_reason: true });
    await waitForForm();

    fireEvent.change(reasonBox() as HTMLInputElement, { target: { value: "Төслийн хугацаа" } });
    fireEvent.click(screen.getByRole("button", { name: "Батлах" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Шат өөрчлөгдсөн байна");
    expect(alert.className).toContain("text-red-700");
    const message = await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(message.closest("label")).toBeNull();
    expect(reasonBox()?.getAttribute("aria-describedby")).toBe(message.parentElement?.id);
    expect(onClose).not.toHaveBeenCalled();
    expect(reasonBox()?.value).toBe("Төслийн хугацаа");
  });

  it("approve answering 404 (decided meanwhile) shows the decided text, hides the decision buttons and refetches the detail", async () => {
    h.post.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPop(DETAIL);
    await waitForForm();
    const before = h.get.mock.calls.filter(([path]) => path === DETAIL_PATH).length;

    fireEvent.click(screen.getByRole("button", { name: "Батлах" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Энэ хүсэлт шийдэгдсэн байна.");
    expect(screen.queryByRole("button", { name: "Батлах" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Татгалзах" })).toBeNull();
    expect(screen.getByRole("button", { name: "Болих" })).toBeTruthy();
    await waitFor(() =>
      expect(h.get.mock.calls.filter(([path]) => path === DETAIL_PATH).length).toBeGreaterThan(before),
    );
  });

  it("the balance after the leave shows while the request waits", async () => {
    renderPop({ ...DETAIL, balance_after: 7 });
    await waitForForm();
    expect(screen.getByText("Энэ чөлөөг авсны дараах үлдэгдэл")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
  });

  it("the balance after the leave does not show once the request is decided", async () => {
    renderPop({ ...DETAIL, waiting: false, balance_after: 7 });
    await waitForForm();
    expect(screen.queryByText("Энэ чөлөөг авсны дараах үлдэгдэл")).toBeNull();
    expect(screen.queryByText("7")).toBeNull();
  });

  it("the reason box is hidden until needs_reason, and shown after a refusal", async () => {
    h.post.mockImplementation(async () => answer({ error: "Алдаа гарлаа" }));
    renderPop(DETAIL);
    await waitForForm();
    expect(reasonBox()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Батлах" }));

    await screen.findByText("Алдаа гарлаа");
    expect(reasonBox()).not.toBeNull();
    expect(screen.getByText("Үлдэгдэл хүрэлцэхгүй бол шалтгаан")).toBeTruthy();
  });

  it("the reason box is shown at once when needs_reason is set", async () => {
    renderPop({ ...DETAIL, needs_reason: true });
    await waitForForm();
    expect(reasonBox()).not.toBeNull();
  });

  it("a read-only user sees no form and no approve or reject button, only Болих", async () => {
    renderPop({ ...DETAIL, may: false });
    await waitForForm();

    expect(screen.queryByRole("button", { name: "Батлах" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Татгалзах" })).toBeNull();
    expect(document.querySelector("form")).toBeNull();
    expect(screen.getByRole("button", { name: "Болих" })).toBeTruthy();
  });

  it("a second click while the approve is pending posts once", async () => {
    h.post.mockImplementation(async () => new Promise(() => {}));
    renderPop(DETAIL);
    await waitForForm();

    const submit = screen.getByRole("button", { name: "Батлах" });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(postsTo(APPROVE)).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(postsTo(APPROVE)).toHaveLength(1);
  });

  it("Татгалзах opens the reject pop-up, and a done reject closes both pop-ups", async () => {
    h.post.mockImplementation(async (path: string) =>
      path === REJECT ? ok({ error: "", field_errors: {}, form_errors: [], ok: true }) : answer({}),
    );
    const { onClose } = renderPop(DETAIL);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Татгалзах" }));
    expect(await screen.findByRole("heading", { name: "Хүсэлт татгалзах" })).toBeTruthy();

    const dialog = topDialog();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Төслийн хугацаа" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Татгалзах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledWith(REJECT, { params: { path: { pk: 5 } }, body: { reason: "Төслийн хугацаа" } });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Хүсэлт татгалзах" })).toBeNull());
  });

  it("Escape closes only the top pop-up: the open reject pop-up, then the detail", async () => {
    const { onClose } = renderPop(DETAIL);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Татгалзах" }));
    await screen.findByRole("heading", { name: "Хүсэлт татгалзах" });

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Хүсэлт татгалзах" })).toBeNull());
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape closes a detail that sits over a pop-up below it, and the pop-up below stays open", async () => {
    const client = makeClient();
    h.get.mockImplementation(async (path: string) =>
      path === DETAIL_PATH ? ok(DETAIL) : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
    const parentClose = vi.fn();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <Modal open onClose={parentClose} title="Доод цонх">
          Доод
        </Modal>
        <RequestDetailModal id={5} onClose={onClose} />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(parentClose).not.toHaveBeenCalled();
  });

  it("Болих closes a clean pop-up at once", async () => {
    const { onClose } = renderPop(DETAIL);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("Болих with typed input asks first and stays open when the answer is no", async () => {
    h.confirm.mockReturnValue(false);
    const { onClose } = renderPop({ ...DETAIL, needs_reason: true });
    await waitForForm();

    fireEvent.change(reasonBox() as HTMLInputElement, { target: { value: "Гэр бүл" } });
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    await waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a request that cannot be loaded (404) shows the load alert and no form", async () => {
    renderPop(null);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByRole("button", { name: "Батлах" })).toBeNull();
  });
});
