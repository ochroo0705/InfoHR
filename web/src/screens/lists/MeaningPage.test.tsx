import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { ListMeaningOut } from "../../api/lists";
import { MeaningPage } from "./MeaningPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in EmployeeLogPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

// Two rows: the bank has a current entry (pk 2); the district has none.
const MEANING: ListMeaningOut = {
  rows: [
    {
      key: "bank",
      label: "Банк",
      hint: "Цалин шилжүүлэх банк",
      current: 2,
      options: [
        { value: 1, label: "Хаан банк" },
        { value: 2, label: "Голомт банк" },
      ],
    },
    {
      key: "district",
      label: "Дүүрэг",
      hint: "Оршин суугаа дүүрэг",
      current: null,
      options: [
        { value: 3, label: "Баянзүрх" },
        { value: 4, label: "Сүхбаатар" },
      ],
    },
  ],
};

// What the server holds after a save: the district now has entry 4.
const MEANING_SAVED: ListMeaningOut = {
  rows: [
    { ...MEANING.rows[0], current: 1 },
    { ...MEANING.rows[1], current: 4 },
  ],
};

const OK = { ok: true, status: 200 };

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MeaningPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function bankBox() {
  return screen.getByRole("combobox", { name: /Банк/ }) as HTMLSelectElement;
}

function districtBox() {
  return screen.getByRole("combobox", { name: /Дүүрэг/ }) as HTMLSelectElement;
}

describe("MeaningPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders one labelled select per row with the current entry selected, and the template texts", async () => {
    h.get.mockImplementation(async () => ({ data: MEANING, error: undefined, response: OK }));
    renderPage();

    expect(await screen.findByRole("heading", { name: "Утгын холбоо" })).toBeTruthy();
    expect(bankBox().value).toBe("2");
    expect(districtBox().value).toBe("");
    expect(screen.getByText("Цалин шилжүүлэх банк")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← Жагсаалтууд" }).getAttribute("href")).toBe("/lists/");
    expect(screen.getAllByRole("option", { name: "— сонгоогүй —" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Хадгалах" })).toBeTruthy();
    expect(document.title).toBe("Утгын холбоо · MACS Human Capital");
  });

  it("posts every value, including the changed one, when saved", async () => {
    h.get.mockImplementation(async () => ({ data: MEANING, error: undefined, response: OK }));
    h.post.mockImplementation(async () => ({ data: { ok: true }, error: undefined, response: OK }));
    renderPage();
    await screen.findByRole("heading", { name: "Утгын холбоо" });

    fireEvent.change(districtBox(), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/lists/meaning", { body: { values: { bank: "2", district: "4" } } });
  });

  it("sends an empty value for a blank choice", async () => {
    h.get.mockImplementation(async () => ({ data: MEANING, error: undefined, response: OK }));
    h.post.mockImplementation(async () => ({ data: { ok: true }, error: undefined, response: OK }));
    renderPage();
    await screen.findByRole("heading", { name: "Утгын холбоо" });

    fireEvent.change(bankBox(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(h.post.mock.calls[0][1]).toEqual({ body: { values: { bank: "", district: "" } } });
  });

  it("shows the saved note and the fresh server values after the save", async () => {
    let saved = false;
    h.get.mockImplementation(async () => ({
      data: saved ? MEANING_SAVED : MEANING,
      error: undefined,
      response: OK,
    }));
    h.post.mockImplementation(async () => {
      saved = true;
      return { data: { ok: true }, error: undefined, response: OK };
    });
    renderPage();
    await screen.findByRole("heading", { name: "Утгын холбоо" });

    fireEvent.change(districtBox(), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Хадгалагдлаа")).toBeTruthy();
    await waitFor(() => expect(bankBox().value).toBe("1"));
    expect(districtBox().value).toBe("4");
  });

  it("shows the forbidden screen when the user has no right", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage();

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });
});
