import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDismissNotice, useMe, useTick, useWithdraw, type MeOut } from "../../api/me";
import { MainWidthContext } from "../../shell/mainWidth";
import { MePage } from "./MePage";
import { mergeRows } from "./Notices";

// The API client is replaced by a stub that answers by path: the request pop-ups load their options and detail through it.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

// The data hooks are replaced: each test sets what useMe returns and what the dismissal does. The rest of the module
// (retryMe, used by the request pop-ups' hooks) is the real one.
vi.mock("../../api/me", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/me")>()),
  useMe: vi.fn(),
  useDismissNotice: vi.fn(),
  useTick: vi.fn(),
  useWithdraw: vi.fn(),
}));

// The task and request sections call these on render; idle mutations keep the page tests independent of them.
function idleMutations() {
  vi.mocked(useTick).mockReturnValue({ mutate: vi.fn() } as unknown as ReturnType<typeof useTick>);
  vi.mocked(useWithdraw).mockReturnValue({ mutate: vi.fn() } as unknown as ReturnType<typeof useWithdraw>);
}

// The request options answer with one leave type; a detail request never answers, so the detail pop-up stays loading and
// the test can see which request id it asked for.
const REQUEST_OPTIONS = { types: [{ value: 2, label: "Ээлжийн амралт" }] };

function leaveOk(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function makeMe(overrides: Partial<MeOut> = {}): MeOut {
  return {
    employee: { id: 1, full_name: "Бат Дорж", initial: "Б", photo: "" },
    job: { position: "Програмист", department: "Мэдээлэл", manager: "Сүрэн" },
    can_request: true,
    has_team: false,
    holidays: [],
    notices: [],
    queue: [],
    recorded: [],
    requests: [],
    tasks: [],
    team_away: [],
    balance: { start_missing: false, configured: false, periods: [], nowhere: 0 },
    ...overrides,
  } as MeOut;
}

function useMeReturns(data: MeOut | undefined, error: unknown = null) {
  vi.mocked(useMe).mockReturnValue({ data, error } as unknown as ReturnType<typeof useMe>);
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MePage", () => {
  let mutate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/requests/options" ? leaveOk(REQUEST_OPTIONS) : new Promise(() => {}),
    );
    h.post.mockImplementation(async () => leaveOk({}));
    mutate = vi.fn((_vars: unknown, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
    vi.mocked(useDismissNotice).mockReturnValue({ mutate } as unknown as ReturnType<typeof useDismissNotice>);
    idleMutations();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the initial when there is no photo", () => {
    useMeReturns(makeMe());
    renderPage();
    expect(screen.getByText("Б", { selector: "div" })).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("shows the photo when there is one", () => {
    useMeReturns(makeMe({ employee: { id: 1, full_name: "Бат Дорж", initial: "Б", photo: "/media/p.jpg" } }));
    renderPage();
    expect(document.querySelector("img")?.getAttribute("src")).toBe("/media/p.jpg");
  });

  it("hides «Чөлөө хүсэх» when can_request is false", () => {
    useMeReturns(makeMe({ can_request: false }));
    renderPage();
    expect(screen.queryByText("Чөлөө хүсэх")).toBeNull();
  });

  it("opens the leave request pop-up from «Чөлөө хүсэх», on the page", async () => {
    useMeReturns(makeMe({ can_request: true }));
    renderPage();
    expect(screen.queryByRole("heading", { name: "Чөлөө хүсэх" })).toBeNull();
    fireEvent.click(screen.getByText("Чөлөө хүсэх"));
    expect(await screen.findByRole("heading", { name: "Чөлөө хүсэх" })).toBeTruthy();
    await waitFor(() => expect(h.get).toHaveBeenCalledWith("/api/v1/leave/requests/options"));
    expect(document.title).toBe("Миний хуудас · MACS Human Capital");
  });

  it("dismissing a notice sends its key and marks the row as leaving", () => {
    useMeReturns(makeMe({ notices: [{ key: "n1", text: "Чөлөө батлагдлаа", approved: true }] }));
    renderPage();
    const row = document.querySelector("[data-notice]") as HTMLElement;
    expect(row.hasAttribute("data-leaving")).toBe(false);
    fireEvent.click(screen.getByText("Мэдлээ"));
    expect(mutate).toHaveBeenCalledWith({ key: "n1" }, expect.anything());
    expect(row.hasAttribute("data-leaving")).toBe(true);
    expect(row.hasAttribute("inert")).toBe(true);
  });

  it("keeps a notice when the dismissal fails", () => {
    mutate.mockImplementation((_vars: unknown, opts?: { onError?: () => void }) => opts?.onError?.());
    useMeReturns(makeMe({ notices: [{ key: "n1", text: "Татгалзсан", approved: false }] }));
    renderPage();
    fireEvent.click(screen.getByText("Мэдлээ"));
    const row = document.querySelector("[data-notice]") as HTMLElement;
    expect(row.hasAttribute("data-leaving")).toBe(false);
    expect(screen.getByText("Татгалзсан")).toBeTruthy();
  });

  it("shows no «Надад ирсэн хүсэлт» when the queue is empty", () => {
    useMeReturns(makeMe({ queue: [] }));
    renderPage();
    expect(screen.queryByText("Надад ирсэн хүсэлт", { exact: false })).toBeNull();
  });

  it("shows the queue with its count and opens the detail of that row's request", async () => {
    useMeReturns(
      makeMe({
        queue: [
          { id: 7, employee: "Сараа", leave_type: "Ээлжийн амралт", start: "2026-12-01", end: "2026-12-05", step: "1/2" },
          { id: 8, employee: "Болд", leave_type: "Ээлжийн амралт", start: "2026-12-10", end: "2026-12-12", step: "2/2" },
        ],
      }),
    );
    renderPage();
    expect(screen.getByText("Надад ирсэн хүсэлт", { exact: false }).textContent).toContain("2");
    fireEvent.click(screen.getByText("Болд"));
    await waitFor(() =>
      expect(h.get).toHaveBeenCalledWith("/api/v1/leave/requests/{pk}", { params: { path: { pk: 8 } } }),
    );
    expect(h.get).not.toHaveBeenCalledWith("/api/v1/leave/requests/{pk}", { params: { path: { pk: 7 } } });
  });

  it("shows the NotFound text when /me answers 404", () => {
    useMeReturns(undefined, Object.assign(new Error("not found"), { status: 404 }));
    renderPage();
    expect(screen.getByText("Хуудас олдсонгүй")).toBeTruthy();
  });

  it("sets the document title", () => {
    useMeReturns(makeMe());
    renderPage();
    expect(document.title).toBe("Миний хуудас · MACS Human Capital");
  });
});

describe("MePage refetch and width", () => {
  beforeEach(() => {
    vi.mocked(useDismissNotice).mockReturnValue({ mutate: vi.fn() } as unknown as ReturnType<typeof useDismissNotice>);
    idleMutations();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps the page when a background refetch fails and data is already there", () => {
    useMeReturns(makeMe(), new Error("network"));
    renderPage();
    expect(screen.getByText("Бат Дорж")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
  });

  it("shows only the error line when there is no data and the request failed", () => {
    useMeReturns(undefined, Object.assign(new Error("server"), { status: 500 }));
    renderPage();
    expect(screen.getByText("Мэдээлэл ачаалж чадсангүй.")).toBeTruthy();
    expect(screen.queryByText("Бат Дорж")).toBeNull();
  });

  it("sets the narrow main width only for the page body, not for NotFound", () => {
    const setWidth = vi.fn();
    const withProvider = (ui: ReactNode) => (
      <MemoryRouter>
        <MainWidthContext.Provider value={setWidth}>{ui}</MainWidthContext.Provider>
      </MemoryRouter>
    );

    useMeReturns(undefined, Object.assign(new Error("not found"), { status: 404 }));
    render(withProvider(<MePage />));
    expect(setWidth).not.toHaveBeenCalledWith("max-w-2xl px-4");
    cleanup();

    setWidth.mockClear();
    useMeReturns(makeMe());
    render(withProvider(<MePage />));
    expect(setWidth).toHaveBeenCalledWith("max-w-2xl px-4");
  });
});

describe("mergeRows", () => {
  const a = { key: "a", text: "A", approved: true };
  const b = { key: "b", text: "B", approved: false };

  it("keeps a closing row the server no longer sends, in its place", () => {
    const prev = [
      { notice: a, closing: false },
      { notice: b, closing: true },
    ];
    const merged = mergeRows(prev, [a], new Set());
    expect(merged.map((r) => r.notice.key)).toEqual(["a", "b"]);
    expect(merged[1].closing).toBe(true);
  });

  it("keeps a row whose dismissal is still in flight", () => {
    const prev = [{ notice: b, closing: false }];
    expect(mergeRows(prev, [], new Set(["b"])).map((r) => r.notice.key)).toEqual(["b"]);
  });

  it("drops an open row the server no longer sends", () => {
    const prev = [{ notice: b, closing: false }];
    expect(mergeRows(prev, [], new Set())).toEqual([]);
  });
});
