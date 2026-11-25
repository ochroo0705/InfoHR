import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RecruitWriteResultOut } from "../../api/recruitment";
import { RejectModal } from "./RejectModal";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));
vi.mock("../../widgets/confirm", () => ({ confirm: vi.fn(async () => true) }));

const CANDIDATE = { id: 11, name: "Бат Болд" };
const SAVED: RecruitWriteResultOut = { ok: true, error: "", field_errors: {}, form_errors: [] };
const NO_REASON: RecruitWriteResultOut = {
  ok: false,
  error: "",
  field_errors: { reason: ["Татгалзсан шалтгаанаа бичнэ үү."] },
  form_errors: [],
};

function renderModal(onDone = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RejectModal candidate={CANDIDATE} onClose={onClose} onDone={onDone} />
    </QueryClientProvider>,
  );
  return { onDone, onClose };
}

function reasonBox(): HTMLTextAreaElement {
  return document.querySelector<HTMLTextAreaElement>('textarea[name="reason"]') as HTMLTextAreaElement;
}

function withdrawnBox(): HTMLInputElement {
  return document.querySelector<HTMLInputElement>('input[name="withdrawn"]') as HTMLInputElement;
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Татгалзах" }));
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.post.mockImplementation(async () => ({ data: SAVED, error: undefined, response: { ok: true, status: 200 } }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RejectModal", () => {
  it("names the candidate, marks the reason required, and explains what is kept", () => {
    renderModal();

    expect(screen.getByRole("heading", { name: "Ажил хүсэгчийг татгалзах" })).toBeTruthy();
    expect(screen.getByText("Бат Болд")).toBeTruthy();
    expect(screen.getByText("Татгалзсан шалтгаан *")).toBeTruthy();
    expect(reasonBox().getAttribute("placeholder")).toBe("Жишээ: туршлага хүрэлцэхгүй байна");
    expect(screen.getByText(/Шалтгаан шатны түүхэнд хадгалагдана/)).toBeTruthy();
    expect(screen.getByText("Татгалзсан биш, өөрөө хасагдсан бол сонгоно. Шалтгаан заавал биш.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Татгалзах" }) as HTMLButtonElement).className).toContain("bg-red-600");
  });

  it("drops the star from the reason when the candidate withdrew", () => {
    renderModal();

    fireEvent.click(withdrawnBox());

    expect(screen.getByText("Татгалзсан шалтгаан")).toBeTruthy();
    expect(screen.queryByText("Татгалзсан шалтгаан *")).toBeNull();
  });

  it("shows the server's message under the reason box, and clears it when the box is typed in", async () => {
    h.post.mockImplementation(async () => ({ data: NO_REASON, error: undefined, response: { ok: true, status: 200 } }));
    renderModal();

    submit();

    await waitFor(() => expect(screen.getByText("Татгалзсан шалтгаанаа бичнэ үү.")).toBeTruthy());
    expect(reasonBox().getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(reasonBox(), { target: { value: "Туршлага" } });
    expect(screen.queryByText("Татгалзсан шалтгаанаа бичнэ үү.")).toBeNull();
  });

  it("posts the reason and the withdrawn flag, then reports done", async () => {
    const { onDone } = renderModal();

    fireEvent.change(reasonBox(), { target: { value: "Туршлага хүрэлцэхгүй" } });
    submit();

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    const init = h.post.mock.calls[0][1] as { body: { reason: string; withdrawn: boolean } };
    expect(init.body).toEqual({ reason: "Туршлага хүрэлцэхгүй", withdrawn: false });
  });

  it("posts once when the button is clicked twice", async () => {
    const { onDone } = renderModal();
    fireEvent.change(reasonBox(), { target: { value: "Туршлага" } });

    submit();
    submit();

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("shows a refusal with no message as the general save text in the red box", async () => {
    h.post.mockImplementation(async () => ({
      data: { ok: false, error: "", field_errors: {}, form_errors: [] },
      error: undefined,
      response: { ok: true, status: 200 },
    }));
    renderModal();
    fireEvent.change(reasonBox(), { target: { value: "Туршлага" } });

    submit();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Мэдээллийг хадгалж чадсангүй."));
  });

  it("lets a withdrawn candidate go with no reason: posts withdrawn true, shows no reason message, and closes", async () => {
    const { onDone } = renderModal();

    fireEvent.click(withdrawnBox());
    expect(screen.queryByText("Татгалзсан шалтгаан *")).toBeNull();
    submit();

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    const init = h.post.mock.calls[0][1] as { body: { reason: string; withdrawn: boolean } };
    expect(init.body).toEqual({ reason: "", withdrawn: true });
    expect(screen.queryByText("Татгалзсан шалтгаанаа бичнэ үү.")).toBeNull();
  });

  it("cancels through Болих without posting", () => {
    const { onClose } = renderModal();

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(h.post).not.toHaveBeenCalled();
  });
});
