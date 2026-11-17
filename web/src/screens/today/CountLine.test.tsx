import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CountLine, type LazyResult } from "./CountLine";
import { NAME_LINK_CLASS, NameRows } from "./NameRows";

type Person = { id: number; name: string };

const people: Person[] = [
  { id: 5, name: "Бат" },
  { id: 6, name: "Сараа" },
];

// A fake lazy query: nothing while closed, the data while open, no network.
function fakeQuery<T>(data: T, opts: { fail?: boolean } = {}) {
  return (open: boolean): LazyResult<T> => {
    if (!open) return { data: undefined, isSuccess: false, isError: false };
    if (opts.fail) return { data: undefined, isSuccess: false, isError: true };
    return { data, isSuccess: true, isError: false };
  };
}

function renderLine(query: (open: boolean) => LazyResult<Person[]>, empty = "Ойрын 30 хоногт алга.") {
  return render(
    <CountLine label="Төрсөн өдөр" count={2} id="upcoming-birthday" query={query}>
      {(list) => (
        <NameRows
          rows={list.map((p) => ({
            id: p.id,
            left: (
              <a href={`/employees/${p.id}/`} className={NAME_LINK_CLASS}>
                {p.name}
              </a>
            ),
            right: "2026-11-20",
          }))}
          empty={empty}
        />
      )}
    </CountLine>,
  );
}

function panel(): HTMLElement {
  const el = document.getElementById("upcoming-birthday");
  if (!el) throw new Error("panel missing");
  return el;
}

// A real react-query hook over a stubbed fetch, as the app's hooks use. Only fetches while open.
function useLazyPeople(open: boolean): LazyResult<Person[]> {
  return useQuery({
    queryKey: ["test-people"],
    enabled: open,
    retry: false,
    queryFn: async () => {
      const response = await fetch("/api/test-people");
      if (!response.ok) throw new Error("request failed");
      return (await response.json()) as Person[];
    },
  });
}

function renderWithClient(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CountLine label="Төрсөн өдөр" count={2} id="upcoming-birthday" query={(open) => useLazyPeople(open)}>
        {(list) => (
          <NameRows
            rows={list.map((p) => ({ id: p.id, left: p.name, right: "2026-11-20" }))}
            empty="Алга."
          />
        )}
      </CountLine>
    </QueryClientProvider>,
  );
}

// Lets pending fetch promises and react-query state updates settle.
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("CountLine", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("starts closed with ▸ and aria-controls pointing at the panel", () => {
    renderLine(fakeQuery(people));
    const button = screen.getByRole("button");
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▸");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.getAttribute("aria-controls")).toBe("upcoming-birthday");
    expect(panel().childElementCount).toBe(0);
  });

  it("on the first click shows the rows, aria-expanded true and ▾", () => {
    renderLine(fakeQuery(people));
    const button = screen.getByRole("button");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▾");
    expect(screen.getByRole("link", { name: "Бат" }).getAttribute("href")).toBe("/employees/5/");
    expect(screen.getByRole("link", { name: "Сараа" }).getAttribute("href")).toBe("/employees/6/");
    expect(panel().getAttribute("aria-live")).toBe("polite");
  });

  it("shows the given empty text when the list is empty", () => {
    renderLine(fakeQuery<Person[]>([]), "Ойрын 30 хоногт төрсөн өдөр алга.");
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Ойрын 30 хоногт төрсөн өдөр алга.")).toBeTruthy();
    expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe("true");
  });

  it("stays closed when the fake query fails", () => {
    renderLine(fakeQuery(people, { fail: true }));
    const button = screen.getByRole("button");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▸");
    expect(panel().childElementCount).toBe(0);
  });

  it("on the second click empties the panel, sets ▸ and fetches nothing more", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(people), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    renderWithClient(fetchMock);
    const button = screen.getByRole("button");

    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("true"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(button);
    await settle();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▸");
    expect(panel().childElementCount).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("after a failed load the next click retries and loads the rows", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 500 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(people), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    renderWithClient(fetchMock);
    const button = screen.getByRole("button");

    fireEvent.click(button);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await settle();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▸");
    expect(panel().childElementCount).toBe(0);

    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("true"));
    expect(button.textContent).toBe("Төрсөн өдөр 2 ▾");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Бат")).toBeTruthy();
    expect(screen.getByText("Сараа")).toBeTruthy();
  });
});

describe("NameRows", () => {
  afterEach(() => {
    cleanup();
  });

  it("uses the default empty class and the given one when asked", () => {
    const { rerender } = render(<NameRows rows={[]} empty="Алга." />);
    expect(screen.getByText("Алга.").className).toBe("text-sm text-slate-400");
    rerender(<NameRows rows={[]} empty="Алга." emptyClass="text-sm text-slate-500" />);
    expect(screen.getByText("Алга.").className).toBe("text-sm text-slate-500");
  });

  it("renders each row with the shared row classes", () => {
    const { container } = render(
      <NameRows rows={[{ id: 1, left: "Бат", right: "2026-11-20" }]} empty="Алга." />,
    );
    const row = container.firstElementChild as HTMLElement;
    expect(row.className).toContain("hover:bg-violet-50");
    expect(row.className).toContain("-mx-2");
    expect(row.textContent).toBe("Бат2026-11-20");
  });

  it("right-hand text defaults to text-slate-500 and takes rightClass when given", () => {
    const rows = [{ id: 1, left: "Бат", right: "2026-11-20 · 2026-12-01 хүртэл" }];
    const { rerender } = render(<NameRows rows={rows} empty="Алга." />);
    expect(screen.getByText("2026-11-20 · 2026-12-01 хүртэл").className).toBe("text-slate-500");
    rerender(<NameRows rows={rows} empty="Алга." rightClass="text-right text-slate-500" />);
    expect(screen.getByText("2026-11-20 · 2026-12-01 хүртэл").className).toBe("text-right text-slate-500");
  });
});
