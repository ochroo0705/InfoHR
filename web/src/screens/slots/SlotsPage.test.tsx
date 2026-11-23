import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { SlotListOut, SlotRowOut } from "../../api/slots";
import { SlotsPage } from "./SlotsPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in OrdersPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const ROW: SlotRowOut = {
  id: 1,
  position: "Нягтлан бодогч",
  position_id: 1,
  branch: "Төв оффис",
  branch_id: 10,
  kind: "Main",
  kind_label: "Үндсэн",
  posts: 3,
  used: 1,
  free: 2,
  free_class: "",
};

const ROW_OVER: SlotRowOut = {
  ...ROW,
  id: 2,
  position: "Жолооч",
  kind: "Temporary",
  kind_label: "Түр",
  posts: 1,
  used: 2,
  free: -1,
  free_class: "font-medium text-red-600",
};

function listAnswer(year: number, enforce = false, rows: SlotRowOut[] = [ROW, ROW_OVER]): SlotListOut {
  return {
    year,
    rows,
    next_offset: null,
    totals: { posts: 4, used: 3, free: 1 },
    enforce,
    settings_url: "/admin/employees/companysettings/",
    empty_text: `${year} оны орон тоо бүртгэгдээгүй`,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

// The year of the request on the wire, or null when none was sent (the server picks the current year then).
function yearOf(call: unknown[]): string | null {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query?.year ?? null;
}

let answers: (year: string | null) => unknown;

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderPage(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/employees/slots/" element={<SlotsPage />} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SlotsPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    answers = (year) => ok(listAnswer(year ? Number(year) : 2026));
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (path === "/api/v1/slots") {
        return answers(yearOf([path, init]));
      }
      if (path === "/api/v1/slots/options") {
        return ok({
          year: 2026,
          min_year: 2000,
          max_year: 2100,
          hint: "Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна.",
          positions: [{ value: 1, label: "Нягтлан бодогч" }],
          branches: [{ value: 10, label: "Төв оффис" }],
          kinds: [{ value: "Main", label: "Үндсэн" }],
        });
      }
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders the title with the year from the URL", async () => {
    renderPage("/employees/slots/?year=2027");

    expect(await screen.findByRole("heading", { name: "Орон тооны төлөвлөгөө — 2027" })).toBeTruthy();
    expect(h.get.mock.calls[0][1]).toMatchObject({ params: { query: { year: "2027", offset: "0" } } });
    expect(document.title).toBe("Орон тооны төлөвлөгөө · MACS Human Capital");
  });

  it("year links point at year-1 and year+1 and move the router without a full page load", async () => {
    renderPage("/employees/slots/?year=2027");
    await screen.findByRole("heading", { name: /Орон тооны төлөвлөгөө — 2027/ });

    const back = screen.getByRole("link", { name: "← 2026" });
    expect(back.getAttribute("href")).toContain("?year=2026");
    fireEvent.click(back);
    // A TLink click is handled by the router: the location changes and the page is not reloaded.
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/slots/?year=2026"));
    expect(await screen.findByRole("heading", { name: "Орон тооны төлөвлөгөө — 2026" })).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "2027 →" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/slots/?year=2027"));
  });

  it("while a new year loads, the title, the links and Нэмэх follow the URL year and Нэмэх is disabled", async () => {
    const hold: { release?: () => void } = {};
    const gate = new Promise<void>((resolve) => {
      hold.release = resolve;
    });
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (yearOf([path, init]) === "2027") {
        await gate;
        return ok(listAnswer(2027));
      }
      // The API year of the rows on screen differs from the URL year while the new year loads.
      return ok(listAnswer(2026));
    });
    const onAdd = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/slots/?year=2026"]}>
          <Routes>
            <Route path="/employees/slots/" element={<SlotsPage onAdd={onAdd} />} />
          </Routes>
          <Probe />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("Нягтлан бодогч");
    expect(screen.getByRole("button", { name: "Нэмэх" }).hasAttribute("disabled")).toBe(false);

    fireEvent.click(screen.getByRole("link", { name: "2027 →" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/slots/?year=2027"));

    expect(screen.getByRole("heading", { name: "Орон тооны төлөвлөгөө — 2027" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 2026" }).getAttribute("href")).toContain("?year=2026");
    expect(screen.getByRole("link", { name: "2028 →" }).getAttribute("href")).toContain("?year=2028");
    expect((screen.getByRole("button", { name: "Нэмэх" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Нэмэх" }));
    expect(onAdd).not.toHaveBeenCalled();

    hold.release?.();
    await waitFor(() => expect((screen.getByRole("button", { name: "Нэмэх" }) as HTMLButtonElement).disabled).toBe(false));
    expect(onAdd).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Нэмэх" }));
    expect(onAdd).toHaveBeenCalledWith(2027);
  });

  it("a bad ?year= falls back to the server's year once settled: title, links and Нэмэх use that year", async () => {
    // The server answers every bad year with the current year (2026 here) and that year's rows.
    answers = () => ok(listAnswer(2026));
    const onAdd = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/slots/?year=1999"]}>
          <Routes>
            <Route path="/employees/slots/" element={<SlotsPage onAdd={onAdd} />} />
          </Routes>
          <Probe />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Орон тооны төлөвлөгөө — 2026" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Орон тооны төлөвлөгөө — 1999" })).toBeNull();
    expect(screen.getByRole("link", { name: "← 2025" }).getAttribute("href")).toContain("?year=2025");
    expect(screen.getByRole("link", { name: "2027 →" }).getAttribute("href")).toContain("?year=2027");
    await waitFor(() => expect((screen.getByRole("button", { name: "Нэмэх" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Нэмэх" }));
    expect(onAdd).toHaveBeenCalledWith(2026);
  });

  it.each(["?year=12", "?year=999999"])("a bad year %s settles to the server year in the add pop-up", async (query) => {
    answers = () => ok(listAnswer(2026));
    renderPage(`/employees/slots/${query}`);
    expect(await screen.findByRole("heading", { name: "Орон тооны төлөвлөгөө — 2026" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "Нэмэх" }));

    expect(await screen.findByRole("heading", { name: "Орон тоо нэмэх" })).toBeTruthy();
    const options = h.get.mock.calls.find((call) => call[0] === "/api/v1/slots/options");
    expect(options?.[1]).toMatchObject({ params: { query: { year: "2026" } } });
  });

  it("shows the enforce box state from the API", async () => {
    answers = () => ok(listAnswer(2026, true));
    const { unmount } = renderPage("/employees/slots/?year=2026");
    expect(await screen.findByText("Асаалттай")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Байгууллагын тохиргоо" }).getAttribute("href")).toBe(
      "/admin/employees/companysettings/",
    );
    unmount();

    answers = () => ok(listAnswer(2026, false));
    renderPage("/employees/slots/?year=2026");
    expect(await screen.findByText("Унтраалттай")).toBeTruthy();
  });

  it("shows the empty text row and no footer when no rows", async () => {
    answers = () =>
      ok({ ...listAnswer(2026, false, []), totals: { posts: 0, used: 0, free: 0 } });
    renderPage("/employees/slots/?year=2026");

    expect(await screen.findByText("2026 оны орон тоо бүртгэгдээгүй")).toBeTruthy();
    expect(document.querySelector("tfoot")).toBeNull();
  });

  it("calls onAdd with the year on screen when Нэмэх is clicked", async () => {
    const onAdd = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/employees/slots/?year=2026"]}>
          <SlotsPage onAdd={onAdd} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("Нягтлан бодогч");

    fireEvent.click(screen.getByRole("button", { name: "Нэмэх" }));

    expect(onAdd).toHaveBeenCalledWith(2026);
  });

  it("403 shows the forbidden screen", async () => {
    answers = () => undefined;
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage("/employees/slots/?year=2026");

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("a year change keeps the old rows inert until the new year arrives", async () => {
    const hold: { release?: () => void } = {};
    const gate = new Promise<void>((resolve) => {
      hold.release = resolve;
    });
    h.get.mockImplementation(async (path: string, init: unknown) => {
      const year = yearOf([path, init]);
      if (year === "2027") {
        await gate;
        return ok(listAnswer(2027, false, [{ ...ROW, id: 9, position: "Шинэ орон тоо" }]));
      }
      return ok(listAnswer(2026));
    });
    renderPage("/employees/slots/?year=2026");
    await screen.findByText("Нягтлан бодогч");

    fireEvent.click(screen.getByRole("link", { name: "2027 →" }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/slots/?year=2027"));

    // The old rows stay, inert and stale, while the 2027 batch is still on its way.
    const card = screen.getByText("Нягтлан бодогч").closest(".card-soft") as HTMLElement;
    expect(card.hasAttribute("inert")).toBe(true);
    expect(card.getAttribute("aria-busy")).toBe("true");

    hold.release?.();
    expect(await screen.findByText("Шинэ орон тоо")).toBeTruthy();
    expect(screen.queryByText("Нягтлан бодогч")).toBeNull();
  });

  it("Нэмэх opens the add pop-up", async () => {
    renderPage("/employees/slots/?year=2027");
    await screen.findByRole("heading", { name: /Орон тооны төлөвлөгөө — 2027/ });

    fireEvent.click(screen.getByRole("button", { name: "Нэмэх" }));

    expect(await screen.findByRole("heading", { name: "Орон тоо нэмэх" })).toBeTruthy();
    const options = h.get.mock.calls.find((call) => call[0] === "/api/v1/slots/options");
    expect(options?.[1]).toMatchObject({ params: { query: { year: "2027" } } });
  });

  it("row click opens the edit pop-up", async () => {
    renderPage("/employees/slots/?year=2026");
    await screen.findByRole("heading", { name: /Орон тооны төлөвлөгөө — 2026/ });

    fireEvent.click(screen.getByText("Нягтлан бодогч"));

    expect(await screen.findByRole("heading", { name: "Орон тоо засах" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Устгах" })).toBeTruthy();
  });

  it("list refetches after a save", async () => {
    h.post.mockResolvedValue(ok({ ok: true, id: 1, field_errors: {}, form_errors: [] }));
    renderPage("/employees/slots/?year=2026");
    await screen.findByRole("heading", { name: /Орон тооны төлөвлөгөө — 2026/ });
    const listCalls = () => h.get.mock.calls.filter((call) => call[0] === "/api/v1/slots").length;
    const before = listCalls();

    fireEvent.click(screen.getByText("Нягтлан бодогч"));
    fireEvent.click(await screen.findByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    await waitFor(() => expect(listCalls()).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Орон тоо засах" })).toBeNull());
  });
});
