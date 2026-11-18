import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeHeadOut } from "../../api/employee";
import { SetupCard } from "./SetupCard";

// fetch and Request are stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// CorrectionModal.test. The toggle posts go through this stub.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

const SAVE_FAILED = "Мэдээллийг хадгалж чадсангүй.";

let client: QueryClient;
let posted: string[] = [];
let answer: () => Promise<Response>;
let gate: Promise<void> | null = null;

// Answers the setup toggle POSTs through `answer`; every posted path is recorded.
function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "POST" && /\/api\/v1\/employees\/7\/setup\/[a-z_]+$/.test(url.pathname)) {
      posted.push(url.pathname);
      if (gate) await gate;
      return answer();
    }
    throw new Error(`unexpected request ${request.method} ${url.pathname}`);
  });
}

// Every render needs the query client (the toggle is a mutation).
function renderCard(ui: ReactNode) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

type Setup = NonNullable<EmployeeHeadOut["setup"]>;

// A checklist as the API sends it: two items done or not, one system item, the texts and percent already computed.
function setup(overrides: Partial<Setup> = {}): Setup {
  return {
    items: [
      { key: "contract", label: "Гэрээ байгуулсан", done: true, auto: false, note: "Админ · 2026-01-05 10:00" },
      { key: "photo", label: "Зураг оруулсан", done: false, auto: false, note: "" },
      { key: "bank", label: "Банкны данс", done: false, auto: true, note: "" },
    ],
    done: 1,
    total: 3,
    complete: false,
    percent: 33,
    progress_text: "1/3 хийгдсэн",
    ...overrides,
  };
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchMock.mockReset();
  posted = [];
  gate = null;
  answer = async () => new Response(null, { status: 204 });
  route();
});

afterEach(() => {
  cleanup();
});

describe("SetupCard", () => {
  it("renders nothing when setup is null", () => {
    const { container } = renderCard(<SetupCard setup={null} pk={7} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the done count, the «done/total» text and the progress width while incomplete", () => {
    const { container } = renderCard(<SetupCard setup={setup()} pk={7} />);
    expect(container.querySelector("#setup")?.className).toBe("mb-6");
    expect(screen.getByText("Бүрдүүлэлт")).toBeTruthy();
    expect(screen.getByText("1/3 хийгдсэн")).toBeTruthy();
    const details = container.querySelector("details");
    expect(details?.hasAttribute("open")).toBe(true);
    expect(details?.className).toContain("border-l-amber-500");
    const bar = container.querySelector(".transition-all") as HTMLElement;
    expect(bar.style.width).toBe("33%");
    expect(bar.className).toBe("block h-full rounded-full bg-amber-500 transition-all");
  });

  it("shows the completed title and a closed card when complete", () => {
    const { container } = renderCard(
      <SetupCard setup={setup({ complete: true, done: 3, percent: 100, progress_text: "3/3 хийгдсэн" })} pk={7} />,
    );
    expect(screen.getByText("Бүрдүүлэлт дууссан")).toBeTruthy();
    expect(screen.queryByText("3/3 хийгдсэн")).toBeNull();
    const details = container.querySelector("details");
    expect(details?.hasAttribute("open")).toBe(false);
    expect(details?.className).toContain("border-l-emerald-500");
  });

  it("marks a system item as automatic with its disabled checkbox", () => {
    renderCard(<SetupCard setup={setup()} pk={7} />);
    expect(screen.getByText("автоматаар").getAttribute("title")).toBe("Систем өөрөө тэмдэглэнэ");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[2].disabled).toBe(true);
    expect(boxes[1].disabled).toBe(false);
  });

  it("shows the note of a ticked item and no note on an open one", () => {
    renderCard(<SetupCard setup={setup()} pk={7} />);
    expect(screen.getByText("Админ · 2026-01-05 10:00").className).toBe("ml-auto text-xs text-slate-400");
    expect(screen.getByText("Зураг оруулсан").className).toBe("font-medium text-slate-800");
    expect(screen.getByText("Гэрээ байгуулсан").className).toBe("text-slate-500");
  });

  it("ticking an item posts to its setup path, and no legacy page opens", async () => {
    renderCard(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Зураг оруулсан"));
    await waitFor(() => expect(posted).toEqual(["/api/v1/employees/7/setup/photo"]));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("a system item is inert: a click posts nothing", () => {
    renderCard(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Банкны данс"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[2].disabled).toBe(true);
  });

  it("while an item's toggle is pending, only that item's checkbox is disabled", async () => {
    let release: () => void = () => {};
    gate = new Promise<void>((resolve) => (release = resolve));
    renderCard(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Зураг оруулсан"));
    const boxes = () => screen.getAllByRole("checkbox") as HTMLInputElement[];
    await waitFor(() => expect(boxes()[1].disabled).toBe(true));
    expect(boxes()[0].disabled).toBe(false);
    release();
    await waitFor(() => expect(boxes()[1].disabled).toBe(false));
  });

  it("two quick ticks on two items keep their own pending flag; the failed one alone shows the line", async () => {
    let releasePhoto: () => void = () => {};
    const photoGate = new Promise<void>((resolve) => (releasePhoto = resolve));
    fetchMock.mockImplementation(async (input: unknown) => {
      const url = new URL((input as Request).url);
      if (url.pathname.endsWith("/setup/photo")) {
        await photoGate;
        return new Response(JSON.stringify({}), { status: 500, headers: { "Content-Type": "application/json" } });
      }
      return new Response(null, { status: 204 });
    });
    renderCard(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Зураг оруулсан"));
    fireEvent.click(screen.getByText("Гэрээ байгуулсан"));
    const boxes = () => screen.getAllByRole("checkbox") as HTMLInputElement[];
    // The contract tick succeeds on its own; the photo tick is still pending and keeps its own disabled box.
    await waitFor(() => expect(boxes()[0].disabled).toBe(false));
    expect(boxes()[1].disabled).toBe(true);
    expect(screen.queryByText(SAVE_FAILED)).toBeNull();
    releasePhoto();
    expect(await screen.findByText(SAVE_FAILED)).toBeTruthy();
    expect(boxes()[1].disabled).toBe(false);
    expect(boxes()[1].checked).toBe(false);
  });

  it("a failed toggle shows one red line and leaves the checkbox at the server state", async () => {
    answer = async () => new Response(JSON.stringify({}), { status: 500, headers: { "Content-Type": "application/json" } });
    renderCard(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Зураг оруулсан"));
    expect(await screen.findByText(SAVE_FAILED)).toBeTruthy();
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[1].checked).toBe(false);
  });
});
