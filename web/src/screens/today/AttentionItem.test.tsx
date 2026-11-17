import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render as renderTree, screen, waitFor, type RenderOptions } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { AttentionMoreOut, GroupOut, ItemOut } from "../../api/today";
import { AttentionChip } from "./AttentionChip";
import { AttentionItem } from "./AttentionItem";
import { AttentionMore, GapPeople } from "./AttentionMore";

// The tiles link to employee pages through the router (ported paths), so every render needs a Router. Any wrapper the
// test passes is kept inside the router.
function render(ui: ReactNode, options?: RenderOptions) {
  const Inner = options?.wrapper;
  return renderTree(ui, {
    ...options,
    wrapper: ({ children }: { children: ReactNode }) => (
      <MemoryRouter>{Inner ? <Inner>{children}</Inner> : children}</MemoryRouter>
    ),
  });
}

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created). The real
// useAttentionMore runs on a QueryClient; `respond` decides each answer from the request URL.
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
let respond: (url: URL) => Response = () => jsonResponse(200, answer({}));

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function answer(over: Partial<AttentionMoreOut>): AttentionMoreOut {
  return { dated: false, items: [], more: 0, next_offset: 0, ...over };
}

function urlsSeen(): URL[] {
  return fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url));
}

const person: ItemOut = {
  key: "contract:5",
  text: "Гэрээ дуусна",
  urgency: 0,
  employee: { id: 5, full_name: "Бат Болд", short_name: "Б. Болд", code: "E-001" },
  url: "/employees/5/",
  anchor: "#contract",
  clash: false,
  can_dismiss: true,
};

const second: ItemOut = {
  ...person,
  key: "contract:6",
  employee: { id: 6, full_name: "Сараа", short_name: "С. Сараа", code: "E-002" },
  url: "/employees/6/",
};

const third: ItemOut = {
  ...person,
  key: "contract:7",
  employee: { id: 7, full_name: "Төмөр", short_name: "Т. Төмөр", code: "E-003" },
  url: "/employees/7/",
};

const noEmployee: ItemOut = {
  key: "list:1",
  text: "Бүрэн бус",
  urgency: 1,
  employee: null,
  url: "/employees/?gap=1",
  anchor: "",
  clash: false,
  can_dismiss: false,
};

function group(overrides: Partial<GroupOut>): GroupOut {
  return {
    count: 5,
    dated: true,
    keys: [],
    kind: "contract",
    label: "Гэрээ дуусах",
    more: 2,
    nearest: null,
    open: true,
    shown: [],
    urgency: 0,
    url: "",
    ...overrides,
  };
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

let client: QueryClient;

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input: Request) => respond(new URL(input.url)));
  respond = () => jsonResponse(200, answer({}));
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(() => {
  cleanup();
});

describe("AttentionItem", () => {
  it("an item without an employee in the dismiss list shows no button", () => {
    render(
      <ul>
        <AttentionItem item={noEmployee} action="dismiss" onToggle={vi.fn()} />
      </ul>,
    );

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("link", { name: "Жагсаалт" }).getAttribute("href")).toBe("/employees/?gap=1");
  });

  it("restore shows «Дахин харуулах» and sends the restore action", () => {
    const onToggle = vi.fn();
    render(
      <ul>
        <AttentionItem item={person} action="restore" onToggle={onToggle} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Дахин харуулах" }));

    expect(onToggle).toHaveBeenCalledWith(["contract:5"], "restore");
  });

  it("dismiss shows «Мэдлээ» and sends the dismiss action", () => {
    const onToggle = vi.fn();
    render(
      <ul>
        <AttentionItem item={person} action="dismiss" onToggle={onToggle} />
      </ul>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Мэдлээ" }));

    expect(onToggle).toHaveBeenCalledWith(["contract:5"], "dismiss");
  });
});

describe("AttentionChip", () => {
  it("shows the short name and code when the item clashes", () => {
    render(<AttentionChip item={{ ...person, clash: true }} onToggle={vi.fn()} />);

    expect(screen.getByRole("link", { name: "Б. Болд · E-001" }).getAttribute("href")).toBe("/employees/5/#contract");
  });

  it("shows only the short name when there is no clash", () => {
    render(<AttentionChip item={person} onToggle={vi.fn()} />);

    expect(screen.getByRole("link", { name: "Б. Болд" })).toBeTruthy();
  });
});

describe("AttentionMore (group, no all)", () => {
  it("the first click sends no all, then shows the items and no button (dated group)", async () => {
    respond = () => jsonResponse(200, answer({ dated: true, items: [person, second], more: 0 }));

    render(
      <ul>
        <AttentionMore group={group({ more: 2 })} onToggle={vi.fn()} />
      </ul>,
      { wrapper: wrapper(client) },
    );
    fireEvent.click(screen.getByRole("button", { name: "Бүгдийг харах (2) →" }));

    expect(await screen.findByRole("link", { name: "Сараа" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Мэдлээ" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Бүгдийг харах/ })).toBeNull();
    const url = urlsSeen()[0];
    expect(url.searchParams.get("kind")).toBe("contract");
    expect(url.searchParams.get("urgency")).toBe("0");
    expect(url.searchParams.has("all")).toBe(false);
  });

  it("a failed first request keeps the button, and a click retries", async () => {
    respond = () => new Response("", { status: 500 });

    render(
      <ul>
        <AttentionMore group={group({ more: 2 })} onToggle={vi.fn()} />
      </ul>,
      { wrapper: wrapper(client) },
    );
    fireEvent.click(screen.getByRole("button", { name: "Бүгдийг харах (2) →" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const retry = await screen.findByRole("button", { name: "Бүгдийг харах (2) →" });
    await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false));

    respond = () => jsonResponse(200, answer({ dated: true, items: [person], more: 0 }));
    fireEvent.click(retry);

    expect(await screen.findByRole("link", { name: "Бат Болд" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Бүгдийг харах/ })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("GapPeople (all=1 paging)", () => {
  it("loads all=1&offset=0, then appends the next offset", async () => {
    respond = (url) =>
      url.searchParams.get("offset") === "8"
        ? jsonResponse(200, answer({ items: [third], more: 0, next_offset: 16 }))
        : jsonResponse(200, answer({ items: [person, second], more: 1, next_offset: 8 }));

    render(<GapPeople group={group({ dated: false, more: 0 })} onToggle={vi.fn()} enabled />, {
      wrapper: wrapper(client),
    });

    expect(await screen.findByRole("button", { name: "+ 1 бусад →" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Б. Болд" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "С. Сараа" })).toBeTruthy();
    const first = urlsSeen()[0];
    expect(first.searchParams.get("all")).toBe("1");
    expect(first.searchParams.get("offset")).toBe("0");

    fireEvent.click(screen.getByRole("button", { name: "+ 1 бусад →" }));

    expect(await screen.findByRole("link", { name: "Т. Төмөр" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Б. Болд" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /бусад/ })).toBeNull();
    expect(urlsSeen()[1].searchParams.get("offset")).toBe("8");
  });

  it("a failed page keeps the button, and a retry click loads that page", async () => {
    respond = (url) =>
      url.searchParams.get("offset") === "8"
        ? new Response("", { status: 500 })
        : jsonResponse(200, answer({ items: [person], more: 2, next_offset: 8 }));

    render(<GapPeople group={group({ dated: false, more: 0 })} onToggle={vi.fn()} enabled />, {
      wrapper: wrapper(client),
    });
    fireEvent.click(await screen.findByRole("button", { name: "+ 2 бусад →" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const retry = await screen.findByRole("button", { name: "+ 2 бусад →" });
    await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByRole("link", { name: "Б. Болд" })).toBeTruthy();

    respond = (url) =>
      url.searchParams.get("offset") === "8"
        ? jsonResponse(200, answer({ items: [second], more: 0, next_offset: 16 }))
        : jsonResponse(200, answer({ items: [person], more: 2, next_offset: 8 }));
    fireEvent.click(retry);

    expect(await screen.findByRole("link", { name: "С. Сараа" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Б. Болд" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /бусад/ })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlsSeen()[2].searchParams.get("offset")).toBe("8");
  });
});
