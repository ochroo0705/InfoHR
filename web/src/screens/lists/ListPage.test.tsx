import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import type { ListPageOut } from "../../api/lists";
import { ListPage } from "./ListPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in SlotsPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

// The pop-up is replaced by a stub that shows which pop-up it is (its slug and pk, or "add") and closes through onClose.
vi.mock("./EntryFormModal", () => ({
  EntryFormModal: (props: { slug: string; pk?: number; onClose: () => void }) => (
    <div
      data-testid="entry-form"
      data-slug={props.slug}
      data-pk={props.pk === undefined ? "add" : String(props.pk)}
    >
      <button type="button" onClick={props.onClose}>
        Хаах тест
      </button>
    </div>
  ),
}));

const PAGE: ListPageOut = {
  slug: "bank",
  label: "Банк",
  columns: [{ name: "name", label: "Нэр" }],
  rows: [
    { id: 7, cells: ["Хаан банк"] },
    { id: -3, cells: ["Голомт банк"] },
  ],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function renderPage(slug: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/lists/${slug}/`]}>
        <Routes>
          <Route path="/lists/:slug/" element={<ListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ListPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.get.mockImplementation(async () => ok(PAGE));
  });

  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("draws the back link, the title, the «Нэмэх» button, the columns and the rows", async () => {
    renderPage("bank");

    expect(await screen.findByRole("heading", { name: "Банк" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← Жагсаалтууд" }).getAttribute("href")).toBe("/lists/");
    expect(screen.getByRole("button", { name: "Нэмэх" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Нэр" })).toBeTruthy();
    expect(screen.getByText("Хаан банк")).toBeTruthy();
    expect(screen.getByText("Голомт банк")).toBeTruthy();
  });

  it("sets the page title from the list label", async () => {
    renderPage("bank");

    await waitFor(() => expect(document.title).toBe("Банк · MACS Human Capital"));
  });

  it("asks the list page of the slug in the route", async () => {
    renderPage("bank");

    await screen.findByRole("heading", { name: "Банк" });
    expect(h.get.mock.calls[0][1]).toEqual({ params: { path: { slug: "bank" } } });
  });

  it("shows the empty row when the list has no entries", async () => {
    h.get.mockImplementation(async () => ok({ ...PAGE, rows: [] }));
    renderPage("bank");

    expect(await screen.findByText("бүртгэгдээгүй")).toBeTruthy();
  });

  it("opens the edit pop-up of the entry on a click", async () => {
    renderPage("bank");

    fireEvent.click(await screen.findByText("Голомт банк"));

    const form = screen.getByTestId("entry-form");
    expect(form.getAttribute("data-slug")).toBe("bank");
    expect(form.getAttribute("data-pk")).toBe("-3");
  });

  it("opens the edit pop-up of the entry on Enter", async () => {
    renderPage("bank");

    // Keys go to the focused row itself (tabIndex 0), not to a cell inside it.
    const row = (await screen.findByText("Хаан банк")).closest("tr") as HTMLElement;
    fireEvent.keyDown(row, { key: "Enter" });

    expect(screen.getByTestId("entry-form").getAttribute("data-pk")).toBe("7");
  });

  it("opens the add pop-up from «Нэмэх»", async () => {
    renderPage("bank");

    fireEvent.click(await screen.findByRole("button", { name: "Нэмэх" }));

    const form = screen.getByTestId("entry-form");
    expect(form.getAttribute("data-slug")).toBe("bank");
    expect(form.getAttribute("data-pk")).toBe("add");
  });

  it("removes the pop-up when it closes", async () => {
    renderPage("bank");

    fireEvent.click(await screen.findByRole("button", { name: "Нэмэх" }));
    expect(screen.getByTestId("entry-form")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Хаах тест" }));

    expect(screen.queryByTestId("entry-form")).toBeNull();
  });

  it("shows the forbidden screen for a user without the right", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage("bank");

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Нэмэх" })).toBeNull();
  });

  it("shows the not-found screen for an unknown list", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPage("nope");

    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Нэмэх" })).toBeNull();
  });
});
