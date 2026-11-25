import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { RecruitVacancyListOut, RecruitVacancyRowOut } from "../../api/recruitment";
import { endNavBar } from "../../lib/navBar";
import { VacanciesPage } from "./VacanciesPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW: RecruitVacancyRowOut = {
  id: 1,
  title: "Бухгалтер",
  position: "Нягтлан",
  department: "Санхүү",
  hiring_manager: "Бат Болд",
  status: "open",
  status_label: "Нээлттэй",
  headcount: 2,
  deadline: "2026-12-31",
  counts: { new: 3, screening: 2, interview: 1, offer: 0, hired: 1 },
};

const CLOSED: RecruitVacancyRowOut = {
  ...ROW,
  id: 2,
  title: "Жолооч",
  position: "Жолооч",
  department: "Үйлчилгээ",
  hiring_manager: "",
  status: "closed",
  status_label: "Хаагдсан",
  headcount: 1,
  deadline: null,
  counts: { new: 0, screening: 0, interview: 0, offer: 0, hired: 0 },
};

function listAnswer(over: Partial<RecruitVacancyListOut> = {}): RecruitVacancyListOut {
  return {
    status: "open",
    q: "",
    rows: [ROW, CLOSED],
    next_offset: null,
    can_manage: true,
    empty_text: "Ажлын байр олдсонгүй",
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function failure(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

// The query of a request on the wire.
function queryOf(call: unknown[]): Record<string, string> {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query ?? {};
}

// The list requests made so far, by their query.
function listQueries(): Record<string, string>[] {
  return h.get.mock.calls.filter((call) => call[0] === "/api/v1/recruitment/vacancies").map((call) => queryOf(call));
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderPage(url = "/recruitment/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/recruitment/" element={<VacanciesPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The address the router shows now (the last Where element is the one outside the routes).
function where(): string {
  return screen.getAllByTestId("where").at(-1)?.textContent ?? "";
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/recruitment/vacancies") return ok(listAnswer());
    return failure(404);
  });
});

afterEach(() => {
  // A row opened through the router starts the top bar's safety timer; end it before the environment goes.
  endNavBar();
  cleanup();
  vi.restoreAllMocks();
});

describe("VacanciesPage", () => {
  it("draws the rows with their chips, counts and hired of headcount", async () => {
    renderPage();
    const row = await screen.findByRole("row", { name: /Бухгалтер/ });
    expect(within(row).getByText("Нээлттэй")).toBeTruthy();
    expect(within(row).getByText("Нягтлан · Санхүү · Бат Болд")).toBeTruthy();
    // The cells in order: title, status, new, screening, interview, offer, hired of headcount, deadline.
    const cells = within(row).getAllByRole("cell");
    expect(cells[2].textContent).toContain("3");
    expect(cells[6].textContent).toContain("1 / 2");
    expect(cells[7].textContent).toContain("2026-12-31");

    const closed = screen.getByRole("row", { name: /Жолооч/ });
    expect(within(closed).getByText("Хаагдсан")).toBeTruthy();
    const closedCells = within(closed).getAllByRole("cell");
    expect(closedCells[6].textContent).toContain("0 / 1");
    expect(closedCells[7].textContent).toContain("—");
  });

  it("the title is a link to the vacancy page", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "Бухгалтер" });
    expect(link.getAttribute("href")).toBe("/recruitment/vacancies/1/");
  });

  it("the vacancy row is a tab stop with no role, and Enter opens the vacancy", async () => {
    renderPage();
    const row = await screen.findByRole("row", { name: /Бухгалтер/ });
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("role")).toBeNull();
    fireEvent.keyDown(row, { key: "Enter" });
    await waitFor(() => expect(where()).toBe("/recruitment/vacancies/1/"));
  });

  it("the empty list says so in a full-width row", async () => {
    h.get.mockImplementation(async () => ok(listAnswer({ rows: [] })));
    renderPage();
    expect(await screen.findByText("Ажлын байр олдсонгүй")).toBeTruthy();
  });

  it("junk status in the address shows open and asks the server for open", async () => {
    renderPage("/recruitment/?status=garbage");
    await screen.findByRole("row", { name: /Бухгалтер/ });
    await waitFor(() => expect(listQueries().at(-1)?.status).toBe("open"));
  });

  it("a status change writes the address with replace and asks the server for it", async () => {
    renderPage();
    await screen.findByRole("row", { name: /Бухгалтер/ });
    const select = document.querySelector<HTMLSelectElement>("select[name=status]") as HTMLSelectElement;
    fireEvent.mouseDown(select);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Бүгд" }));
    await waitFor(() => expect(where()).toBe("/recruitment/?status=all"));
    await waitFor(() => expect(listQueries().at(-1)?.status).toBe("all"));
  });

  it("the search box sends its text 300 ms after the last key and writes the address", async () => {
    renderPage();
    await screen.findByRole("row", { name: /Бухгалтер/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Хайх" }), { target: { value: "Нягтлан" } });
    await waitFor(() => expect(listQueries().at(-1)?.q).toBe("Нягтлан"));
    expect(where()).toContain("q=");
  });

  it("shows the manager's purge link and the add button", async () => {
    renderPage();
    await screen.findByRole("row", { name: /Бухгалтер/ });
    expect(screen.getByRole("link", { name: "Хуучин татгалзсан ажил хүсэгч цэвэрлэх" }).getAttribute("href")).toBe(
      "/recruitment/purge/",
    );
    expect(screen.getByRole("button", { name: "Ажлын байр нээх" })).toBeTruthy();
  });

  it("hides the purge link and the add button for a hiring manager", async () => {
    h.get.mockImplementation(async () => ok(listAnswer({ can_manage: false })));
    renderPage();
    await screen.findByRole("row", { name: /Бухгалтер/ });
    expect(screen.queryByRole("link", { name: "Хуучин татгалзсан ажил хүсэгч цэвэрлэх" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ажлын байр нээх" })).toBeNull();
  });

  it("the more batch loads the next offset", async () => {
    h.get.mockImplementation(async (_path: string, init: unknown) => {
      const query = (init as { params?: { query?: Record<string, string> } }).params?.query ?? {};
      return ok(query.offset === "1" ? listAnswer({ rows: [CLOSED], next_offset: null }) : listAnswer({ rows: [ROW], next_offset: 1 }));
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Цааш харуулах" }));
    expect(await screen.findByRole("row", { name: /Жолооч/ })).toBeTruthy();
    expect(listQueries().some((query) => query.offset === "1")).toBe(true);
  });

  it("a 404 shows the app's not-found page", async () => {
    h.get.mockImplementation(async () => failure(404));
    renderPage();
    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
  });
});
