import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEmployeeActivity } from "../../api/employee";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ActivityDrawer, type ActivityDrawerProps } from "./ActivityDrawer";

vi.mock("../../api/employee", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/employee")>();
  return { ...actual, useEmployeeActivity: vi.fn() };
});

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// fetch and Request are stubbed (the note form posts). openapi-fetch captures fetch at import, so the stub is set up
// here, before the api client is imported; beforeEach stubs them again, since afterEach unstubs every global.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  class StubRequest extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
    }
  }
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal("Request", StubRequest);
  return { fetchMock, StubRequest };
});
const fetchMock = h.fetchMock;

type Entry = components["schemas"]["EmployeeActivityEntryOut"];
type Batch = components["schemas"]["EmployeeActivityOut"];

// A stand-in IntersectionObserver: the tests call the callback of the newest observer to say the pill came into view.
class FakeObserver {
  static instances: FakeObserver[] = [];
  readonly callback: IntersectionObserverCallback;
  readonly observe = vi.fn();
  readonly disconnect = vi.fn();
  readonly unobserve = vi.fn();
  readonly takeRecords = vi.fn(() => []);
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: number[] = [];

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    FakeObserver.instances.push(this);
  }
}

function entry(overrides: Partial<Entry> = {}): Entry {
  return {
    badge_class: "shrink-0 rounded px-1.5 py-0.5 text-xs bg-emerald-50 text-emerald-700",
    by: "Бат",
    changes: [],
    day: "2026-11-17",
    day_heading: "",
    dot_class: "absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full border-2 border-surface bg-emerald-500",
    is_note: false,
    kind: "created",
    kind_label: "Нэмсэн",
    message: "Анхны бүртгэл",
    message_class: "mt-0.5 text-slate-700",
    starts_day: true,
    time: "09:15",
    ...overrides,
  };
}

function batch(entries: Entry[], overrides: Partial<Batch> = {}): Batch {
  return {
    empty_label: "",
    entries,
    log_url: "",
    next_offset: null,
    prev_day: "",
    ...overrides,
  };
}

const fetchNextPage = vi.fn();

// The shape of the infinite query the drawer reads: the loaded batches and whether another one is there.
function useActivityResult(pages: Batch[], fetching = false) {
  const last = pages[pages.length - 1];
  return {
    data: { pages, pageParams: pages.map((_, i) => i * 50) },
    hasNextPage: last ? last.next_offset !== null : false,
    isFetchingNextPage: fetching,
    fetchNextPage,
  };
}

function givenPages(pages: Batch[], fetching = false) {
  vi.mocked(useEmployeeActivity).mockReturnValue(
    useActivityResult(pages, fetching) as unknown as ReturnType<typeof useEmployeeActivity>,
  );
}

function drawerTree(client: QueryClient, props: Partial<ActivityDrawerProps>) {
  return (
    <QueryClientProvider client={client}>
      <ActivityDrawer pk={7} count={3} canManage={false} open onClose={vi.fn()} {...props} />
    </QueryClientProvider>
  );
}

// Renders the drawer open by default; `rerender` replaces only the props given (the same client and tree).
function renderDrawer(props: Partial<ActivityDrawerProps> = {}) {
  const onClose = props.onClose ?? vi.fn();
  const client = new QueryClient();
  const utils = render(drawerTree(client, { ...props, onClose }));
  const rerender = (next: Partial<ActivityDrawerProps>) => utils.rerender(drawerTree(client, { ...props, onClose, ...next }));
  return { ...utils, onClose, rerender };
}

// A page with its opener button, so the focus can go back to it. The drawer opens and closes with the button.
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <QueryClientProvider client={new QueryClient()}>
      <button type="button" onClick={() => setOpen(true)}>
        Түүх
      </button>
      <ActivityDrawer pk={7} count={3} canManage={false} open={open} onClose={() => setOpen(false)} />
    </QueryClientProvider>
  );
}

// The note form's answers: every posted text is recorded; `noteGate` holds the answer until released.
const notes: string[] = [];
let noteGate: Promise<void> | null = null;
let noteStatus = 204;
function routeNote() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname.endsWith("/api/v1/employees/7/note")) {
      const body = (await request.json()) as { text: string };
      notes.push(body.text);
      if (noteGate) await noteGate;
      if (noteStatus === 204) return new Response(null, { status: 204 });
      return new Response(JSON.stringify({}), { status: noteStatus, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected request ${request.method} ${url.pathname}`);
  });
}

beforeEach(() => {
  FakeObserver.instances = [];
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal("Request", h.StubRequest);
  fetchNextPage.mockReset();
  fetchMock.mockReset();
  notes.length = 0;
  noteGate = null;
  noteStatus = 204;
  routeNote();
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.classList.remove("drawer-open");
  document.querySelectorAll(".fixed.inset-0.z-50").forEach((el) => el.remove());
});

describe("ActivityDrawer", () => {
  it("opening renders the entries of page 1", () => {
    givenPages([
      batch([
        entry({ message: "Анхны бүртгэл", day_heading: "Өнөөдөр" }),
        entry({ by: "Систем", kind: "note", kind_label: "Тэмдэглэл", message: "Хоёр дахь", starts_day: false, time: "10:00" }),
      ]),
    ]);
    renderDrawer();

    expect(screen.getByText("Анхны бүртгэл")).toBeTruthy();
    expect(screen.getByText("Хоёр дахь")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Өнөөдөр" })).toBeTruthy();
    const aside = document.getElementById("activity-drawer");
    expect(aside?.getAttribute("aria-hidden")).toBe("false");
    expect(aside?.className).not.toContain("translate-x-full");
    expect(aside?.hasAttribute("inert")).toBe(false);
  });

  it("a stubbed intersection fetches page 2", () => {
    givenPages([batch([entry()], { next_offset: 50 })]);
    renderDrawer();

    expect(document.querySelector("[data-more-batch]")).not.toBeNull();
    const pill = document.querySelector("[data-more-batch]");
    expect(FakeObserver.instances.at(-1)?.observe).toHaveBeenCalledWith(pill);

    act(() => {
      FakeObserver.instances.at(-1)?.callback([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    expect(fetchNextPage).not.toHaveBeenCalled();

    act(() => {
      FakeObserver.instances.at(-1)?.callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("a day heading equal to prev_day is not repeated across a batch boundary", () => {
    givenPages([
      batch([entry({ message: "Эхний", day_heading: "Өнөөдөр" })], { next_offset: 50 }),
      batch([entry({ message: "Хоёр дахь", day_heading: "", starts_day: true })], { prev_day: "2026-11-17" }),
    ]);
    renderDrawer();

    expect(screen.getAllByRole("heading", { name: "Өнөөдөр" })).toHaveLength(1);
    expect(screen.getByText("Хоёр дахь")).toBeTruthy();
  });

  it("Escape calls onClose", () => {
    givenPages([batch([entry()])]);
    const { onClose } = renderDrawer();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape does nothing while a pop-up is open", () => {
    givenPages([batch([entry()])]);
    const { onClose } = renderDrawer();
    const popup = document.createElement("div");
    popup.className = "fixed inset-0 z-50";
    document.body.appendChild(popup);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("with next_offset null there is no end pill", () => {
    givenPages([batch([entry()], { next_offset: null })]);
    renderDrawer();

    expect(document.querySelector("[data-more-batch]")).toBeNull();
    expect(screen.queryByText("Цааш харуулах")).toBeNull();
  });

  it("a backdrop click closes the drawer", () => {
    givenPages([batch([entry()])]);
    const { onClose } = renderDrawer();

    fireEvent.click(document.getElementById("activity-backdrop") as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closing hands focus back to the button that opened it", () => {
    givenPages([batch([entry()])]);
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Түүх" });

    act(() => opener.focus());
    fireEvent.click(opener);
    const close = document.querySelector("[data-drawer-close]") as HTMLElement;
    expect(document.activeElement).toBe(close);

    fireEvent.click(close);
    expect(document.activeElement).toBe(opener);
  });

  describe("note form (Task 16b)", () => {
    const SAVE_FAILED = "Мэдээллийг хадгалж чадсангүй.";
    const noteBox = () => document.querySelector("#activity input[name='text']") as HTMLInputElement;
    const noteForm = () => document.querySelector("#activity form") as HTMLFormElement;

    it("a note posts its trimmed text once, and no legacy page opens", async () => {
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "  Тест тэмдэглэл  " } });
      fireEvent.submit(noteForm());
      await waitFor(() => expect(notes).toEqual(["Тест тэмдэглэл"]));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(openLegacyEmployee).not.toHaveBeenCalled();
    });

    it("the note is a one-line input named text, and Enter (the form submit) posts it once", async () => {
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      const input = noteBox();
      expect(input.type).toBe("text");
      expect(input.required).toBe(true);
      fireEvent.change(input, { target: { value: "Тест" } });
      noteForm().requestSubmit();
      await waitFor(() => expect(notes).toEqual(["Тест"]));
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("a blank note posts nothing and shows nothing", () => {
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "   " } });
      fireEvent.submit(noteForm());
      expect(fetchMock).not.toHaveBeenCalled();
      expect(screen.queryByText(SAVE_FAILED)).toBeNull();
      expect(noteBox().value).toBe("   ");
    });

    it("a failed post keeps the text, shows the line, and the drawer stays open", async () => {
      noteStatus = 500;
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "Тест" } });
      fireEvent.submit(noteForm());
      expect(await screen.findByText(SAVE_FAILED)).toBeTruthy();
      expect(noteBox().value).toBe("Тест");
      expect(document.getElementById("activity-drawer")?.getAttribute("aria-hidden")).toBe("false");
    });

    it("a saved note clears the box", async () => {
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "Тест" } });
      fireEvent.submit(noteForm());
      await waitFor(() => expect(noteBox().value).toBe(""));
      expect(screen.queryByText(SAVE_FAILED)).toBeNull();
    });

    it("the text stays in the box while the post is in flight", async () => {
      let release: () => void = () => {};
      noteGate = new Promise<void>((resolve) => (release = resolve));
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "Тест" } });
      fireEvent.submit(noteForm());
      await waitFor(() => expect(notes).toEqual(["Тест"]));
      expect(noteBox().value).toBe("Тест");
      release();
      await waitFor(() => expect(noteBox().value).toBe(""));
    });

    it("a double submit posts once", async () => {
      let release: () => void = () => {};
      noteGate = new Promise<void>((resolve) => (release = resolve));
      givenPages([batch([entry()])]);
      renderDrawer({ canManage: true });
      fireEvent.change(noteBox(), { target: { value: "Тест" } });
      fireEvent.submit(noteForm());
      fireEvent.submit(noteForm());
      release();
      await waitFor(() => expect(noteBox().value).toBe(""));
      expect(notes).toEqual(["Тест"]);
    });
  });

  it("shows the log link only when the batch carries one", () => {
    givenPages([batch([entry()], { log_url: "/logs/?employee=7" })]);
    renderDrawer();

    const link = screen.getByRole("link", { name: "Бүрэн харах" });
    expect(link.getAttribute("href")).toBe("/logs/?employee=7");
  });

  it("closed, the panel is off screen, aria-hidden and inert, and the backdrop is hidden", () => {
    givenPages([batch([entry()])]);
    renderDrawer({ open: false });

    const aside = document.getElementById("activity-drawer") as HTMLElement;
    expect(aside).not.toBeNull();
    expect(aside.className).toContain("translate-x-full");
    expect(aside.getAttribute("aria-hidden")).toBe("true");
    expect(aside.hasAttribute("inert")).toBe(true);
    expect(document.getElementById("activity-backdrop")?.className).toContain("hidden");
    expect(document.body.classList.contains("drawer-open")).toBe(false);
  });

  it("opening from closed slides the panel in, moves focus to Хаах and asks for the first batch", () => {
    givenPages([batch([entry()])]);
    const { rerender } = renderDrawer({ open: false });
    expect(vi.mocked(useEmployeeActivity)).toHaveBeenLastCalledWith(7, false);

    rerender({ open: true });
    const aside = document.getElementById("activity-drawer") as HTMLElement;
    expect(aside.className).not.toContain("translate-x-full");
    expect(aside.getAttribute("aria-hidden")).toBe("false");
    expect(aside.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(document.querySelector("[data-drawer-close]"));
    expect(vi.mocked(useEmployeeActivity)).toHaveBeenLastCalledWith(7, true);
    expect(screen.getByText("Анхны бүртгэл")).toBeTruthy();
  });

  it("reopening after a close loads the next page when the pill comes into view", () => {
    givenPages([batch([entry()], { next_offset: 50 })]);
    const { rerender, onClose } = renderDrawer();

    rerender({ open: false });
    rerender({ open: true });
    expect(onClose).not.toHaveBeenCalled();

    act(() => {
      FakeObserver.instances.at(-1)?.callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("the second page renders when it arrives, and the pill is gone when it was the last", () => {
    givenPages([batch([entry({ message: "Эхний", day_heading: "Өнөөдөр" })], { next_offset: 50 })]);
    const { rerender } = renderDrawer();
    act(() => {
      FakeObserver.instances.at(-1)?.callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    expect(fetchNextPage).toHaveBeenCalledTimes(1);

    // Page 2 is the last one (next_offset null): its entries render and no pill is left.
    givenPages([
      batch([entry({ message: "Эхний", day_heading: "Өнөөдөр" })], { next_offset: 50 }),
      batch([entry({ message: "Хоёр дахь", day_heading: "", starts_day: true })], { prev_day: "2026-11-17" }),
    ]);
    rerender({});
    expect(screen.getByText("Хоёр дахь")).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: "Өнөөдөр" })).toHaveLength(1);
    expect(document.querySelector("[data-more-batch]")).toBeNull();
  });

  it("an Escape that an inner pop-up already prevented leaves the drawer open", () => {
    givenPages([batch([entry()])]);
    const guard = (e: KeyboardEvent) => e.preventDefault();
    document.addEventListener("keydown", guard);
    try {
      const { onClose } = renderDrawer();
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).not.toHaveBeenCalled();
    } finally {
      document.removeEventListener("keydown", guard);
    }
  });

  it("an open drawer sets body.drawer-open (the page push), and closing removes it", () => {
    givenPages([batch([entry()])]);
    const { rerender } = renderDrawer();
    expect(document.body.classList.contains("drawer-open")).toBe(true);

    rerender({ open: false });
    expect(document.body.classList.contains("drawer-open")).toBe(false);
  });
});
