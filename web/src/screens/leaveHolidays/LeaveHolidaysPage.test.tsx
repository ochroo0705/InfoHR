import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { LeaveHolidaysOut } from "../../api/leaveSetup";
import { LeaveHolidaysPage } from "./LeaveHolidaysPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const HOLIDAYS: LeaveHolidaysOut = {
  year: 2026,
  fixed_count: 12,
  empty_text: "Бүртгээгүй",
  holidays: [
    { date: "2026-01-01", name: "Шинэ жил" },
    { date: "2026-03-08", name: "Эмэгтэйчүүдийн өдөр" },
  ],
};

const EMPTY: LeaveHolidaysOut = { ...HOLIDAYS, holidays: [] };

const SAVED = { error: "", field_errors: {}, form_errors: [], ok: true };
const REFUSED = { error: "Огноо буруу эсвэл нэр хоосон байна.", field_errors: {}, form_errors: [], ok: false };

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function postsTo(path: string): unknown[][] {
  return h.post.mock.calls.filter(([called]) => called === path);
}

function renderPage(url = "/leave/holidays/?year=2026", holidays: LeaveHolidaysOut = HOLIDAYS) {
  h.get.mockImplementation(async () => ok(holidays));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <LeaveHolidaysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function dateBox(): HTMLInputElement {
  const el = document.querySelector<HTMLInputElement>('input[name="date"]');
  if (!el) throw new Error("no date box");
  return el;
}

function nameBox(): HTMLInputElement {
  return screen.getByRole("textbox", { name: "Нэр" }) as HTMLInputElement;
}

function addButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Нэмэх" }) as HTMLButtonElement;
}

describe("LeaveHolidaysPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.post.mockImplementation(async () => ok(SAVED));
  });

  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("shows the year title, the grey sentence and the prefill button with its count", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Баярын өдрүүд — 2026" })).toBeTruthy();
    expect(screen.getByText(/Бямба, ням гараг үргэлж амралтын өдөр\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Тогтмол баярыг бөглөх (12)" })).toBeTruthy();
    expect(document.title).toBe("Баярын өдрүүд · MACS Human Capital");
  });

  it("lists each holiday with its date, name and a delete button", async () => {
    renderPage();

    const row = (await screen.findByText("Эмэгтэйчүүдийн өдөр")).closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[0].textContent).toBe("2026-03-08");
    expect(cells[1].textContent).toBe("Эмэгтэйчүүдийн өдөр");
    expect(within(row).getByRole("button", { name: "Устгах" })).toBeTruthy();
  });

  it("the previous and next year links keep the address to the year", async () => {
    renderPage();
    await screen.findByRole("heading", { level: 1, name: "Баярын өдрүүд — 2026" });

    expect(screen.getByRole("link", { name: "← 2025" }).getAttribute("href")).toContain("year=2025");
    expect(screen.getByRole("link", { name: "2027 →" }).getAttribute("href")).toContain("year=2027");
  });

  it("the year in the address is sent to the server", async () => {
    renderPage("/leave/holidays/?year=2026");
    await screen.findByText("Шинэ жил");

    expect(h.get).toHaveBeenCalledWith("/api/v1/leave/holidays", { params: { query: { year: "2026" } } });
  });

  it("a year with no holidays says so in a full-width row", async () => {
    renderPage("/leave/holidays/?year=2030", { ...EMPTY, year: 2030 });

    const cell = await screen.findByText("Бүртгээгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("3");
  });

  it("add ok sends the year, date and name, then clears both boxes", async () => {
    renderPage();
    await screen.findByText("Шинэ жил");

    fireEvent.change(dateBox(), { target: { value: "2026-05-01" } });
    fireEvent.change(nameBox(), { target: { value: "Олон улсын хөдөлмөрийн баяр" } });
    fireEvent.click(addButton());

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/add")).toHaveLength(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/holidays/add", {
      body: { year: 2026, date: "2026-05-01", name: "Олон улсын хөдөлмөрийн баяр" },
    });
    await waitFor(() => expect(nameBox().value).toBe(""));
    expect(dateBox().value).toBe("");
  });

  it("add refused keeps both boxes and shows the message in the red box", async () => {
    h.post.mockImplementation(async () => ok(REFUSED));
    renderPage();
    await screen.findByText("Шинэ жил");

    fireEvent.change(dateBox(), { target: { value: "2027-05-01" } });
    fireEvent.change(nameBox(), { target: { value: "Буруу өдөр" } });
    fireEvent.click(addButton());

    expect(await screen.findByText("Огноо буруу эсвэл нэр хоосон байна.")).toBeTruthy();
    expect(nameBox().value).toBe("Буруу өдөр");
    expect(dateBox().value).toBe("2027-05-01");
  });

  it("a double click on add posts once", async () => {
    renderPage();
    await screen.findByText("Шинэ жил");

    fireEvent.change(dateBox(), { target: { value: "2026-05-01" } });
    fireEvent.change(nameBox(), { target: { value: "Баяр" } });
    const button = addButton();
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/add")).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(postsTo("/api/v1/leave/holidays/add")).toHaveLength(1);
  });

  it("delete posts the day's date for the year", async () => {
    renderPage();
    const row = (await screen.findByText("Шинэ жил")).closest("tr") as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/delete")).toHaveLength(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/holidays/delete", {
      body: { year: 2026, date: "2026-01-01" },
    });
  });

  it("prefill posts the year and the button shows the count", async () => {
    renderPage();
    await screen.findByText("Шинэ жил");

    fireEvent.click(screen.getByRole("button", { name: "Тогтмол баярыг бөглөх (12)" }));

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/prefill")).toHaveLength(1));
    expect(h.post).toHaveBeenCalledWith("/api/v1/leave/holidays/prefill", { body: { year: 2026 } });
  });

  it("while an add runs the add, prefill and delete buttons are locked", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderPage();
    const row = (await screen.findByText("Шинэ жил")).closest("tr") as HTMLElement;

    fireEvent.change(dateBox(), { target: { value: "2026-05-01" } });
    fireEvent.change(nameBox(), { target: { value: "Баяр" } });
    fireEvent.click(addButton());

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/add")).toHaveLength(1));
    expect(addButton().disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Тогтмол баярыг бөглөх (12)" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((within(row).getByRole("button", { name: "Устгах" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("while a prefill runs the buttons are locked, and a double click posts once", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await screen.findByText("Шинэ жил");

    const prefill = screen.getByRole("button", { name: "Тогтмол баярыг бөглөх (12)" }) as HTMLButtonElement;
    fireEvent.click(prefill);
    fireEvent.click(prefill);

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/prefill")).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(postsTo("/api/v1/leave/holidays/prefill")).toHaveLength(1);
    expect(prefill.disabled).toBe(true);
    expect(addButton().disabled).toBe(true);
  });

  it("while a delete runs the buttons are locked, and a double click posts once", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderPage();
    const row = (await screen.findByText("Шинэ жил")).closest("tr") as HTMLElement;
    const remove = within(row).getByRole("button", { name: "Устгах" }) as HTMLButtonElement;

    fireEvent.click(remove);
    fireEvent.click(remove);

    await waitFor(() => expect(postsTo("/api/v1/leave/holidays/delete")).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(postsTo("/api/v1/leave/holidays/delete")).toHaveLength(1);
    expect(remove.disabled).toBe(true);
    expect(addButton().disabled).toBe(true);
  });

  it("a failed load shows the load message", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/leave/holidays/"]}>
          <LeaveHolidaysPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
  });
});
