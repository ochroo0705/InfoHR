import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RecruitWriteResultOut } from "../../api/recruitment";
import { CandidateModal } from "./CandidateModal";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), confirm: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));
vi.mock("../../widgets/confirm", () => ({ confirm: (...args: unknown[]) => h.confirm(...args) }));

const VACANCY = { id: 5, title: "Бухгалтер" };
const NOT_OPEN = "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. Эхлээд ажлын байрыг нээнэ үү.";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

const SAVED: RecruitWriteResultOut = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED_SURNAME: RecruitWriteResultOut = {
  ok: false,
  error: "",
  field_errors: { surname: ["Энэ талбарыг бөглөнө үү."] },
  form_errors: [],
};
const REFUSED_NOT_OPEN: RecruitWriteResultOut = { ok: false, error: NOT_OPEN, field_errors: {}, form_errors: [] };

function renderModal(props: { onClose?: () => void; onSaved?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = props.onClose ?? vi.fn();
  const onSaved = props.onSaved ?? vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <CandidateModal vacancy={VACANCY} onClose={onClose} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { onClose, onSaved, ...view };
}

function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

function typeIn(name: string, value: string) {
  fireEvent.change(document.querySelector(`[name="${name}"]`) as HTMLInputElement, { target: { value } });
}

// The body of the add request on the wire.
function postedBody(): Record<string, string> {
  const call = h.post.mock.calls[0];
  return (call[1] as { body: Record<string, string> }).body;
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.confirm.mockReset();
  h.post.mockImplementation(async () => ok(SAVED));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CandidateModal", () => {
  it("names the pop-up, shows the vacancy under its title, and draws the six fields in order", () => {
    renderModal();

    expect(screen.getByRole("heading", { name: "Ажил хүсэгч нэмэх" })).toBeTruthy();
    expect(screen.getByText("Бухгалтер")).toBeTruthy();
    const labels = Array.from(document.querySelectorAll("form label")).map((label) => label.textContent ?? "");
    const order = ["Овог", "Нэр", "Утас", "И-мэйл", "Эх сурвалж", "Тэмдэглэл"];
    const found = order.map((text) => labels.findIndex((label) => label.startsWith(text)));
    expect(found.every((index) => index >= 0)).toBe(true);
    expect([...found].sort((a, b) => a - b)).toEqual(found);
    expect(labels.find((label) => label.startsWith("Овог"))).toContain("*");
    expect(labels.find((label) => label.startsWith("Нэр"))).toContain("*");
    expect(labels.find((label) => label.startsWith("Утас"))?.includes("*")).toBe(false);
  });

  it("lets the notes span two columns and offers the five source suggestions", () => {
    renderModal();

    const notes = document.querySelector("textarea[name=notes]")!;
    expect(notes.closest("label")?.className).toContain("md:col-span-2");
    const source = document.querySelector<HTMLInputElement>("input[name=source]")!;
    const list = document.getElementById(source.getAttribute("list") ?? "");
    expect(list).not.toBeNull();
    const options = Array.from(list!.querySelectorAll("option")).map((option) => option.value);
    expect(options).toEqual(["Танилын санал", "Вэбсайт", "Ажлын зар", "Биечлэн ирсэн", "Бусад"]);
  });

  it("a saved candidate posts the six fields, reports the save and closes", async () => {
    const { onClose, onSaved } = renderModal();

    typeIn("surname", "Бат");
    typeIn("given_name", "Болд");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
    expect(h.post.mock.calls[0][0]).toBe("/api/v1/recruitment/vacancies/{pk}/candidates");
    expect(postedBody()).toMatchObject({ surname: "Бат", given_name: "Болд" });
  });

  it("a refused add shows the field message under its box and keeps the typed values", async () => {
    h.post.mockImplementation(async () => ok(REFUSED_SURNAME));
    const { onClose, onSaved } = renderModal();

    typeIn("given_name", "Болд");
    typeIn("phone", "99112233");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Энэ талбарыг бөглөнө үү.");
    expect(document.querySelector("input[name=surname]")!.closest("label")!.contains(message)).toBe(true);
    expect(valueOf("given_name")).toBe("Болд");
    expect(valueOf("phone")).toBe("99112233");
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("when the vacancy was closed meanwhile the form becomes the amber text with a «Хаах» button", async () => {
    h.post.mockImplementation(async () => ok(REFUSED_NOT_OPEN));
    const { onClose } = renderModal();

    typeIn("surname", "Бат");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const text = await screen.findByText(NOT_OPEN);
    expect(text.className).toContain("text-amber-800");
    expect(document.querySelector("input[name=surname]")).toBeNull();
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    // The ✕ of the pop-up is also named «Хаах»; the text button is the one with the word as its text.
    const textButton = screen.getAllByRole("button", { name: "Хаах" }).find((button) => button.textContent === "Хаах");
    fireEvent.click(textButton as HTMLButtonElement);
    expect(onClose).toHaveBeenCalled();
  });

  it("a double click posts once", async () => {
    let finish: (value: unknown) => void = () => undefined;
    h.post.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    renderModal();

    typeIn("surname", "Бат");
    typeIn("given_name", "Болд");
    const button = screen.getByRole("button", { name: "Хадгалах" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.submit(button.closest("form") as HTMLFormElement);
    await waitFor(() => expect(h.post).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(h.post).toHaveBeenCalledTimes(1);
    finish(ok(SAVED));
  });
});
