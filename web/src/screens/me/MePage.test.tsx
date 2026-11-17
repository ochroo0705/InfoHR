import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDismissNotice, useMe, useTick, useWithdraw, type MeOut } from "../../api/me";
import { openLegacyPopup } from "../../lib/AppLink";
import { MainWidthContext } from "../../shell/mainWidth";
import { MePage } from "./MePage";
import { mergeRows } from "./Notices";

// The data hooks are replaced: each test sets what useMe returns and what the dismissal does.
vi.mock("../../api/me", () => ({
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

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyPopup: vi.fn() };
});

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
  return render(
    <MemoryRouter>
      <MePage />
    </MemoryRouter>,
  );
}

describe("MePage", () => {
  let mutate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.mocked(openLegacyPopup).mockClear();
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

  it("opens the leave request pop-up from «Чөлөө хүсэх»", () => {
    useMeReturns(makeMe({ can_request: true }));
    renderPage();
    fireEvent.click(screen.getByText("Чөлөө хүсэх"));
    expect(openLegacyPopup).toHaveBeenCalledWith("leave_request", "/me/");
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

  it("shows the queue with its count and opens the request pop-up from a row", () => {
    useMeReturns(
      makeMe({
        queue: [{ id: 7, employee: "Сараа", leave_type: "Ээлжийн амралт", start: "2026-12-01", end: "2026-12-05", step: "1/2" }],
      }),
    );
    renderPage();
    expect(screen.getByText("Надад ирсэн хүсэлт", { exact: false }).textContent).toContain("1");
    fireEvent.click(screen.getByText("Сараа"));
    expect(openLegacyPopup).toHaveBeenCalledWith("request_detail", "/me/");
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
