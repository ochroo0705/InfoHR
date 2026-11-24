import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaveTypeOut } from "../../api/leaveSetup";
import { Modal } from "../../widgets/Modal";
import { TypeModal } from "./TypeModal";

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

const TYPE: LeaveTypeOut = {
  id: 7,
  name: "Төлбөртэй чөлөө",
  is_paid: true,
  uses_annual_balance: false,
  is_active: false,
  order: 4,
  staff_may_request: true,
};

const SAVED = { error: "", field_errors: {}, form_errors: [], ok: true };
const REFUSED = { error: "", field_errors: {}, form_errors: [], ok: false };

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ ...REFUSED, ...data });
}

function postsTo(path: string): unknown[][] {
  return h.post.mock.calls.filter(([called]) => called === path);
}

function renderPop(id: number | null, onClose = vi.fn()) {
  h.get.mockImplementation(async (path: string) =>
    path === "/api/v1/leave/settings/types/{pk}"
      ? ok(TYPE)
      : { data: undefined, error: {}, response: { ok: false, status: 404 } },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TypeModal id={id} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

function box(name: string): HTMLInputElement {
  const el = document.querySelector<HTMLInputElement>(`input[name="${name}"]`);
  if (!el) throw new Error(`no ${name} box`);
  return el;
}

function checkbox(label: RegExp): HTMLInputElement {
  return screen.getByRole("checkbox", { name: label }) as HTMLInputElement;
}

function saveButton(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name: "Хадгалах" }) as HTMLButtonElement;
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Болих" });
}

describe("TypeModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
    h.post.mockImplementation(async () => answer({}));
  });

  afterEach(() => {
    cleanup();
  });

  it("the add pop-up starts with the defaults: active, staff may request, order 0, no delete", () => {
    renderPop(null);

    expect(screen.getByRole("heading", { name: "Чөлөөний төрөл нэмэх" })).toBeTruthy();
    expect(box("name").value).toBe("");
    expect(box("order").value).toBe("0");
    expect(checkbox(/Идэвхтэй/).checked).toBe(true);
    expect(checkbox(/Ажилтан хүсэлт гаргана/).checked).toBe(true);
    expect(checkbox(/Цалинтай/).checked).toBe(false);
    expect(checkbox(/Ээлжийн амралтаас хасна/).checked).toBe(false);
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
    expect(h.get).not.toHaveBeenCalled();
  });

  it("the fields carry their labels, the required marks and the help texts of the form", () => {
    renderPop(null);

    expect(screen.getByText(/Нэр \*/)).toBeTruthy();
    expect(screen.getByText(/Жагсаалтад гарах дараалал \*/)).toBeTruthy();
    expect(screen.getByText("Тэмдэглэгээ: энэ төрлийн чөлөө цалинтай эсэхийг харуулна.")).toBeTruthy();
    expect(screen.getByText("Авсан хоног ээлжийн амралтын эрх, үлдэгдлээс хасагдана.")).toBeTruthy();
    expect(screen.getByText("Унтраавал ажилтан өөрөө хүсэлт гаргаж чадахгүй; шууд бүртгэнэ.")).toBeTruthy();
  });

  it("the add save posts the full body to the create route and closes on ok", async () => {
    h.post.mockImplementation(async () => ok(SAVED));
    const { onClose } = renderPop(null);
    await waitForForm();

    fireEvent.change(box("name"), { target: { value: "Шинэ төрөл" } });
    fireEvent.click(checkbox(/Цалинтай/));
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/types", {
      body: {
        name: "Шинэ төрөл",
        is_paid: true,
        uses_annual_balance: false,
        is_active: true,
        order: 0,
        staff_may_request: true,
      },
    });
  });

  it("the edit pop-up loads the type and shows its values and the delete", async () => {
    renderPop(7);
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Чөлөөний төрөл засах" })).toBeTruthy();
    expect(box("name").value).toBe("Төлбөртэй чөлөө");
    expect(box("order").value).toBe("4");
    expect(checkbox(/Идэвхтэй/).checked).toBe(false);
    expect(checkbox(/Цалинтай/).checked).toBe(true);
    expect(screen.getByRole("button", { name: "Устгах" })).toBeTruthy();
    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/settings/types/{pk}", { params: { path: { pk: 7 } } });
  });

  it("the edit save posts to the type's own route", async () => {
    h.post.mockImplementation(async () => ok(SAVED));
    const { onClose } = renderPop(7);
    await waitForForm();

    fireEvent.click(checkbox(/Идэвхтэй/));
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/types/{pk}", {
      params: { path: { pk: 7 } },
      body: {
        name: "Төлбөртэй чөлөө",
        is_paid: true,
        uses_annual_balance: false,
        is_active: true,
        order: 4,
        staff_may_request: true,
      },
    });
  });

  it("a field message from a refused save shows under its field, the order too", async () => {
    h.post.mockImplementation(async () => answer({ field_errors: { order: ["Утга 0-32767 хооронд байна."] } }));
    renderPop(null);
    await waitForForm();

    fireEvent.click(saveButton());

    const message = await screen.findByText("Утга 0-32767 хооронд байна.");
    expect(message.closest("label")?.textContent).toContain("Жагсаалтад гарах дараалал");
  });

  it("the service's error and form errors show in the red box on top", async () => {
    h.post.mockImplementation(async () =>
      answer({ error: "Нэр давхардсан байна.", form_errors: ["Хадгалах боломжгүй."] }),
    );
    renderPop(null);
    await waitForForm();

    fireEvent.click(saveButton());

    expect(await screen.findByText("Нэр давхардсан байна.")).toBeTruthy();
    expect(screen.getByText("Хадгалах боломжгүй.")).toBeTruthy();
  });

  it("a double click on save posts once", async () => {
    h.post.mockImplementation(async () => answer({}));
    renderPop(null);
    await waitForForm();

    const button = saveButton();
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(postsTo("/api/v1/leave/settings/types")).toHaveLength(1);
  });

  it("delete asks first and posts to the delete route on yes, then closes", async () => {
    h.confirm.mockImplementation(async () => true);
    h.post.mockImplementation(async () => ok(SAVED));
    const { onClose } = renderPop(7);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.confirm).toHaveBeenCalledWith("Энэ төрлийг устгах уу?");
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/types/{pk}/delete", {
      params: { path: { pk: 7 } },
    });
  });

  it("delete does nothing when the question is answered no", async () => {
    h.confirm.mockImplementation(async () => false);
    renderPop(7);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(h.confirm).toHaveBeenCalled());
    expect(h.post).not.toHaveBeenCalled();
  });

  it("a type in use keeps the pop-up open with the refusal", async () => {
    h.confirm.mockImplementation(async () => true);
    h.post.mockImplementation(async () =>
      answer({ error: "Энэ төрлөөр чөлөө бүртгэгдсэн тул устгах боломжгүй." }),
    );
    const { onClose } = renderPop(7);
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    expect(await screen.findByText("Энэ төрлөөр чөлөө бүртгэгдсэн тул устгах боломжгүй.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("an unknown type shows the load failure instead of the form", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TypeModal id={99} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });

  it("an empty order is refused under its box and nothing is sent", async () => {
    renderPop(null);
    await waitForForm();

    fireEvent.change(box("name"), { target: { value: "Шинэ төрөл" } });
    fireEvent.change(box("order"), { target: { value: "" } });
    fireEvent.click(saveButton());

    const message = await screen.findByText("Энэ талбарыг бөглөнө үү.");
    expect(message.closest("label")?.textContent).toContain("Жагсаалтад гарах дараалал");
    expect(h.post).not.toHaveBeenCalled();
  });

  it("the edit delete is the solid red confirm style", async () => {
    renderPop(7);
    await waitForForm();

    expect(screen.getByRole("button", { name: "Устгах" }).className).toContain("bg-red-600");
  });

  it("while the save runs every button of the pop-up is locked", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderPop(null);
    await waitForForm();

    fireEvent.change(box("name"), { target: { value: "Шинэ төрөл" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(saveButton().disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Болих" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("while the delete runs the delete and the other buttons are locked, and a double click deletes once", async () => {
    h.confirm.mockImplementation(async () => true);
    h.post.mockImplementation(() => new Promise(() => {}));
    renderPop(7);
    await waitForForm();

    const remove = screen.getByRole("button", { name: "Устгах" }) as HTMLButtonElement;
    fireEvent.click(remove);
    fireEvent.click(remove);

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(h.confirm).toHaveBeenCalledTimes(1);
    expect(postsTo("/api/v1/leave/settings/types/{pk}/delete")).toHaveLength(1);
    expect(remove.disabled).toBe(true);
    expect(saveButton().disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Болих" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Escape closes only the top pop-up", async () => {
    const parentClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <Modal open onClose={parentClose} title="Доод цонх">
          Доод
        </Modal>
        <TypeModal id={null} onClose={onClose} />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(parentClose).not.toHaveBeenCalled();
  });
});
