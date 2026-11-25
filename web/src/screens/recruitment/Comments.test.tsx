import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RecruitWriteResultOut } from "../../api/recruitment";
import { Comments, type CommentItem } from "./Comments";

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ONE: CommentItem = { id: 1, text: "Эхний мөр\nХоёр дахь мөр", by: "Болд Бат", at: "2026-11-20 10:30" };
const SAVED: RecruitWriteResultOut = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED: RecruitWriteResultOut = { ok: false, error: "Сэтгэгдэл хоосон байна.", field_errors: {}, form_errors: [] };

function renderComments(comments: CommentItem[] = [ONE]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Comments candidate={11} comments={comments} />
    </QueryClientProvider>,
  );
}

function box(): HTMLTextAreaElement {
  return screen.getByLabelText("Сэтгэгдэл") as HTMLTextAreaElement;
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.post.mockImplementation(async () => ({ data: SAVED, error: undefined, response: { ok: true, status: 200 } }));
});

afterEach(() => {
  cleanup();
});

describe("Comments", () => {
  it("lists each comment with its line breaks, author and time", () => {
    renderComments();

    const text = screen.getByText((content, element) => element?.tagName === "DIV" && content.startsWith("Эхний мөр"));
    expect(text.className).toContain("whitespace-pre-line");
    expect(screen.getByText("Болд Бат · 2026-11-20 10:30")).toBeTruthy();
  });

  it("says so when there are no comments, and still offers the box", () => {
    renderComments([]);

    expect(screen.getByText("Сэтгэгдэл бүртгэгдээгүй")).toBeTruthy();
    expect(box().getAttribute("placeholder")).toBe("Сэтгэгдэл бичих");
    expect(screen.getByRole("button", { name: "Сэтгэгдэл нэмэх" })).toBeTruthy();
  });

  it("posts the text, then clears the box", async () => {
    renderComments();
    fireEvent.change(box(), { target: { value: "Шинэ сэтгэгдэл" } });

    fireEvent.click(screen.getByRole("button", { name: "Сэтгэгдэл нэмэх" }));

    await waitFor(() => expect(box().value).toBe(""));
    const init = h.post.mock.calls[0][1] as { body: { text: string } };
    expect(init.body.text).toBe("Шинэ сэтгэгдэл");
  });

  it("keeps the typed text and shows the refusal above the box", async () => {
    h.post.mockImplementation(async () => ({ data: REFUSED, error: undefined, response: { ok: true, status: 200 } }));
    renderComments();
    fireEvent.change(box(), { target: { value: "   " } });

    fireEvent.click(screen.getByRole("button", { name: "Сэтгэгдэл нэмэх" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Сэтгэгдэл хоосон байна."));
    expect(box().value).toBe("   ");
  });

  it("posts once when the button is clicked twice", async () => {
    renderComments();
    fireEvent.change(box(), { target: { value: "Нэг" } });

    const button = screen.getByRole("button", { name: "Сэтгэгдэл нэмэх" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(box().value).toBe(""));
    expect(h.post).toHaveBeenCalledTimes(1);
  });
});
