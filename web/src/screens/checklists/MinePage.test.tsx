import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import type { ChecklistMineItemOut } from "../../api/checklists";
import { MinePage } from "./MinePage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in ListsIndexPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const OVERDUE: ChecklistMineItemOut = {
  id: 3,
  title: "Лаборатори",
  employee: "Бат Болд",
  kind_label: "Ажилд орох",
  due: "2026-11-20",
  overdue: true,
};
const LATER: ChecklistMineItemOut = {
  id: 4,
  title: "Нэвтрэх эрх",
  employee: "Сара Од",
  kind_label: "Ажлаас гарах",
  due: "2026-12-01",
  overdue: false,
};

// What the server answers for «Миний даалгавар»; tests change it to mimic a tick.
let items: ChecklistMineItemOut[] = [];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/checklists/mine/"]}>
        <Routes>
          <Route path="/checklists/mine/" element={<MinePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function tickCalls() {
  return h.post.mock.calls.filter((call) => /\/tick$/.test(String(call[0])));
}

beforeEach(() => {
  items = [OVERDUE, LATER];
  h.get.mockReset();
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/checklists/mine") {
      return { data: { items }, error: undefined, response: { ok: true, status: 200 } };
    }
    return { data: undefined, error: {}, response: { ok: false, status: 404 } };
  });
  h.post.mockReset();
  h.post.mockImplementation(async () => ({ data: undefined, error: undefined, response: { ok: true, status: 204 } }));
  document.title = "start";
});

afterEach(() => {
  cleanup();
});

describe("MinePage", () => {
  it("renders the title, the count and one row per task", async () => {
    renderPage();

    const heading = await screen.findByRole("heading", { level: 1, name: /Миний даалгавар/ });
    expect(heading.querySelector("span")?.textContent).toBe("2");
    expect(screen.getByText("Лаборатори")).toBeTruthy();
    expect(screen.getByText("Нэвтрэх эрх")).toBeTruthy();
    // The employee name and the kind pill are separate elements, so each is matched on its own.
    expect(screen.getByText(/Бат Болд/).textContent).toBe("Бат Болд · Ажилд орох");
    expect(screen.getByText("Ажилд орох").className).toContain("rounded");
    expect(screen.getByText(/Сара Од/).textContent).toBe("Сара Од · Ажлаас гарах");
    expect(screen.getAllByText("Хийгдсэн")).toHaveLength(2);
    expect(document.title).toBe("Миний даалгавар · MACS Human Capital");
  });

  it("marks an overdue due date red and bold, and leaves the others grey", async () => {
    renderPage();

    const overdue = await screen.findByText("Хугацаа 2026-11-20");
    expect(overdue.className).toContain("text-red-700");
    expect(overdue.className).toContain("font-medium");

    const later = screen.getByText("Хугацаа 2026-12-01");
    expect(later.className).toContain("text-slate-500");
    expect(later.className).not.toContain("text-red-700");
  });

  it("shows the empty text and no list when the user has no open tasks", async () => {
    items = [];
    renderPage();

    expect(await screen.findByText("Таныг хүлээж буй даалгавар алга.")).toBeTruthy();
    expect(screen.queryByText("Хийгдсэн")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).querySelector("span")?.textContent).toBe("0");
  });

  it("a tick posts to the task and the row leaves the list after the refetch", async () => {
    renderPage();
    await screen.findByText("Лаборатори");

    h.post.mockImplementationOnce(async () => {
      items = [LATER];
      return { data: undefined, error: undefined, response: { ok: true, status: 204 } };
    });
    fireEvent.click(screen.getAllByText("Хийгдсэн")[0]);

    await waitFor(() => expect(screen.queryByText("Лаборатори")).toBeNull());
    expect(tickCalls()).toHaveLength(1);
    expect(h.post.mock.calls[0][0]).toBe("/api/v1/checklists/tasks/{pk}/tick");
    expect(h.post.mock.calls[0][1]).toEqual({ params: { path: { pk: 3 } } });
    expect(h.get.mock.calls.filter((call) => call[0] === "/api/v1/checklists/mine").length).toBeGreaterThan(1);
    expect(screen.getByRole("heading", { level: 1 }).querySelector("span")?.textContent).toBe("1");
  });

  it("shows the refusal text of a 409 under the list and keeps the row", async () => {
    renderPage();
    await screen.findByText("Лаборатори");

    h.post.mockImplementationOnce(async () => ({
      data: undefined,
      error: { form_errors: ["Жагсаалт аль хэдийн дууссан байна."] },
      response: { ok: false, status: 409 },
    }));
    fireEvent.click(screen.getAllByText("Хийгдсэн")[0]);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Жагсаалт аль хэдийн дууссан байна.");
    expect(alert.className).toContain("text-red-700");
    expect(screen.getByText("Лаборатори")).toBeTruthy();
  });

  it("a 409 on tick refetches the list and shows the text", async () => {
    renderPage();
    await screen.findByText("Лаборатори");
    const listCalls = () => h.get.mock.calls.filter((call) => call[0] === "/api/v1/checklists/mine").length;
    const before = listCalls();

    h.post.mockImplementationOnce(async () => ({
      data: undefined,
      error: { form_errors: ["Жагсаалт аль хэдийн дууссан байна."] },
      response: { ok: false, status: 409 },
    }));
    fireEvent.click(screen.getAllByText("Хийгдсэн")[0]);

    expect((await screen.findByRole("alert")).textContent).toBe("Жагсаалт аль хэдийн дууссан байна.");
    await waitFor(() => expect(listCalls()).toBe(before + 1));
  });

  it("two ticks cannot run at once: while one runs, every «Хийгдсэн» button is disabled", async () => {
    renderPage();
    await screen.findByText("Лаборатори");

    let answer: (response: unknown) => void = () => undefined;
    h.post.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    const [first, second] = screen.getAllByRole("button", { name: "Хийгдсэн" }) as HTMLButtonElement[];
    fireEvent.click(first);

    await waitFor(() => expect(first.disabled).toBe(true));
    expect(second.disabled).toBe(true);
    fireEvent.click(second);
    expect(tickCalls()).toHaveLength(1);

    answer({ data: undefined, error: undefined, response: { ok: true, status: 204 } });
    await waitFor(() => expect(second.disabled).toBe(false));
  });

  it("shows the Forbidden screen for a 403 answer", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Хандах эрх байхгүй" })).toBeTruthy();
  });

  it("shows the NotFound screen for a 404 answer", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 404 } }));
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Хуудас олдсонгүй" })).toBeTruthy();
  });

  it("shows the load alert for any other failure", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 500 } }));
    renderPage();

    // A 500 is retried with backoff (retryMe), so the alert appears after the retries, not at once.
    const alert = await screen.findByRole("alert", {}, { timeout: 12000 });
    expect(alert.textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
  }, 15000);
});
