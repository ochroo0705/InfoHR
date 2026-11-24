import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ListsIndexOut } from "../../api/lists";
import { ListsIndexPage } from "./ListsIndexPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as in EmployeeLogPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const BANK = { slug: "bank", label: "Банк", count: 3, hits: 0 };
const SIZES = { slug: "sizes", label: "Хэмжээ", count: 12, hits: 2 };

// The index answer: a list of cards, optionally with the meaning card.
function indexAnswer(overrides: Partial<ListsIndexOut> = {}): ListsIndexOut {
  return {
    items: [BANK, SIZES],
    meanings_count: 4,
    q: "",
    show_meanings: true,
    ...overrides,
  };
}

// The search text the stub answers for; the answer is built from it as the server would echo it.
let answer: (q: string) => ListsIndexOut = () => indexAnswer();

function indexCalls(q?: string) {
  return h.get.mock.calls.filter(
    (call) => call[0] === "/api/v1/lists" && (q === undefined || call[1]?.params?.query?.q === q),
  );
}

// Shows the router's address, so a test can read what the URL became.
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
          <Route path="/lists/" element={<ListsIndexPage />} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function searchBox(): HTMLInputElement {
  return screen.getByLabelText("Хайх") as HTMLInputElement;
}

beforeEach(() => {
  answer = () => indexAnswer();
  h.get.mockReset();
  h.get.mockImplementation(async (path: string, init?: { params?: { query?: { q?: string } } }) => {
    if (path === "/api/v1/lists") {
      const data = answer(init?.params?.query?.q ?? "");
      return { data, error: undefined, response: { ok: true, status: 200 } };
    }
    return { data: undefined, error: {}, response: { ok: false, status: 404 } };
  });
  document.title = "start";
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ListsIndexPage", () => {
  it("renders the title, the grey line and the cards with their counts", async () => {
    renderPage("/lists/");

    expect(screen.getByRole("heading", { level: 1, name: "Жагсаалтууд" })).toBeTruthy();
    expect(screen.getByText(/Ажилтны бүртгэлд ашиглагдах нийтлэг жагсаалтууд/)).toBeTruthy();
    expect((await screen.findByRole("link", { name: /Банк/ })).getAttribute("href")).toBe("/lists/bank/");
    expect(screen.getByText("3 бичлэг")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Хэмжээ/ }).getAttribute("href")).toBe("/lists/sizes/");
    expect(screen.getByRole("link", { name: /Хэмжээ/ }).textContent).toContain("12 бичлэг · 2 таарсан");
    expect(screen.queryByText(/0 таарсан/)).toBeNull();
    expect(document.title).toBe("Жагсаалтууд · MACS Human Capital");
  });

  it("a typed word calls the API once after the debounce and updates the address", async () => {
    answer = (q) => (q === "банк" ? indexAnswer({ items: [{ ...BANK, hits: 1 }], q: "банк" }) : indexAnswer());
    renderPage("/lists/");
    await screen.findByText("3 бичлэг");

    vi.useFakeTimers();
    fireEvent.change(searchBox(), { target: { value: "банк" } });
    expect(indexCalls("банк")).toHaveLength(0);

    act(() => vi.advanceTimersByTime(249));
    expect(indexCalls("банк")).toHaveLength(0);

    act(() => vi.advanceTimersByTime(1));
    expect(indexCalls("банк")).toHaveLength(1);
    // The address is URL-encoded by the router; the decoded text is what the user typed.
    expect(decodeURIComponent(screen.getByTestId("loc").textContent ?? "")).toBe("/lists/?q=банк");
  });

  it("shows the hit count of a matching list in violet", async () => {
    renderPage("/lists/?q=хэмжээ");

    const hits = await screen.findByText("2 таарсан");
    expect(hits.className).toContain("text-violet-700");
    expect(indexCalls("хэмжээ")).toHaveLength(1);
  });

  it("shows Олдсонгүй when nothing matches and there is no meaning card", async () => {
    answer = () => indexAnswer({ items: [], show_meanings: false, q: "zzz" });
    renderPage("/lists/?q=zzz");

    expect(await screen.findByText("Олдсонгүй")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Утгын холбоо/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Утгын холбоо" })).toBeNull();
  });

  it("shows the meaning card with its count when show_meanings is set", async () => {
    renderPage("/lists/");

    expect(await screen.findByRole("heading", { level: 2, name: "Утгын холбоо" })).toBeTruthy();
    const card = screen.getByText("4 холбоо").closest("a");
    expect(card?.getAttribute("href")).toBe("/lists/meaning/");
    expect(screen.queryByText("Олдсонгүй")).toBeNull();
  });

  it("hides the meaning card when show_meanings is not set", async () => {
    answer = () => indexAnswer({ show_meanings: false });
    renderPage("/lists/");

    await screen.findByText("3 бичлэг");
    expect(screen.queryByRole("heading", { name: "Утгын холбоо" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Утгын холбоо/ })).toBeNull();
  });

  it("403 shows the forbidden screen", async () => {
    h.get.mockImplementation(async () => ({ data: undefined, error: {}, response: { ok: false, status: 403 } }));
    renderPage("/lists/");

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });
});
