import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ListFormOut } from "../../api/lists";
import { QuickAddModal } from "./QuickAddModal";

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

// A district-like list: a name box and a required parent (city) select, plus a plain text box.
const FORM: ListFormOut = {
  title: "Сум, дүүрэг",
  can_delete: false,
  fields: [
    { name: "name", label: "Нэр", kind: "text", required: true, value: "", errors: [], choices: [], max_length: 100 },
    {
      name: "city",
      label: "Аймаг, хот",
      kind: "select",
      required: true,
      value: "",
      errors: [],
      max_length: null,
      choices: [
        { value: "", label: "— сонгоогүй —" },
        { value: "1", label: "Улаанбаатар" },
        { value: "2", label: "Дархан" },
      ],
    },
    { name: "code", label: "Код", kind: "text", required: false, value: "", errors: [], choices: [], max_length: 10 },
  ],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function renderModal(
  props: { initialName?: string; parentValue?: string; onDone?: () => void; onClose?: () => void } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onDone = props.onDone ?? vi.fn();
  const onClose = props.onClose ?? vi.fn();
  render(
    <QueryClientProvider client={client}>
      <QuickAddModal
        slug="district"
        label="Сум, дүүрэг"
        initialName={props.initialName ?? ""}
        parentValue={props.parentValue}
        onDone={onDone}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onDone, onClose };
}

// The value of a posted box: a native select for a short list, a hidden field for a typing box.
function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Хадгалах" });
}

describe("QuickAddModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/lists/{slug}/form" ? ok(FORM) : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("opens with the title and the typed name filled", async () => {
    renderModal({ initialName: "Баянзүрх" });
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Сум, дүүрэг: шинэ бичлэг" })).toBeTruthy();
    expect(valueOf("name")).toBe("Баянзүрх");
    expect(valueOf("city")).toBe("");
  });

  it("pre-fills the required parent select from parentValue", async () => {
    renderModal({ initialName: "Баянзүрх", parentValue: "2" });
    await waitForForm();

    expect(valueOf("city")).toBe("2");
  });

  it("success posts every field, calls onDone with the reply and closes", async () => {
    h.post.mockResolvedValue(ok({ value: 7, label: "Баянзүрх", existed: false }));
    const { onDone, onClose } = renderModal({ initialName: "Баянзүрх", parentValue: "1" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/lists/{slug}/quick", {
      params: { path: { slug: "district" } },
      body: { values: { name: "Баянзүрх", city: "1", code: "" } },
    });
    expect(onDone).toHaveBeenCalledWith({ value: 7, label: "Баянзүрх", existed: false });
  });

  it("a 400 shows the field errors and the first form error and stays open", async () => {
    h.post.mockResolvedValue({
      data: undefined,
      error: { error: "Аймаг, хот заавал сонгоно.", field_errors: { city: ["Аймаг, хот заавал сонгоно."] } },
      response: { ok: false, status: 400 },
    });
    const { onDone, onClose } = renderModal({ initialName: "Баянзүрх" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    // The same text shows twice: the field message under the box and the form error at the top.
    const messages = await screen.findAllByText("Аймаг, хот заавал сонгоно.");
    const fieldMessage = messages.find((el) => el.className.includes("text-red-600"));
    expect(fieldMessage).toBeTruthy();
    expect(messages.some((el) => el.className.includes("text-red-700") || el.closest(".text-red-700"))).toBe(true);
    expect(onClose).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("existed true is passed through to onDone unchanged", async () => {
    h.post.mockResolvedValue(ok({ value: 3, label: "Баянзүрх", existed: true }));
    const { onDone, onClose } = renderModal({ initialName: "баянзүрх", parentValue: "1" });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onDone).toHaveBeenCalledWith({ value: 3, label: "Баянзүрх", existed: true });
  });
});
