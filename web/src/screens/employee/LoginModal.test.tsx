import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginModal } from "./LoginModal";

// fetch and Request are stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// CorrectionModal.test.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

const PASSWORD = "Tmp-Pass-4821";
const USERNAME_TAKEN = "Ийм нэвтрэх нэр бүртгэлтэй байна.";
const ALREADY_HAS_LOGIN = "Энэ ажилтанд нэвтрэх эрх аль хэдийн бий.";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let client: QueryClient;
let posts: string[] = [];
let answer: () => Promise<Response>;
let gate: Promise<void> | null = null;

// Answers the login POST through `answer`; every posted username is recorded.
function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname.endsWith("/api/v1/employees/7/login")) {
      const body = (await request.json()) as { username: string };
      posts.push(body.username);
      if (gate) await gate;
      return answer();
    }
    throw new Error(`unexpected request ${request.method} ${url.pathname}`);
  });
}

// The pop-up with its open state, as Header holds it. «Хаах» and «Болих» close it through onClose.
function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <QueryClientProvider client={client}>
      <LoginModal
        pk={7}
        open={open}
        onClose={() => {
          onClose();
          setOpen(false);
        }}
      />
    </QueryClientProvider>
  );
}

const usernameBox = () => document.querySelector<HTMLInputElement>("input[name='username']") as HTMLInputElement;
const dialog = () => screen.getByRole("dialog");

function typeUsername(value: string) {
  fireEvent.change(usernameBox(), { target: { value } });
}

function submitForm() {
  fireEvent.submit(usernameBox().closest("form") as HTMLFormElement);
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchMock.mockReset();
  posts = [];
  gate = null;
  answer = async () => jsonResponse(200, { username: "bat.bold", password: PASSWORD });
  route();
});

afterEach(() => {
  cleanup();
});

describe("LoginModal (Task 16b)", () => {
  it("shows the create-login form with one username box (max 150) and the buttons", () => {
    render(<Harness />);
    expect(within(dialog()).getByRole("heading", { name: "Нэвтрэх эрх үүсгэх" })).toBeTruthy();
    expect(usernameBox().maxLength).toBe(150);
    expect(screen.getByText("Нууц үг автоматаар үүснэ. Гарсны дараа ажилтанд өгнө; анх нэвтрэхдээ солино.")).toBeTruthy();
    expect(within(dialog()).getByRole("button", { name: "Болих" })).toBeTruthy();
    expect(within(dialog()).getByRole("button", { name: "Хадгалах" })).toBeTruthy();
  });

  it("a username field error sits under the box with aria-invalid, and no password is shown", async () => {
    answer = async () => jsonResponse(400, { field_errors: { username: [USERNAME_TAKEN] }, form_errors: [] });
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    expect(await screen.findByText(USERNAME_TAKEN)).toBeTruthy();
    expect(usernameBox().getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByText(PASSWORD)).toBeNull();
    expect(screen.queryByText("Түр нууц үг")).toBeNull();
  });

  it("a refusal without a box message shows its form error in the red box", async () => {
    answer = async () => jsonResponse(400, { field_errors: {}, form_errors: ["Энэ ажилтанд нэвтрэх эрх аль хэдийн бий."] });
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    const message = await screen.findByText("Энэ ажилтанд нэвтрэх эрх аль хэдийн бий.");
    expect(message.parentElement?.className).toBe("rounded bg-red-50 p-2 text-sm text-red-700");
    expect(usernameBox().getAttribute("aria-invalid")).toBeNull();
  });

  it("success shows the password pop-up with the exact texts and the password", async () => {
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    expect(await screen.findByRole("heading", { name: "Түр нууц үг" })).toBeTruthy();
    expect(screen.getByText("Нэвтрэх нэр")).toBeTruthy();
    expect(screen.getByText("bat.bold").className).toBe("mb-3 font-mono text-base");
    expect(screen.getByText("Түр нууц үг", { selector: "p" })).toBeTruthy();
    const box = screen.getByText(PASSWORD);
    expect(box.className).toBe(
      "mb-3 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-lg tracking-wider select-all",
    );
    expect(
      screen.getByText("Энэ нууц үгийг зөвхөн одоо нэг удаа харуулна. Ажилтанд өгөөд хадгалахгүй байгаарай.").className,
    ).toBe("text-sm text-red-700");
    expect(screen.getByText("Ажилтан анх нэвтрэхдээ нууц үгээ өөрөө солино.")).toBeTruthy();
    // The ✕ of the shell is also named «Хаах»; the password step's button is the one with its text.
    expect(screen.getByText("Хаах", { selector: "button" }).className).toContain("bg-violet-600");
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });

  it("the username is sent trimmed", async () => {
    render(<Harness />);
    typeUsername("  bat.bold  ");
    submitForm();
    await screen.findByText(PASSWORD);
    expect(posts).toEqual(["bat.bold"]);
  });

  it("the password is in no query and no mutation cache entry", async () => {
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    await screen.findByText(PASSWORD);
    const inQueries = client.getQueryCache().getAll().some((query) => JSON.stringify(query.state).includes(PASSWORD));
    expect(inQueries).toBe(false);
    await waitFor(() => {
      const inMutations = client
        .getMutationCache()
        .getAll()
        .some((mutation) => JSON.stringify(mutation.state).includes(PASSWORD));
      expect(inMutations).toBe(false);
    });
  });

  it("«Хаах» refetches the header, closes the pop-up and clears the password", async () => {
    const onClose = vi.fn();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(<Harness onClose={onClose} />);
    typeUsername("bat.bold");
    submitForm();
    await screen.findByText(PASSWORD);
    fireEvent.click(screen.getByText("Хаах", { selector: "button" }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7], exact: true });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(PASSWORD)).toBeNull();
  });

  it("Escape does not close the password step", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    typeUsername("bat.bold");
    submitForm();
    await screen.findByText(PASSWORD);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(PASSWORD)).toBeTruthy();
  });

  it("the password step has no ✕, and an outside click does nothing", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    typeUsername("bat.bold");
    submitForm();
    await screen.findByText(PASSWORD);
    expect(document.querySelector("[data-modal-x]")).toBeNull();
    const overlay = document.querySelector<HTMLElement>(".fixed.inset-0.z-50") as HTMLElement;
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(PASSWORD)).toBeTruthy();
  });

  it("a refused create (a form message) refetches the header and keeps the pop-up with its message", async () => {
    answer = async () => jsonResponse(400, { field_errors: {}, form_errors: [ALREADY_HAS_LOGIN] });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    expect(await screen.findByText(ALREADY_HAS_LOGIN)).toBeTruthy();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7], exact: true });
    expect(dialog()).toBeTruthy();
    expect(usernameBox().value).toBe("bat.bold");
  });

  it("a field error is linked to its box with aria-describedby", async () => {
    answer = async () => jsonResponse(400, { field_errors: { username: [USERNAME_TAKEN] }, form_errors: [] });
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    await screen.findByText(USERNAME_TAKEN);
    const describedBy = usernameBox().getAttribute("aria-describedby") as string;
    expect(document.getElementById(describedBy)?.textContent).toContain(USERNAME_TAKEN);
  });

  it("a double submit sends one request", async () => {
    let release: () => void = () => {};
    gate = new Promise<void>((resolve) => (release = resolve));
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    submitForm();
    release();
    await screen.findByText(PASSWORD);
    expect(posts).toEqual(["bat.bold"]);
  });

  it("a blank username is sent to the server, and its required message is shown", async () => {
    answer = async () =>
      jsonResponse(400, { field_errors: { username: ["Энэ талбарыг бөглөх шаардлагатай."] }, form_errors: [] });
    render(<Harness />);
    submitForm();
    expect(await screen.findByText("Энэ талбарыг бөглөх шаардлагатай.")).toBeTruthy();
    expect(posts).toEqual([""]);
  });

  it("a failed request with no message shows the general save line", async () => {
    answer = async () => jsonResponse(500, {});
    render(<Harness />);
    typeUsername("bat.bold");
    submitForm();
    expect(await screen.findByText("Мэдээллийг хадгалж чадсангүй.")).toBeTruthy();
    expect(screen.queryByText(PASSWORD)).toBeNull();
  });

  it("«Болих» closes the form step without a request", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.click(within(dialog()).getByRole("button", { name: "Болих" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
