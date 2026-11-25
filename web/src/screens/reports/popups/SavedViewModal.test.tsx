import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportViewFormOut } from "../../../api/reports";
import { SAVE_FAILED_TEXT } from "../../employee/PageForm";
import { SavedViewModal, type SavedViewTarget } from "./SavedViewModal";
import { VIEW_TEXT } from "./popupTexts";

// The API client is replaced by a stub that answers by path; the real hooks run. Navigation is a spy.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), navigate: vi.fn() }));

vi.mock("../../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router")>()),
  useNavigate: () => h.navigate,
}));

const KEY = "staff";
const NEW_FORM: ReportViewFormOut = {
  title: "Харагдац хадгалах",
  can_delete: false,
  is_default: false,
  name: "",
  query: "q=a&sort=-name",
  view_id: null,
  visibility: "",
};
const EDIT_FORM: ReportViewFormOut = {
  title: "Харагдац засах",
  can_delete: true,
  is_default: false,
  name: "Миний",
  query: "",
  view_id: 7,
  visibility: "private",
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}
function answer(data: Record<string, unknown>) {
  return ok({ ok: false, redirect: "", error: "", field_errors: {}, form_errors: [], ...data });
}
function failed(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

// Answers the form read by path: the «new» form for the report, or the «edit» form of view 7 (or a failure).
function answerForms(form: ReportViewFormOut | number) {
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/reports/{key}/views/new" || path === "/api/v1/reports/views/{pk}") {
      return typeof form === "number" ? failed(form) : ok(form);
    }
    return failed(404);
  });
}

function renderPop(target: SavedViewTarget, form: ReportViewFormOut | number = target.mode === "new" ? NEW_FORM : EDIT_FORM) {
  answerForms(form);
  const client = makeClient();
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SavedViewModal reportKey={KEY} target={target} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose, client };
}

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

function nameBox(): HTMLInputElement {
  const el = document.querySelector<HTMLInputElement>('input[name="name"]');
  if (!el) throw new Error("no name box");
  return el;
}

function radio(value: "shared" | "private"): HTMLInputElement {
  const el = document.querySelector<HTMLInputElement>(`input[name="visibility"][value="${value}"]`);
  if (!el) throw new Error(`no ${value} radio`);
  return el;
}

function saveButton(): HTMLButtonElement {
  return within(dialog()).getByRole("button", { name: VIEW_TEXT.save }) as HTMLButtonElement;
}

async function waitForForm() {
  await screen.findByRole("button", { name: VIEW_TEXT.save });
}

const NEW_TARGET: SavedViewTarget = { mode: "new", query: "?q=a&sort=-name" };
const EDIT_TARGET: SavedViewTarget = { mode: "edit", pk: 7 };

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.navigate.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SavedViewModal", () => {
  it("new_prefills_blank_name_shared_and_posts_query", async () => {
    h.post.mockResolvedValue(answer({ field_errors: {}, form_errors: [] }));
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    expect(nameBox().value).toBe("");
    expect(radio("shared").checked).toBe(true);
    expect(radio("private").checked).toBe(false);
    expect(screen.getByRole("checkbox")).toBeTruthy();

    fireEvent.change(nameBox(), { target: { value: "Миний" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/reports/{key}/views", {
      params: { path: { key: KEY } },
      body: { name: "Миний", visibility: "shared", is_default: false, query: "q=a&sort=-name" },
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("blank_name_shows_server_error", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { name: ["Нэрээ оруулна уу."] } }));
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.click(saveButton());

    const message = await screen.findByText("Нэрээ оруулна уу.");
    expect(message.className).toContain("text-xs text-red-600");
    expect(message.closest("label")?.querySelector('input[name="name"]')).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("duplicate_name_shows_error_under_name_and_stays_open", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { name: ["Ийм нэртэй харагдац байна."] } }));
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Дубль" } });
    fireEvent.click(saveButton());

    const message = await screen.findByText("Ийм нэртэй харагдац байна.");
    expect(message.closest("label")?.querySelector('input[name="name"]')).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(h.navigate).not.toHaveBeenCalled();
    expect(saveButton()).toBeTruthy();

    // Typing in the name clears its error.
    fireEvent.change(nameBox(), { target: { value: "Дубль 2" } });
    expect(screen.queryByText("Ийм нэртэй харагдац байна.")).toBeNull();
  });

  it("private_hides_default_checkbox", async () => {
    renderPop(NEW_TARGET);
    await waitForForm();

    expect(screen.getByRole("checkbox")).toBeTruthy();

    fireEvent.click(radio("private"));
    expect(screen.queryByRole("checkbox")).toBeNull();

    fireEvent.click(radio("shared"));
    expect(screen.getByRole("checkbox")).toBeTruthy();
  });

  it("save_ok_navigates_to_returned_address", async () => {
    h.post.mockResolvedValue(ok({ ok: true, redirect: "/reports/staff/?view=9", error: "", field_errors: {}, form_errors: [] }));
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Шинэ" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.navigate).toHaveBeenCalledWith("/reports/staff/?view=9");
  });

  it("edit_prefills_current_values", async () => {
    renderPop(EDIT_TARGET);
    await waitForForm();

    expect(nameBox().value).toBe("Миний");
    expect(radio("private").checked).toBe(true);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(within(dialog()).getByRole("button", { name: VIEW_TEXT.delete })).toBeTruthy();
    expect(h.get).toHaveBeenCalledWith("/api/v1/reports/views/{pk}", { params: { path: { pk: 7 } } });
  });

  it("edit_ok_closes_and_refreshes_page_query", async () => {
    h.post.mockResolvedValue(ok({ ok: true, redirect: "", error: "", field_errors: {}, form_errors: [] }));
    const { onClose, client } = renderPop(EDIT_TARGET, { ...EDIT_FORM, visibility: "shared", is_default: true });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Шинэ нэр" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/reports/views/{pk}", {
      params: { path: { pk: 7 } },
      body: { name: "Шинэ нэр", visibility: "shared", is_default: true, query: "" },
    });
    expect(h.navigate).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["reports"] });
  });

  it("delete_asks_then_posts_then_navigates_to_bare_report", async () => {
    h.post.mockResolvedValue(ok({ ok: true, redirect: "/reports/staff/", error: "", field_errors: {}, form_errors: [] }));
    const { onClose } = renderPop(EDIT_TARGET);
    await waitForForm();

    fireEvent.click(within(dialog()).getByRole("button", { name: VIEW_TEXT.delete }));

    expect(screen.getByText(VIEW_TEXT.deleteConfirm)).toBeTruthy();
    expect(h.post).not.toHaveBeenCalled();

    fireEvent.click(within(dialog()).getByRole("button", { name: VIEW_TEXT.delete }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/reports/views/{pk}/delete", { params: { path: { pk: 7 } } });
    expect(h.navigate).toHaveBeenCalledWith("/reports/staff/");
  });

  it("edit_of_missing_view_shows_not_found_and_close", async () => {
    const { onClose } = renderPop(EDIT_TARGET, 404);

    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: VIEW_TEXT.save })).toBeNull();

    fireEvent.click(within(dialog()).getByRole("button", { name: VIEW_TEXT.cancel }));
    expect(onClose).toHaveBeenCalled();
  });

  it("403_shows_forbidden_text", async () => {
    renderPop(NEW_TARGET, 403);

    expect(
      await screen.findByText(
        "Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: VIEW_TEXT.save })).toBeNull();
  });

  it("private_after_default_posts_is_default_false", async () => {
    h.post.mockResolvedValue(answer({ field_errors: {}, form_errors: [] }));
    renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Хувийн" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(radio("private"));
    fireEvent.click(saveButton());

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { visibility: "private", is_default: false } });
  });

  it("edit_private_after_default_posts_is_default_false", async () => {
    h.post.mockResolvedValue(answer({ field_errors: {}, form_errors: [] }));
    renderPop(EDIT_TARGET, { ...EDIT_FORM, visibility: "shared", is_default: true });
    await waitForForm();

    fireEvent.click(radio("private"));
    fireEvent.click(saveButton());

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { visibility: "private", is_default: false } });
  });

  it("refused_error_string_shows_in_red_box", async () => {
    h.post.mockResolvedValue(answer({ error: "Харагдац олдсонгүй." }));
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Шинэ" } });
    fireEvent.click(saveButton());

    const message = await screen.findByText("Харагдац олдсонгүй.");
    expect(message.tagName).toBe("P");
    expect(message.className).toContain("bg-red-50");
    expect(message.className).toContain("text-red-700");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("failed_request_shows_save_failed_text", async () => {
    h.post.mockResolvedValue({ data: undefined, error: {}, response: { ok: false, status: 500 } });
    const { onClose } = renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Шинэ" } });
    fireEvent.click(saveButton());

    expect(await screen.findByText(SAVE_FAILED_TEXT)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("is_default_field_error_shows_under_checkbox", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { is_default: ["Үндсэн харагдац аль хэдийн байна."] } }));
    renderPop(NEW_TARGET);
    await waitForForm();

    fireEvent.change(nameBox(), { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(saveButton());

    const message = await screen.findByText("Үндсэн харагдац аль хэдийн байна.");
    expect(message.className).toContain("text-xs text-red-600");
    expect(message.parentElement?.querySelector('input[name="is_default"]')).toBeTruthy();
  });
});
