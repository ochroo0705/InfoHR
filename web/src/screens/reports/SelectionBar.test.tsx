import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  copySelection,
  fetchChecklistForm,
  postSelection,
  printTicket,
  startChecklists,
} from "../../api/reports";
import { SelectionBar } from "./SelectionBar";
import { useReportSelection } from "./useReportSelection";

vi.mock("../../api/reports", () => ({
  postSelection: vi.fn(),
  copySelection: vi.fn(),
  printTicket: vi.fn(),
  fetchChecklistForm: vi.fn(),
  startChecklists: vi.fn(),
  SELECTION_FAIL_ERROR: "Татаж чадсангүй. Дахин оролдоно уу.",
}));

const postSelectionMock = vi.mocked(postSelection);
const copySelectionMock = vi.mocked(copySelection);
const printTicketMock = vi.mocked(printTicket);
const fetchChecklistFormMock = vi.mocked(fetchChecklistForm);
const startChecklistsMock = vi.mocked(startChecklists);

const CHECKLIST = "Ажлаас гарах жагсаалт эхлүүлэх";
const CHECKLIST_FORM = {
  all: false,
  anchor_max: "2026-12-31",
  anchor_min: "2020-01-01",
  count: 2,
  reasons: [],
  template_missing: false,
  today: "2026-11-27",
};

const REAL_CREATE_OBJECT_URL = URL.createObjectURL;
const REAL_REVOKE_OBJECT_URL = URL.revokeObjectURL;

const URLS = {
  excel: "/api/v1/reports/staff/selected/excel",
  csv: "/api/v1/reports/staff/selected/csv",
  print: "/api/v1/reports/staff/selected/print",
  copy: "/api/v1/reports/staff/selected/copy",
  checklist: "/api/v1/reports/staff/selected/checklist",
};

const NOTE_MS_TEST = 4000;
const NETWORK_MSG = "Холбогдож чадсангүй. Дахин оролдоно уу.";
const FAILED_MSG = "Татаж чадсангүй. Дахин оролдоно уу.";
const OVER_CAP_MSG = "500-аас олон мөр сонгох боломжгүй. Шүүлтүүрээр нарийвчилна уу.";

type HarnessProps = {
  urls?: Record<string, string>;
  total?: number;
  allVisiblePicked?: boolean;
  hasMore?: boolean;
  overCap?: boolean;
  maxPeople?: number;
};

// The real hook drives the bar: the buttons below pick people and toggle the mode, as the rows and «Сонгох» will.
function Harness({
  urls = URLS,
  total = 42,
  allVisiblePicked = false,
  hasMore = false,
  overCap = false,
  maxPeople = 500,
}: HarnessProps) {
  const selection = useReportSelection("staff");
  return (
    <>
      <button type="button" onClick={selection.toggle}>
        Сонгох
      </button>
      <button type="button" onClick={() => selection.pickRow(12, true)}>
        pick-12
      </button>
      <button type="button" onClick={() => selection.pickRow(34, true)}>
        pick-34
      </button>
      <SelectionBar
        reportKey="staff"
        query="q=a"
        total={total}
        urls={urls}
        selection={selection}
        pickedCount={selection.state.ids.size}
        allVisiblePicked={allVisiblePicked}
        hasMore={hasMore}
        overCap={overCap}
        maxPeople={maxPeople}
      />
    </>
  );
}

let client: QueryClient;

function renderBar(props: HarnessProps = {}) {
  return render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

// Picks persons 12 and 34 (the mode turns on with the first pick).
function pickTwo() {
  fireEvent.click(screen.getByRole("button", { name: "pick-12" }));
  fireEvent.click(screen.getByRole("button", { name: "pick-34" }));
}

function actionButton(name: string): HTMLButtonElement | null {
  return screen.queryByRole("button", { name }) as HTMLButtonElement | null;
}

class Deferred<T> {
  promise: Promise<T>;
  resolve!: (value: T) => void;
  reject!: (reason: unknown) => void;
  constructor() {
    this.promise = new Promise<T>((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
  }
}

// A refusal as the client throws it: a message, the status and the form errors.
function refusal(message: string, status = 400): Error {
  return Object.assign(new Error(message), { status, formErrors: [message], fieldErrors: {}, code: undefined });
}

// Lets the bar's promise chain finish under fake timers without advancing them (vi.waitFor would advance the clock).
async function settleLastCall(mock: { mock: { results: { value: unknown }[] } }) {
  await act(async () => {
    await mock.mock.results[mock.mock.results.length - 1].value;
    await Promise.resolve();
    await Promise.resolve();
  });
}

// Captures the download name of every anchor the bar clicks, without navigating.
function captureDownloads(): string[] {
  const downloads: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  });
  return downloads;
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  postSelectionMock.mockReset();
  copySelectionMock.mockReset();
  printTicketMock.mockReset();
  fetchChecklistFormMock.mockReset();
  startChecklistsMock.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:staff");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  URL.createObjectURL = REAL_CREATE_OBJECT_URL;
  // jsdom has no revokeObjectURL: a download timer still pending from an earlier test must find a function, not undefined.
  URL.revokeObjectURL = REAL_REVOKE_OBJECT_URL ?? (() => {});
  Reflect.deleteProperty(navigator, "clipboard");
  Reflect.deleteProperty(window, "isSecureContext");
  Reflect.deleteProperty(document, "execCommand");
});

describe("SelectionBar visibility", () => {
  it("is absent while selection is off", () => {
    renderBar();
    expect(document.getElementById("selection-bar")).toBeNull();
  });

  it("is present with the picked count while selection is on", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Сонгох" }));
    const bar = document.getElementById("selection-bar");
    expect(bar).not.toBeNull();
    expect(bar?.querySelector("[data-count]")?.textContent).toBe("0");
    pickTwo();
    expect(document.querySelector("[data-count]")?.textContent).toBe("2");
    expect(bar?.textContent).toContain("сонгосон");
  });

  it("goes away when the mode ends with «Болих»", () => {
    renderBar();
    pickTwo();
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    expect(document.getElementById("selection-bar")).toBeNull();
  });

  it("goes away when Escape ends the mode", () => {
    renderBar();
    pickTwo();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.getElementById("selection-bar")).toBeNull();
  });
});

describe("SelectionBar actions", () => {
  it("draws the four file and copy actions, and the checklist after them when its URL is set", () => {
    renderBar();
    pickTwo();
    expect(actionButton("Excel")).not.toBeNull();
    expect(actionButton("CSV")).not.toBeNull();
    expect(actionButton("Хэвлэх")).not.toBeNull();
    expect(actionButton("Хуулах")).not.toBeNull();
    expect(actionButton(CHECKLIST)).not.toBeNull();
    expect(document.querySelector('[data-action="checklist"]')).not.toBeNull();
  });

  it("does not draw an action whose URL is empty", () => {
    renderBar({ urls: { ...URLS, excel: "", csv: "" } });
    pickTwo();
    expect(actionButton("Excel")).toBeNull();
    expect(actionButton("CSV")).toBeNull();
    expect(actionButton("Хэвлэх")).not.toBeNull();
  });

  it("does not draw an action with no URL key at all", () => {
    const rest: Record<string, string> = { ...URLS };
    delete rest.excel;
    renderBar({ urls: rest });
    pickTwo();
    expect(actionButton("Excel")).toBeNull();
  });

  it("Excel posts the picks and saves the blob under the server's name", async () => {
    const createObjectURL = vi.fn(() => "blob:staff");
    URL.createObjectURL = createObjectURL;
    const downloads = captureDownloads();
    const blob = new Blob(["xlsx"]);
    postSelectionMock.mockResolvedValue({ blob, filename: "staff-selected-2026-11-27.xlsx" });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await waitFor(() => expect(downloads).toEqual(["staff-selected-2026-11-27.xlsx"]));
    expect(postSelectionMock).toHaveBeenCalledWith(client, "staff", "excel", {
      query: "q=a",
      ids: ["12", "34"],
      all: false,
    });
    expect(createObjectURL).toHaveBeenCalledWith(blob);
  });

  it("CSV posts the picks as csv and saves the blob", async () => {
    const downloads = captureDownloads();
    postSelectionMock.mockResolvedValue({ blob: new Blob(["a,b"]), filename: "staff-selected.csv" });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("CSV") as HTMLButtonElement);
    await waitFor(() => expect(downloads).toEqual(["staff-selected.csv"]));
    expect(postSelectionMock).toHaveBeenCalledWith(client, "staff", "csv", {
      query: "q=a",
      ids: ["12", "34"],
      all: false,
    });
  });

  it("revokes the object URL after a second", async () => {
    vi.useFakeTimers();
    captureDownloads();
    postSelectionMock.mockResolvedValue({ blob: new Blob(["x"]), filename: "a.xlsx" });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await vi.waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:staff");
  });

  it("a failure while saving the blob shows the plain failure text, not the network text", async () => {
    URL.createObjectURL = vi.fn(() => {
      throw new Error("boom");
    });
    captureDownloads();
    postSelectionMock.mockResolvedValue({ blob: new Blob(["x"]), filename: "a.xlsx" });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(FAILED_MSG));
  });

  it("all matching sends all=true and no ids", async () => {
    captureDownloads();
    postSelectionMock.mockResolvedValue({ blob: new Blob(["x"]), filename: "a.xlsx" });
    renderBar({ total: 42, allVisiblePicked: true, hasMore: true });
    pickTwo();

    fireEvent.click(screen.getByRole("button", { name: "Бүх 42 мөрийг сонгох" }));
    expect(document.querySelector("[data-count]")?.textContent).toBe("Бүгд (42)");
    expect(screen.queryByRole("button", { name: "Бүх 42 мөрийг сонгох" })).toBeNull();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await waitFor(() => expect(postSelectionMock).toHaveBeenCalledTimes(1));
    expect(postSelectionMock).toHaveBeenCalledWith(client, "staff", "excel", { query: "q=a", ids: [], all: true });
  });

  it("copy writes the clipboard and shows the copy note", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    copySelectionMock.mockResolvedValue({ text: "Анна\nБат", count: 2, dropped: 1 });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Хууллаа: 2 · 1 хасагдсан"));
    expect(writeText).toHaveBeenCalledWith("Анна\nБат");
    expect(copySelectionMock).toHaveBeenCalledWith(client, "staff", { query: "q=a", ids: ["12", "34"], all: false });
  });

  it("copy falls back to execCommand when the clipboard API is missing", async () => {
    Object.defineProperty(document, "execCommand", { value: vi.fn(() => true), configurable: true });
    copySelectionMock.mockResolvedValue({ text: "Анна", count: 1, dropped: 0 });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Хууллаа: 1"));
    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  it("copy shows the clipboard failure when both paths fail", async () => {
    Object.defineProperty(document, "execCommand", { value: vi.fn(() => false), configurable: true });
    copySelectionMock.mockResolvedValue({ text: "Анна", count: 1, dropped: 0 });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Хуулж чадсангүй."));
  });

  it("a success note disappears after 4 seconds", async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "execCommand", { value: vi.fn(() => true), configurable: true });
    copySelectionMock.mockResolvedValue({ text: "Анна", count: 1, dropped: 0 });
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await settleLastCall(copySelectionMock);
    expect(screen.getByRole("status").textContent).toBe("Хууллаа: 1");
    act(() => {
      vi.advanceTimersByTime(3999);
    });
    expect(screen.getByRole("status").textContent).toBe("Хууллаа: 1");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("clears the note timer on unmount: no timer and no state update left behind", async () => {
    vi.useFakeTimers();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    Object.defineProperty(document, "execCommand", { value: vi.fn(() => true), configurable: true });
    copySelectionMock.mockResolvedValue({ text: "Анна", count: 1, dropped: 0 });
    const view = renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await settleLastCall(copySelectionMock);
    expect(screen.getByRole("status").textContent).toBe("Хууллаа: 1");
    const pendingBefore = vi.getTimerCount();
    view.unmount();
    // The note timer is one of the pending timers and unmount clears it.
    expect(vi.getTimerCount()).toBe(pendingBefore - 1);
    act(() => {
      vi.advanceTimersByTime(NOTE_MS_TEST);
    });
    expect(consoleError).not.toHaveBeenCalled();
  });
});

describe("SelectionBar «all matching» offer", () => {
  it("is offered when every row on screen is picked and more batches follow", () => {
    renderBar({ total: 42, allVisiblePicked: true, hasMore: true });
    pickTwo();
    expect(screen.getByRole("button", { name: "Бүх 42 мөрийг сонгох" })).not.toBeNull();
    expect(screen.queryByText(OVER_CAP_MSG)).toBeNull();
  });

  it("is not offered when every row on screen is picked but no batch follows", () => {
    renderBar({ total: 2, allVisiblePicked: true, hasMore: false });
    pickTwo();
    expect(screen.queryByRole("button", { name: "Бүх 2 мөрийг сонгох" })).toBeNull();
  });

  it("is not offered when only some rows on screen are picked", () => {
    renderBar({ total: 42, allVisiblePicked: false, hasMore: true });
    pickTwo();
    expect(screen.queryByRole("button", { name: "Бүх 42 мөрийг сонгох" })).toBeNull();
  });

  it("over the cap, the note replaces the button", () => {
    renderBar({ total: 900, allVisiblePicked: true, hasMore: true, overCap: true, maxPeople: 500 });
    pickTwo();
    expect(screen.queryByRole("button", { name: "Бүх 900 мөрийг сонгох" })).toBeNull();
    expect(screen.getByText(OVER_CAP_MSG)).not.toBeNull();
    expect(document.querySelector("[data-over-cap]")?.textContent).toBe(OVER_CAP_MSG);
  });

  it("over the cap with some rows picked, no note is shown", () => {
    renderBar({ total: 900, allVisiblePicked: false, hasMore: true, overCap: true, maxPeople: 500 });
    pickTwo();
    expect(screen.queryByText(OVER_CAP_MSG)).toBeNull();
  });
});

describe("SelectionBar pending and failures", () => {
  it("disables the action buttons while a request runs, and enables them after", async () => {
    const pending = new Deferred<{ blob: Blob; filename: string }>();
    postSelectionMock.mockReturnValue(pending.promise);
    captureDownloads();
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    expect((actionButton("Excel") as HTMLButtonElement).disabled).toBe(true);
    expect((actionButton("CSV") as HTMLButtonElement).disabled).toBe(true);
    expect((actionButton("Хуулах") as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      pending.resolve({ blob: new Blob(["x"]), filename: "a.xlsx" });
    });
    await waitFor(() => expect((actionButton("Excel") as HTMLButtonElement).disabled).toBe(false));
    expect((actionButton("CSV") as HTMLButtonElement).disabled).toBe(false);
  });

  it("a refusal shows its message in role=alert and keeps the picks", async () => {
    postSelectionMock.mockRejectedValue(refusal("Сонгосон мөр хүчингүй байна."));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Сонгосон мөр хүчингүй байна."));
    expect(document.querySelector("[data-count]")?.textContent).toBe("2");
    expect(document.getElementById("selection-bar")).not.toBeNull();
  });

  it("a network failure shows the network text", async () => {
    copySelectionMock.mockRejectedValue(new Error("Failed to fetch"));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хуулах") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(NETWORK_MSG));
  });

  it("an error note stays on screen after the success timer would have cleared it", async () => {
    vi.useFakeTimers();
    postSelectionMock.mockRejectedValue(refusal("Хугацаа дууссан."));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Excel") as HTMLButtonElement);
    await vi.waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Хугацаа дууссан."));
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.getByRole("alert").textContent).toBe("Хугацаа дууссан.");
  });
});

describe("SelectionBar checklist action", () => {
  it("is drawn when its URL is set", () => {
    renderBar();
    pickTwo();
    expect(actionButton(CHECKLIST)).not.toBeNull();
  });

  it("is absent when its URL is empty", () => {
    renderBar({ urls: { ...URLS, checklist: "" } });
    pickTwo();
    expect(actionButton(CHECKLIST)).toBeNull();
    expect(document.querySelector('[data-action="checklist"]')).toBeNull();
  });

  it("opens the pop-up with the current picks", async () => {
    fetchChecklistFormMock.mockResolvedValue(CHECKLIST_FORM);
    renderBar();
    pickTwo();

    fireEvent.click(actionButton(CHECKLIST) as HTMLButtonElement);
    expect(await screen.findByRole("dialog", { name: CHECKLIST })).not.toBeNull();
    await waitFor(() =>
      expect(fetchChecklistFormMock).toHaveBeenCalledWith(client, "staff", {
        query: "q=a",
        ids: ["12", "34"],
        all: false,
      }),
    );
  });

  it("a refused form read shows the message in the bar's alert and no pop-up stays", async () => {
    fetchChecklistFormMock.mockRejectedValue(refusal("Ажлаас гарах жагсаалт эхлүүлэх эрх алга."));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton(CHECKLIST) as HTMLButtonElement);
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Ажлаас гарах жагсаалт эхлүүлэх эрх алга."),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.getElementById("selection-bar")).not.toBeNull();
    expect(document.querySelector("[data-count]")?.textContent).toBe("2");
  });

  it("closing the pop-up keeps the selection on screen", async () => {
    fetchChecklistFormMock.mockResolvedValue(CHECKLIST_FORM);
    renderBar();
    pickTwo();

    fireEvent.click(actionButton(CHECKLIST) as HTMLButtonElement);
    const dialog = await screen.findByRole("dialog", { name: CHECKLIST });
    fireEvent.click(within(dialog).getByRole("button", { name: "Хаах" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.querySelector("[data-count]")?.textContent).toBe("2");
    expect(document.getElementById("selection-bar")).not.toBeNull();
    expect(actionButton("Excel")?.disabled).toBe(false);
  });

  it("the other action buttons are disabled while the pop-up is open", async () => {
    fetchChecklistFormMock.mockResolvedValue(CHECKLIST_FORM);
    renderBar();
    pickTwo();

    fireEvent.click(actionButton(CHECKLIST) as HTMLButtonElement);
    await screen.findByRole("dialog", { name: CHECKLIST });
    for (const name of ["Excel", "CSV", "Хэвлэх", "Хуулах", CHECKLIST]) {
      expect((actionButton(name) as HTMLButtonElement).disabled).toBe(true);
    }
  });
});

describe("SelectionBar print", () => {
  function fakeWindow() {
    return { location: { href: "" }, close: vi.fn() } as unknown as Window & { close: () => void };
  }

  it("opens the blank window inside the click, before the ticket arrives", async () => {
    const win = fakeWindow();
    const open = vi.spyOn(window, "open").mockReturnValue(win);
    const ticket = new Deferred<string>();
    printTicketMock.mockReturnValue(ticket.promise);
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хэвлэх") as HTMLButtonElement);
    expect(open).toHaveBeenCalledWith("", "_blank");
    expect(printTicketMock).toHaveBeenCalledWith(client, "staff", { query: "q=a", ids: ["12", "34"], all: false });
    expect(win.location.href).toBe("");

    await act(async () => {
      ticket.resolve("T1");
    });
    await waitFor(() => expect(win.location.href).toBe("/reports/staff/print/?sel=T1"));
  });

  it("encodes the ticket in the print address", async () => {
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win);
    printTicketMock.mockResolvedValue("a b/c");
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хэвлэх") as HTMLButtonElement);
    await waitFor(() => expect(win.location.href).toBe("/reports/staff/print/?sel=a%20b%2Fc"));
  });

  it("a ticket refusal closes the blank window and shows the message", async () => {
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win);
    printTicketMock.mockRejectedValue(refusal("Хэвлэх эрх байхгүй."));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хэвлэх") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Хэвлэх эрх байхгүй."));
    expect(win.close).toHaveBeenCalled();
    expect(win.location.href).toBe("");
    expect(document.querySelector("[data-count]")?.textContent).toBe("2");
  });

  it("a network failure on print closes the window and shows the network text", async () => {
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win);
    printTicketMock.mockRejectedValue(new Error("Failed to fetch"));
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хэвлэх") as HTMLButtonElement);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(NETWORK_MSG));
    expect(win.close).toHaveBeenCalled();
  });

  it("a blocked pop-up shows the failure text and asks for no ticket", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    renderBar();
    pickTwo();

    fireEvent.click(actionButton("Хэвлэх") as HTMLButtonElement);
    expect(printTicketMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(FAILED_MSG);
  });
});
