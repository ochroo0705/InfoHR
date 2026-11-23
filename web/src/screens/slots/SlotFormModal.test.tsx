import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SlotOptionsOut, SlotRowOut } from "../../api/slots";
import { SlotFormModal } from "./SlotFormModal";

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

const HINT = "Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна.";

const OPTIONS: SlotOptionsOut = {
  year: 2027,
  min_year: 2000,
  max_year: 2100,
  hint: HINT,
  positions: [
    { value: 1, label: "Нягтлан бодогч" },
    { value: 2, label: "Жолооч" },
  ],
  branches: [
    { value: 10, label: "Төв оффис" },
    { value: 11, label: "Салбар 2" },
  ],
  kinds: [
    { value: "Main", label: "Үндсэн" },
    { value: "Temporary", label: "Түр" },
  ],
};

const ROW: SlotRowOut = {
  id: 5,
  position: "Нягтлан бодогч",
  position_id: 1,
  branch: "Төв оффис",
  branch_id: 10,
  kind: "Main",
  kind_label: "Үндсэн",
  posts: 3,
  used: 1,
  free: 2,
  free_class: "",
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ id: null, field_errors: {}, form_errors: [], ok: false, ...data });
}

function renderModal(props: { row?: SlotRowOut; year?: number; onClose?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = props.onClose ?? vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SlotFormModal row={props.row} year={props.year ?? 2027} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

// The value of a posted box: a native select for a short list, a hidden field for a typing box.
function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Хадгалах" });
}

describe("SlotFormModal", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.confirm.mockReset();
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/slots/options"
        ? ok(OPTIONS)
        : { data: undefined, error: {}, response: { ok: false, status: 404 } },
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("add form defaults kind to Үндсэн and year to the page year", async () => {
    renderModal({ year: 2027 });
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Орон тоо нэмэх" })).toBeTruthy();
    expect(valueOf("kind")).toBe("Main");
    expect(valueOf("year")).toBe("2027");
    expect(screen.getByText(HINT)).toBeTruthy();
  });

  it("edit form shows the row values and the delete button", async () => {
    renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Орон тоо засах" })).toBeTruthy();
    expect(valueOf("position")).toBe("1");
    expect(valueOf("branch")).toBe("10");
    expect(valueOf("kind")).toBe("Main");
    expect(valueOf("qty")).toBe("3");
    expect(screen.getByRole("button", { name: "Устгах" })).toBeTruthy();
  });

  it("no delete button when adding", async () => {
    renderModal();
    await waitForForm();

    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
  });

  it("save sends the typed values and closes on ok", async () => {
    h.post.mockResolvedValue(ok({ ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.change(document.querySelector<HTMLInputElement>('input[name="qty"]')!, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledWith("/api/v1/slots/{pk}", {
      params: { path: { pk: 5 } },
      body: { position: 1, branch: 10, kind: "Main", year: 2027, qty: 4 },
    });
  });

  it("refused save shows form_errors and keeps the pop-up open", async () => {
    h.post.mockResolvedValue(answer({ form_errors: ["Ийм мөр аль хэдийн бүртгэлтэй."] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Ийм мөр аль хэдийн бүртгэлтэй.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("field errors show under their boxes", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { qty: ["Орон тоо буруу байна."] } }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Орон тоо буруу байна.");
    expect(message.className).toContain("text-red-600");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("delete asks first, then posts and closes", async () => {
    h.confirm.mockResolvedValue(true);
    h.post.mockResolvedValue(ok({ ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.confirm).toHaveBeenCalledWith("Энэ орон тооны мөрийг устгах уу?");
    expect(h.post).toHaveBeenCalledWith("/api/v1/slots/{pk}/delete", { params: { path: { pk: 5 } } });
  });

  it("delete refused (write denied) shows the text", async () => {
    h.confirm.mockResolvedValue(true);
    h.post.mockResolvedValue(answer({ form_errors: ["Энэ мэдээллийн санд бичих эрх байхгүй."] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));

    expect(await screen.findByText("Энэ мэдээллийн санд бичих эрх байхгүй.")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Escape on a dirty form asks before closing", async () => {
    h.confirm.mockResolvedValue(false);
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.change(document.querySelector<HTMLInputElement>('input[name="qty"]')!, { target: { value: "7" } });
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(h.confirm).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("an empty box goes as null and the server's text shows under that box", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { qty: ["Энэ талбарыг бөглөнө үү."] } }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.change(document.querySelector<HTMLInputElement>('input[name="qty"]')!, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Энэ талбарыг бөглөнө үү.");
    expect(message.closest("label")?.querySelector('input[name="qty"]')).toBeTruthy();
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { qty: null, position: 1, branch: 10 } });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a field error renders directly under its own box, inside the same label", async () => {
    h.post.mockResolvedValue(answer({ field_errors: { year: ["Жил буруу байна."] } }));
    renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Жил буруу байна.");
    const label = message.closest("label");
    expect(label?.querySelector('input[name="year"]')).toBeTruthy();
    expect(message.previousElementSibling?.getAttribute("name")).toBe("year");
  });

  it("double click on Устгах opens one confirm and sends at most one POST", async () => {
    h.confirm.mockResolvedValue(true);
    h.post.mockResolvedValue(ok({ ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    const remove = screen.getByRole("button", { name: "Устгах" });
    fireEvent.click(remove);
    fireEvent.click(remove);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.confirm).toHaveBeenCalledTimes(1);
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("confirm answered no sends no POST and the delete button works again", async () => {
    h.confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    h.post.mockResolvedValue(ok({ ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    await waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(h.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("double click on Хадгалах sends one request", async () => {
    h.post.mockResolvedValue(answer({ form_errors: ["Ийм мөр аль хэдийн бүртгэлтэй."] }));
    renderModal({ row: ROW, year: 2027 });
    await waitForForm();

    const save = screen.getByRole("button", { name: "Хадгалах" });
    fireEvent.click(save);
    fireEvent.click(save);

    await screen.findByText("Ийм мөр аль хэдийн бүртгэлтэй.");
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("an edited row whose position is not in the options keeps its own name and id", async () => {
    h.post.mockResolvedValue(ok({ ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const { onClose } = renderModal({
      row: { ...ROW, position: "Хасагдсан албан тушаал", position_id: 7 },
      year: 2027,
    });
    await waitForForm();

    expect(screen.getByText("Хасагдсан албан тушаал")).toBeTruthy();
    expect(valueOf("position")).toBe("7");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(h.post.mock.calls[0][1]).toMatchObject({ body: { position: 7 } });
  });
});
