import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LeaveApprovalOut, LeaveStringChoiceOut } from "../../api/leaveSetup";
import { ApprovalForm } from "./ApprovalForm";

// The API client is replaced by a stub that answers by path, so the real helpers and hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const STEP1: LeaveStringChoiceOut[] = [
  { value: "", label: "Батлахгүй" },
  { value: "manager", label: "Шууд удирдлага" },
  { value: "group:3", label: "Хүний нөөц" },
];
const STEP2: LeaveStringChoiceOut[] = [
  { value: "", label: "—" },
  { value: "group:3", label: "Хүний нөөц" },
];

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function answer(data: Record<string, unknown>) {
  return ok({ error: "", field_errors: {}, form_errors: [], ok: false, ...data });
}

function renderForm(approval: LeaveApprovalOut) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ApprovalForm approval={approval} step1Choices={STEP1} step2Choices={STEP2} />
    </QueryClientProvider>,
  );
}

// Picks an option of a select by its name, as a user does (the click list of Select).
function pick(name: string, label: string) {
  fireEvent.mouseDown(document.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!);
  // A list that is closing may still be in the page: the newest one is the one just opened.
  const lists = screen.getAllByRole("listbox");
  fireEvent.click(within(lists[lists.length - 1]).getByRole("option", { name: label }));
}

function savePosts(): unknown[][] {
  return h.post.mock.calls.filter(([path]) => path === "/api/v1/leave/settings/approval");
}

describe("ApprovalForm", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.post.mockImplementation(async () => answer({ ok: true }));
  });

  afterEach(() => {
    cleanup();
  });

  it("the second step is not shown while the first step is empty", () => {
    renderForm({ step1: "", step2: "" });

    expect(screen.getByRole("heading", { name: "Чөлөөний хүсэлтийг хэн батлах вэ" })).toBeTruthy();
    expect(screen.queryByText("Дараа нь батлах")).toBeNull();
  });

  it("choosing a first step shows the second step", () => {
    renderForm({ step1: "", step2: "" });

    pick("step1", "Шууд удирдлага");

    expect(screen.getByText("Дараа нь батлах")).toBeTruthy();
  });

  it("clearing the first step hides the second step and empties its value", async () => {
    renderForm({ step1: "manager", step2: "group:3" });

    pick("step1", "Батлахгүй");
    expect(screen.queryByText("Дараа нь батлах")).toBeNull();

    // Choosing the first step again shows the second step empty: the reset happened, not just the hiding.
    pick("step1", "Шууд удирдлага");
    expect(screen.getByText("Дараа нь батлах")).toBeTruthy();
    expect(document.querySelector<HTMLSelectElement>('select[name="step2"]')!.value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(savePosts()).toHaveLength(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/approval", {
      body: { step1: "manager", step2: "" },
    });
  });

  it("while the save runs the save button is locked", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderForm({ step1: "manager", step2: "" });

    const button = screen.getByRole("button", { name: "Хадгалах" }) as HTMLButtonElement;
    fireEvent.click(button);

    await waitFor(() => expect(savePosts()).toHaveLength(1));
    expect(button.disabled).toBe(true);
  });

  it("save posts both steps", async () => {
    renderForm({ step1: "", step2: "" });

    pick("step1", "Шууд удирдлага");
    pick("step2", "Хүний нөөц");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(savePosts()).toHaveLength(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/settings/approval", {
      body: { step1: "manager", step2: "group:3" },
    });
  });

  it("ok shows the saved line", async () => {
    h.post.mockImplementation(async () => answer({ ok: true }));
    renderForm({ step1: "manager", step2: "" });

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Хадгалагдлаа")).toBeTruthy();
  });

  it("a field message from a refused save shows under its box", async () => {
    h.post.mockImplementation(async () => answer({ field_errors: { step1: ["Жагсаалтаас сонгоно уу."] } }));
    renderForm({ step1: "manager", step2: "" });

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    const message = await screen.findByText("Жагсаалтаас сонгоно уу.");
    expect(message.closest("label")?.textContent).toContain("Чөлөө батлах");
    expect(screen.queryByText("Хадгалагдлаа")).toBeNull();
  });

  it("a form message from a refused save shows in the red box at the top", async () => {
    h.post.mockImplementation(async () => answer({ form_errors: ["Батлах хэрэглэгч олдсонгүй."] }));
    renderForm({ step1: "manager", step2: "" });

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Батлах хэрэглэгч олдсонгүй.")).toBeTruthy();
  });

  it("a double click posts once", async () => {
    renderForm({ step1: "manager", step2: "" });

    const button = screen.getByRole("button", { name: "Хадгалах" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByText("Хадгалагдлаа")).toBeTruthy());
    expect(savePosts()).toHaveLength(1);
  });
});
