import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListFormOut } from "../../api/lists";
import { EntryFormModal } from "./EntryFormModal";

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

const SLUG = "sizes";
const IN_USE_TEXT = "Энэ бичлэгийг ашиглаж байгаа тул устгах боломжгүй.";

// The add form: a required text box with a max length, a choice list of 3 (blank first), a number box.
const ADD_FORM: ListFormOut = {
  title: "Хэмжээ: шинэ бичлэг",
  can_delete: false,
  fields: [
    { name: "name", label: "Нэр", kind: "text", required: true, max_length: 50, value: "", choices: [], errors: [] },
    {
      name: "size",
      label: "Хэмжээ",
      kind: "select",
      required: false,
      max_length: null,
      value: "",
      choices: [
        { value: "", label: "" },
        { value: "S", label: "Жижиг" },
        { value: "M", label: "Дунд" },
      ],
      errors: [],
    },
    { name: "qty", label: "Тоо", kind: "number", required: false, max_length: null, value: "", choices: [], errors: [] },
  ],
};

// The edit form of entry 7: the name and choice are filled, and the entry can be deleted.
const EDIT_FORM: ListFormOut = {
  ...ADD_FORM,
  title: "Хэмжээ: засах",
  can_delete: true,
  fields: [
    { ...ADD_FORM.fields[0], value: "Том" },
    { ...ADD_FORM.fields[1], value: "M" },
    { ...ADD_FORM.fields[2], value: "3" },
  ],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}
function answer(data: Record<string, unknown>) {
  return ok({ ok: false, field_errors: {}, form_errors: [], ...data });
}

function renderModal(props: { pk?: number; onClose?: () => void; form?: ListFormOut } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = props.onClose ?? vi.fn();
  h.get.mockImplementation(async (path: string) =>
    path === "/api/v1/lists/{slug}/form" ? ok(props.form ?? ADD_FORM) : { data: undefined, error: {}, response: { ok: false, status: 404 } },
  );
  render(
    <QueryClientProvider client={client}>
      <EntryFormModal slug={SLUG} pk={props.pk} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Хадгалах" });
}

function boxOf(name: string): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
}

describe("EntryFormModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("add success posts every box and closes", async () => {
    h.post.mockResolvedValue(ok({ ok: true, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal();
    await waitForForm();

    fireEvent.change(boxOf("name"), { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/lists/{slug}", {
      params: { path: { slug: SLUG } },
      body: { values: { name: "Шинэ", size: "", qty: "" } },
    });
  });

  it("field error shows under its own box, in red", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { name: ["Нэр давтагдсан байна."] } }));
    const { onClose } = renderModal();
    await waitForForm();

    fireEvent.change(boxOf("name"), { target: { value: "Дунд" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Нэр давтагдсан байна.");
    expect(message.className).toContain("text-xs text-red-600");
    expect(message.closest("label")?.querySelector('input[name="name"]')).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("delete of an entry in use shows the message and stays open", async () => {
    h.confirm.mockResolvedValue(true);
    h.post.mockResolvedValue(answer({ form_errors: [IN_USE_TEXT] }));
    const { onClose } = renderModal({ pk: 7, form: EDIT_FORM });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    expect(await screen.findByText(IN_USE_TEXT)).toBeTruthy();
    expect(h.confirm).toHaveBeenCalledWith("Энэ бичлэгийг устгах уу?");
    expect(h.post).toHaveBeenCalledWith("/api/v1/lists/{slug}/{pk}/delete", {
      params: { path: { slug: SLUG, pk: "7" } },
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("Escape closes a pop-up that has no typed input", async () => {
    const { onClose } = renderModal();
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("a select field posts the value that was picked", async () => {
    h.post.mockResolvedValue(ok({ ok: true, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal();
    await waitForForm();

    fireEvent.change(boxOf("name"), { target: { value: "Шинэ" } });
    fireEvent.mouseDown(document.querySelector<HTMLSelectElement>('select[name="size"]')!);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Дунд" }));
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { values: { name: "Шинэ", size: "M" } } });
  });

  it("a required field carries the ' *' mark, an optional one does not", async () => {
    renderModal();
    await waitForForm();

    expect(boxOf("name").closest("label")?.textContent).toContain("Нэр *");
    expect(boxOf("qty").closest("label")?.textContent).not.toContain("*");
  });

  it("Устгах shows only in the edit pop-up of a deletable entry", async () => {
    const { onClose } = renderModal();
    await waitForForm();
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
    cleanup();

    renderModal({ pk: 7, form: { ...EDIT_FORM, can_delete: false } });
    await waitForForm();
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
    cleanup();

    renderModal({ pk: 7, form: EDIT_FORM, onClose });
    await waitForForm();
    expect(screen.getByRole("button", { name: "Устгах" })).toBeTruthy();
  });
});
