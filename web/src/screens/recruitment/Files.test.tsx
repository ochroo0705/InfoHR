import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RecruitWriteResultOut } from "../../api/recruitment";
import { Files, type FileItem } from "./Files";

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const CV: FileItem = { id: 5, name: "cv-bat.pdf", uploaded: "2026-11-20", by: "Болд Бат" };
const SAVED: RecruitWriteResultOut = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED: RecruitWriteResultOut = {
  ok: false,
  error: "Файл хоосон байна.",
  field_errors: {},
  form_errors: [],
};

function renderFiles(props: { files?: FileItem[]; canManage?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Files
        candidate={11}
        files={props.files ?? [CV]}
        canManage={props.canManage ?? true}
        extensions="pdf, doc, docx"
        maxMb={10}
      />
    </QueryClientProvider>,
  );
}

function pickFile(file: File) {
  fireEvent.change(screen.getByLabelText("Файл"), { target: { files: [file] } });
}

function uploadButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Файл хавсаргах" }) as HTMLButtonElement;
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.post.mockImplementation(async () => ({ data: SAVED, error: undefined, response: { ok: true, status: 200 } }));
});

afterEach(() => {
  cleanup();
});

describe("Files", () => {
  it("draws each file as a plain link to its download, with the upload and the date line", () => {
    renderFiles();

    const link = screen.getByRole("link", { name: "cv-bat.pdf" });
    expect(link.getAttribute("href")).toBe("/api/v1/recruitment/files/5");
    expect(link.hasAttribute("download")).toBe(false);
    expect(screen.getByText("2026-11-20 · Болд Бат")).toBeTruthy();
  });

  it("says so when there are no files", () => {
    renderFiles({ files: [] });

    expect(screen.getByText("Файл бүртгэгдээгүй")).toBeTruthy();
  });

  it("shows the upload box to a manager with the allowed types and the size limit", () => {
    renderFiles();

    expect(screen.getByText("Файл сонгох")).toBeTruthy();
    expect(screen.getByText("pdf, doc, docx · 10 MB хүртэл")).toBeTruthy();
    expect(uploadButton().disabled).toBe(true);
  });

  it("hides the upload box from a hiring manager, who still sees the files", () => {
    renderFiles({ canManage: false });

    expect(screen.queryByLabelText("Файл")).toBeNull();
    expect(screen.queryByRole("button", { name: "Файл хавсаргах" })).toBeNull();
    expect(screen.getByRole("link", { name: "cv-bat.pdf" })).toBeTruthy();
  });

  it("names the chosen file and enables the button", () => {
    renderFiles();

    pickFile(new File(["x"], "anket.docx"));

    expect(screen.getByText("anket.docx")).toBeTruthy();
    expect(uploadButton().disabled).toBe(false);
  });

  it("posts the chosen file as the file part of a multipart body", async () => {
    renderFiles();
    pickFile(new File(["x"], "anket.docx"));

    fireEvent.click(uploadButton());

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    const init = h.post.mock.calls[0][1] as { bodySerializer: () => FormData };
    const form = init.bodySerializer();
    expect(form).toBeInstanceOf(FormData);
    expect((form.get("file") as File).name).toBe("anket.docx");
  });

  it("shows a refusal in red and keeps the chosen file", async () => {
    h.post.mockImplementation(async () => ({ data: REFUSED, error: undefined, response: { ok: true, status: 200 } }));
    renderFiles();
    pickFile(new File([""], "empty.pdf"));

    fireEvent.click(uploadButton());

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Файл хоосон байна."));
    expect(screen.getByText("empty.pdf")).toBeTruthy();
  });

  it("clears the chosen name and the input after a saved upload", async () => {
    renderFiles();
    pickFile(new File(["x"], "anket.docx"));

    fireEvent.click(uploadButton());

    await waitFor(() => expect(screen.queryByText("anket.docx")).toBeNull());
    // The live name span is empty again, and with no file chosen the button is locked. (The input's own value reads as
    // empty in jsdom either way, so it is not asserted here.)
    const live = document.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toBe("");
    expect(uploadButton().disabled).toBe(true);
  });
});
