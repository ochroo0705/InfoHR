// The assistant panel's frame and keys: the Ctrl+K shortcut, the box's Escape order, focus return, the stored open flag,
// the keyboard walk through the results, the pending Enter and the opener. The API is mocked: /api/v1/meta gives a
// signed-in user, and /api/v1/palette gives a fixed answer (three page rows, or a list with a «show all» row).
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import { api } from "../../api/client";
import type { PaletteOut, PaletteRowOut } from "../../api/palette";
import { metaQueryOptions } from "../../api/meta";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ConfirmProvider, confirm } from "../../widgets/confirm";
import { modalStack, popModal, pushModal } from "../../widgets/modalLogic";
import { AssistantPanel } from "./AssistantPanel";
import { PalettePanelProvider, usePalettePanel } from "./PalettePanelContext";
import { PalettePopupsContext, type PalettePopupsApi } from "./PalettePopups";
import { recentKey } from "./recents";
import { DEBOUNCE_MS } from "./usePaletteSearch";

vi.mock("../../api/client", () => ({
  api: { GET: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const META = {
  backend_version: "dev",
  api_version: 1,
  company: { name: "", logo_url: null },
  modules: {},
  csrf: "token",
  user: { id: 1, username: "bat", first_name: "", full_name: "", must_change_password: false, perms: [], own_record: false },
};

// A page row. Its path is a ported page, so Enter navigates inside the router (the probe shows where it went).
function pageRow(key: string, title: string, path = "/employees/today/"): PaletteRowOut {
  return {
    code: [],
    day: "",
    initials: "",
    kind: "page",
    left: false,
    lines: [],
    open: { employee: null, event_type: null, kind: "page", order: null, path, popup: null, year: null },
    ref: null,
    key,
    title: [{ text: title, hit: false }],
  };
}

function answerWith(rows: PaletteRowOut[]): PaletteOut {
  return {
    empty: false,
    empty_text: "",
    fallback: [],
    fallback_heading: "",
    groups: [{ key: "pages", title: "Хуудас", count: rows.length, total: null, note: "", rows }],
  };
}

const ANSWER = answerWith([pageRow("p1", "Нэг"), pageRow("p2", "Хоёр"), pageRow("p3", "Гурав")]);
const MORE_ROW: PaletteRowOut = { ...pageRow("m", "Бүгдийг харах"), kind: "more", open: null };
const SHOW_ALL_ANSWER = answerWith([pageRow("p1", "Нэг"), MORE_ROW]);

// The answer the mock returns. A test may replace it before it renders the panel.
let currentAnswer: PaletteOut = ANSWER;
// When set, the meta answer waits for this promise (the early-open test).
let metaGate: Promise<void> | null = null;
// When set, the palette answer waits for this promise (a slow server: the request stays in flight).
let paletteGate: Promise<void> | null = null;
// The pop-up openers the panel gets. A stub: PalettePopups itself is tested in PalettePopups.test.tsx.
let popupsStub: { open: ReturnType<typeof vi.fn> } = { open: vi.fn() };

// A row that opens a pop-up (open.kind "popup") with a ref, as the API sends it.
function popupRow(key: string, title: string, popup: "order_detail" | "event" | "slot_add", ref: string | null = null): PaletteRowOut {
  return {
    ...pageRow(key, title),
    kind: "person",
    ref,
    open: { employee: 3, event_type: null, kind: "popup", order: 7, path: "/employees/3/", popup, year: 2026 },
  };
}

function mockApi() {
  vi.mocked(api.GET).mockImplementation((async (url: string) => {
    if (url === "/api/v1/meta") {
      if (metaGate) await metaGate;
      return { data: META, response: { status: 200, ok: true } };
    }
    if (url === "/api/v1/palette") {
      if (paletteGate) await paletteGate;
      return { data: currentAnswer, response: { status: 200, ok: true } };
    }
    return { data: [], response: { status: 200, ok: true } };
  }) as never);
}

// Shows whether the provider's meta answer has arrived (the store exists only after it).
function MetaReady() {
  const { data } = useQuery(metaQueryOptions);
  return <span data-testid="meta-ready">{data ? "yes" : "no"}</span>;
}

// Shows the router's path, so a test can see where Enter went.
function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

// An opener in the page, and an input a text box can hold the focus in.
function OpenerProbe() {
  const palette = usePalettePanel();
  return (
    <>
      <button type="button" data-palette-open="" onClick={palette.toggle}>
        Хайх
      </button>
      <input aria-label="Бусад талбар" />
    </>
  );
}

function renderPanel(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ConfirmProvider>
          <PalettePanelProvider>
            <PalettePopupsContext.Provider value={popupsStub as PalettePopupsApi}>
              <MetaReady />
              <OpenerProbe />
              <AssistantPanel />
              <LocationProbe />
            </PalettePopupsContext.Provider>
          </PalettePanelProvider>
        </ConfirmProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const aside = () => document.querySelector<HTMLElement>("[data-assistant-panel]") as HTMLElement;
const box = () => document.querySelector<HTMLTextAreaElement>("[data-palette-input]") as HTMLTextAreaElement;
const location = () => screen.getByTestId("location").textContent;
// fireEvent returns false when the event was cancelled (defaultPrevented).
const ctrlK = (over: Partial<KeyboardEventInit> = {}) =>
  fireEvent.keyDown(document, { key: "k", code: "KeyK", ctrlKey: true, ...over });
const selectedText = () => document.querySelector('[data-palette-item][aria-selected="true"]')?.textContent ?? "";

// Waits until the meta answer is in, so the store (and the stored open flag) exist.
async function ready() {
  await waitFor(() => expect(screen.getByTestId("meta-ready").textContent).toBe("yes"));
}

// The palette requests the API made for a query text (more=1 is the «show all» request).
function paletteCalls(q: string) {
  return vi
    .mocked(api.GET)
    .mock.calls.filter((c) => c[0] === "/api/v1/palette" && (c[1] as { params?: { query?: { q?: string } } })?.params?.query?.q === q);
}

describe("AssistantPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    currentAnswer = ANSWER;
    metaGate = null;
    paletteGate = null;
    popupsStub = { open: vi.fn() };
    mockApi();
  });

  afterEach(() => {
    cleanup();
  });

  it("Ctrl+K opens and closes the panel", async () => {
    renderPanel();
    await ready();
    expect(aside().hidden).toBe(true);
    ctrlK();
    expect(aside().hidden).toBe(false);
    ctrlK();
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
    await waitFor(() => expect(aside().hidden).toBe(true));
  });

  it("Ctrl+K works with a Cyrillic key value", async () => {
    renderPanel();
    await ready();
    fireEvent.keyDown(document, { key: "л", code: "KeyK", ctrlKey: true });
    expect(aside().hidden).toBe(false);
  });

  it("Ctrl+K inside a text box still opens it", async () => {
    renderPanel();
    await ready();
    const other = screen.getByLabelText("Бусад талбар");
    other.focus();
    fireEvent.keyDown(other, { key: "k", code: "KeyK", ctrlKey: true });
    expect(aside().hidden).toBe(false);
  });

  it("Alt+K is not the shortcut", async () => {
    renderPanel();
    await ready();
    ctrlK({ altKey: true });
    expect(aside().hidden).toBe(true);
  });

  it("no shortcut while a Modal is open, and the browser's Ctrl+K is still stopped", async () => {
    renderPanel();
    await ready();
    const modal = { closable: true, leaving: false };
    pushModal(modal);
    try {
      // fireEvent returns false when the default was prevented: the browser's own Ctrl+K never fires.
      expect(ctrlK()).toBe(false);
      expect(aside().hidden).toBe(true);
    } finally {
      popModal(modal);
    }
  });

  it("a held Ctrl+K is stopped and does not toggle the panel", async () => {
    renderPanel();
    await ready();
    expect(ctrlK({ repeat: true })).toBe(false);
    expect(aside().hidden).toBe(true);
  });

  it("with a confirm open, Ctrl+K does not open the panel", async () => {
    renderPanel();
    await ready();
    act(() => {
      void confirm("Үргэлжлүүлэх үү?");
    });
    await screen.findByRole("alertdialog");
    ctrlK();
    expect(aside().hidden).toBe(true);
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
  });

  it("with a confirm open, the panel's Escape is ignored and its box is kept", async () => {
    renderPanel();
    await ready();
    ctrlK();
    fireEvent.change(box(), { target: { value: "абв" } });
    act(() => {
      void confirm("Үргэлжлүүлэх үү?");
    });
    await screen.findByRole("alertdialog");
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    // The confirm answered the Escape; the panel did not clear its box or close.
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(box().value).toBe("абв");
    expect(aside().getAttribute("data-leaving")).toBeNull();
  });

  it("first Escape clears the box, second closes", async () => {
    renderPanel();
    await ready();
    ctrlK();
    fireEvent.change(box(), { target: { value: "санхүү" } });
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(box().value).toBe("");
    expect(aside().getAttribute("data-leaving")).toBeNull();
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
  });

  it("Escape during an IME composition does nothing", async () => {
    renderPanel();
    await ready();
    ctrlK();
    fireEvent.keyDown(box(), { key: "Escape", keyCode: 229 });
    expect(aside().getAttribute("data-leaving")).toBeNull();
  });

  it("Escape already handled by a pop-up does not close the panel", async () => {
    renderPanel();
    await ready();
    ctrlK();
    // A pop-up that handles Escape first calls preventDefault in the capture phase, before the panel sees the key.
    const popup = (e: KeyboardEvent) => e.preventDefault();
    window.addEventListener("keydown", popup, true);
    try {
      fireEvent.keyDown(box(), { key: "Escape" });
    } finally {
      window.removeEventListener("keydown", popup, true);
    }
    expect(aside().hidden).toBe(false);
    expect(aside().getAttribute("data-leaving")).toBeNull();
  });

  it("focus returns to the opener on close", async () => {
    renderPanel();
    await ready();
    const opener = screen.getByRole("button", { name: "Хайх" });
    opener.focus();
    ctrlK();
    expect(document.activeElement).toBe(box());
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(document.activeElement).toBe(opener);
  });

  it("open flag is stored per user and reopens without the enter class", async () => {
    sessionStorage.setItem("assistant-thread-1", JSON.stringify({ open: true, items: [] }));
    renderPanel();
    await ready();
    expect(aside().hidden).toBe(false);
    expect(aside().hasAttribute("data-no-enter")).toBe(true);
    // A user close writes the flag; the next user open removes the no-enter mark.
    ctrlK();
    expect(JSON.parse(sessionStorage.getItem("assistant-thread-1") as string).open).toBe(false);
    ctrlK();
    expect(JSON.parse(sessionStorage.getItem("assistant-thread-1") as string).open).toBe(true);
    expect(aside().hasAttribute("data-no-enter")).toBe(false);
  });

  it("a Ctrl+K before the meta answer is not undone by the stored flag", async () => {
    sessionStorage.setItem("assistant-thread-1", JSON.stringify({ open: false, items: [] }));
    let release: () => void = () => undefined;
    metaGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderPanel();
    // The meta answer is held back: the user opens the panel first.
    ctrlK();
    expect(aside().hidden).toBe(false);
    await act(async () => {
      release();
    });
    await ready();
    expect(aside().hidden).toBe(false);
    expect(JSON.parse(sessionStorage.getItem("assistant-thread-1") as string).open).toBe(true);
  });

  it("closed panel is hidden and its controls are not focusable", async () => {
    renderPanel();
    await ready();
    expect(aside().hidden).toBe(true);
    expect(box()).toBeNull();
    const close = aside().querySelector("[data-assistant-close]") as HTMLElement;
    expect(close.closest("[hidden]")).not.toBeNull();
  });

  it("reopen during the exit animation works: the panel is open again with an empty box", async () => {
    renderPanel();
    await ready();
    ctrlK();
    fireEvent.change(box(), { target: { value: "хайлт" } });
    ctrlK();
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
    ctrlK();
    expect(aside().getAttribute("data-leaving")).toBeNull();
    expect(aside().hidden).toBe(false);
    expect(box().value).toBe("");
    expect(document.activeElement).toBe(box());
  });

  it("Enter during the debounce does not open an old row and sends the query", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.change(box(), { target: { value: "а" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    // The old answer's first row was not opened, and the query went out now.
    expect(location()).toBe("/");
    await waitFor(() => expect(paletteCalls("а").length).toBeGreaterThan(0));
  });

  it("Enter during the debounce flushes once: one request, no second one from the timer", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.change(box(), { target: { value: "б" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    // The query went out at once, synchronously with the Enter.
    expect(paletteCalls("б")).toHaveLength(1);
    // The debounce timer was dropped by the flush: after its time has passed, still one request.
    await new Promise((resolve) => setTimeout(resolve, DEBOUNCE_MS + 50));
    expect(paletteCalls("б")).toHaveLength(1);
  });

  it("Enter during an in-flight request does not abort it or send it again", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    // The server is slow for the next query: the request stays in flight.
    let answer: () => void = () => undefined;
    paletteGate = new Promise<void>((resolve) => {
      answer = resolve;
    });
    fireEvent.change(box(), { target: { value: "в" } });
    await waitFor(() => expect(paletteCalls("в")).toHaveLength(1));
    const signal = (paletteCalls("в")[0][1] as { signal?: AbortSignal }).signal;
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(paletteCalls("в")).toHaveLength(1);
    expect(signal?.aborted).toBe(false);
    expect(location()).toBe("/");
    // The answer arrives; the next Enter opens the first row.
    paletteGate = null;
    answer();
    await waitFor(() => {
      fireEvent.keyDown(box(), { key: "Enter" });
      expect(location()).toBe("/employees/today/");
    });
  });

  it("the confirm's stack entry is leaving during its exit, so a pop-up underneath ignores Escape", async () => {
    renderPanel();
    await ready();
    act(() => {
      void confirm("Үргэлжлүүлэх үү?");
    });
    await screen.findByRole("alertdialog");
    expect(modalStack().some((entry) => entry.leaving)).toBe(false);
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    // Answered: the dialog is on its exit, and its entry says so while it plays.
    expect(modalStack().some((entry) => entry.leaving)).toBe(true);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(modalStack().some((entry) => entry.leaving)).toBe(false);
  });

  it("Enter after the answer activates the first row", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.change(box(), { target: { value: "а" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    // The answer for "а" comes back; the next Enter opens its first row, a ported page.
    await waitFor(() => {
      fireEvent.keyDown(box(), { key: "Enter" });
      expect(location()).toBe("/employees/today/");
    });
  });

  it("Enter with an empty box opens the first row when none is moved to", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    await waitFor(() => expect(selectedText()).toContain("Нэг"));
    fireEvent.keyDown(box(), { key: "Enter" });
    await waitFor(() => expect(location()).toBe("/employees/today/"));
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
  });

  it("Shift+Enter adds a line and does not activate a row", async () => {
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    // Not cancelled: the browser inserts the line break in the box.
    expect(fireEvent.keyDown(box(), { key: "Enter", shiftKey: true })).toBe(true);
    expect(aside().getAttribute("data-leaving")).toBeNull();
    expect(location()).toBe("/");
  });

  it("ArrowDown wraps", async () => {
    renderPanel();
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    await waitFor(() => expect(selectedText()).toContain("Нэг"));
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(selectedText()).toContain("Хоёр");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(selectedText()).toContain("Гурав");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(selectedText()).toContain("Нэг");
  });

  it("«show all» asks for more and keeps the focus in the box", async () => {
    currentAnswer = SHOW_ALL_ANSWER;
    renderPanel();
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    // «Show all» is sent for a typed query only (palette.js sends more=1 with a typed query).
    fireEvent.change(box(), { target: { value: "а" } });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(selectedText()).toContain("Бүгдийг харах");
    const showAllAsked = () =>
      vi.mocked(api.GET).mock.calls.some((c) => {
        const query = (c[1] as { params?: { query?: { more?: string } } })?.params?.query;
        return c[0] === "/api/v1/palette" && query?.more === "1";
      });
    // Enter waits while the query is pending (it only runs the query), then activates the «show all» row.
    await waitFor(() => {
      fireEvent.keyDown(box(), { key: "Enter" });
      expect(showAllAsked()).toBe(true);
    });
    expect(document.activeElement).toBe(box());
    expect(aside().getAttribute("data-leaving")).toBeNull();
  });

  it("a page row with a ref is remembered, then the panel closes", async () => {
    currentAnswer = answerWith([{ ...pageRow("p1", "Нэг"), ref: "p:5" }]);
    renderPanel();
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.keyDown(box(), { key: "Enter" });
    await waitFor(() => expect(location()).toBe("/employees/today/"));
    expect(JSON.parse(localStorage.getItem(recentKey(META.user.id)) ?? "[]")).toEqual(["p:5"]);
  });

  it("a page row without a ref is not remembered", async () => {
    renderPanel();
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.keyDown(box(), { key: "Enter" });
    await waitFor(() => expect(location()).toBe("/employees/today/"));
    expect(localStorage.getItem(recentKey(META.user.id))).toBeNull();
  });

  it("a pop-up row closes the panel, hands its target to the pop-up host, and does not navigate", async () => {
    currentAnswer = answerWith([popupRow("q1", "Захиалга", "order_detail", "p:3")]);
    renderPanel("/employees/today/");
    await ready();
    ctrlK();
    await screen.findByText("Захиалга");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(popupsStub.open).toHaveBeenCalledTimes(1);
    expect(popupsStub.open).toHaveBeenCalledWith(currentAnswer.groups[0].rows[0].open);
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
    expect(location()).toBe("/employees/today/");
    expect(localStorage.getItem(recentKey(META.user.id))).toContain("p:3");
  });

  // ---- Parity details: scroll, hover, click, print, reduced motion, phone width (palette.js select/mousemove/click,
  // base.html lines 61-80).

  // The option whose text is exactly this title.
  const rowOf = (title: string) =>
    Array.from(document.querySelectorAll<HTMLElement>("[data-palette-item]")).find((el) => el.textContent === title) as HTMLElement;

  // A matchMedia that answers the reduced-motion query, as the presence hook reads it at close time.
  function setReducedMotionMedia(on: boolean) {
    window.matchMedia = ((query: string) => ({
      matches: on && query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }

  it("ArrowDown scrolls the selected row into view with block nearest", async () => {
    const scrolled: string[] = [];
    const scroll = vi.fn(function (this: Element) {
      scrolled.push(this.textContent ?? "");
    });
    Element.prototype.scrollIntoView = scroll as never;
    try {
      renderPanel();
      await ready();
      ctrlK();
      await screen.findByText("Нэг");
      await waitFor(() => expect(selectedText()).toContain("Нэг"));
      scroll.mockClear();
      fireEvent.keyDown(box(), { key: "ArrowDown" });
      expect(selectedText()).toContain("Хоёр");
      expect(scroll).toHaveBeenCalledTimes(1);
      expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
      expect(scrolled).toEqual(["Хоёр"]);
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("a keyboard move onto a one-row answer does not leave a scroll pending for a later hover", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll as never;
    try {
      currentAnswer = answerWith([pageRow("p1", "Нэг")]);
      renderPanel();
      await ready();
      ctrlK();
      await screen.findByText("Нэг");
      await waitFor(() => expect(selectedText()).toContain("Нэг"));
      // The only row is already selected: the move scrolls it, and nothing is left over from it.
      fireEvent.keyDown(box(), { key: "ArrowDown" });
      expect(scroll).toHaveBeenCalledTimes(1);
      // A new answer with a second row; the first row is selected again, then the pointer moves onto the second.
      scroll.mockClear();
      currentAnswer = ANSWER;
      fireEvent.change(box(), { target: { value: "а" } });
      await screen.findByText("Хоёр");
      await waitFor(() => expect(selectedText()).toContain("Нэг"));
      fireEvent.mouseMove(rowOf("Хоёр"));
      expect(selectedText()).toContain("Хоёр");
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("mouse move selects the hovered row and does not scroll", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll as never;
    try {
      renderPanel();
      await ready();
      ctrlK();
      await screen.findByText("Нэг");
      await waitFor(() => expect(selectedText()).toContain("Нэг"));
      fireEvent.mouseMove(rowOf("Гурав"));
      expect(selectedText()).toContain("Гурав");
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("click activates the row under the pointer, not the selected one", async () => {
    currentAnswer = answerWith([pageRow("p1", "Нэг"), { ...pageRow("p2", "Хоёр"), ref: "p:2" }]);
    renderPanel("/");
    await ready();
    ctrlK();
    await screen.findByText("Нэг");
    fireEvent.click(rowOf("Хоёр"));
    await waitFor(() => expect(location()).toBe("/employees/today/"));
    expect(aside().getAttribute("data-leaving")).not.toBeNull();
    // The clicked row was remembered (it has the ref), the first row was not.
    expect(JSON.parse(localStorage.getItem(recentKey(META.user.id)) ?? "[]")).toEqual(["p:2"]);
  });

  it("the panel root has the print:hidden class", async () => {
    renderPanel();
    await ready();
    expect(aside().classList.contains("print:hidden")).toBe(true);
  });

  it("with reduced motion on, the panel has no exit class: closing removes it at once", async () => {
    setReducedMotionMedia(true);
    try {
      renderPanel();
      await ready();
      ctrlK();
      expect(aside().hidden).toBe(false);
      expect(aside().hasAttribute("data-leaving")).toBe(false);
      ctrlK();
      await waitFor(() => expect(aside().hidden).toBe(true));
      expect(aside().hasAttribute("data-leaving")).toBe(false);
    } finally {
      delete (window as { matchMedia?: unknown }).matchMedia;
    }
  });

  it("the global reduced-motion rule in app.css turns off the panel's slide animation", () => {
    // app.css: under reduce, every element's animation and transition is none (covers #assistant-panel's slide in and out).
    // Read from disk: vitest returns an empty string for a ?raw import of a stylesheet.
    // Vitest runs from web/ (npm test, npx vitest run), so the path is relative to it.
    const appCss = readFileSync(resolve("src/styles/app.css"), "utf8");
    expect(appCss).toMatch(/prefers-reduced-motion: reduce\) \{[^]*?animation: none !important/);
  });

  it("at phone width the panel is full screen and the composer box is 44 px tall", async () => {
    renderPanel();
    await ready();
    ctrlK();
    expect(aside().classList.contains("max-sm:top-0")).toBe(true);
    expect(aside().classList.contains("max-sm:w-full")).toBe(true);
    expect(box().classList.contains("max-sm:min-h-11")).toBe(true);
  });
});
