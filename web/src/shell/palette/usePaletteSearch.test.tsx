// usePaletteSearch: the debounce, the latest query winning, the busy dim, the failure line, «show all» and the empty box's
// recent and from parameters. fetchPalette is replaced by a mock, so each test decides when an answer arrives.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPalette, type PaletteOut } from "../../api/palette";
import { BUSY_MS, DEBOUNCE_MS, requestKeyOf, usePaletteSearch } from "./usePaletteSearch";
import { remember } from "./recents";

vi.mock("../../api/palette", () => ({ fetchPalette: vi.fn() }));

const fetchMockPalette = vi.mocked(fetchPalette);

function answerFor(title: string): PaletteOut {
  return {
    empty: false,
    empty_text: "Юу ч олдсонгүй",
    fallback: [],
    fallback_heading: "Эсвэл нээх:",
    groups: [{ key: "people", title, count: 0, total: null, rows: [], note: "" }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function memoryStorage(): Storage {
  const raw = new Map<string, string>();
  return {
    getItem: (key: string) => (raw.has(key) ? (raw.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      raw.set(key, String(value));
    },
    removeItem: (key: string) => {
      raw.delete(key);
    },
  } as unknown as Storage;
}

type Props = { q: string; from?: string; storage?: Storage | null };

function setup(initial: Props) {
  return renderHook(
    (props: Props) =>
      usePaletteSearch({
        q: props.q,
        from: props.from ?? "/",
        storage: props.storage === undefined ? null : props.storage,
        userId: 7,
      }),
    { initialProps: initial },
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("usePaletteSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchMockPalette.mockReset();
    fetchMockPalette.mockResolvedValue(answerFor("Хүмүүс"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces typing into one request", async () => {
    const { rerender } = setup({ q: "" });
    expect(fetchMockPalette).toHaveBeenCalledTimes(1); // the panel opens with an empty box: asked at once
    fetchMockPalette.mockClear();

    rerender({ q: "a" });
    await advance(100);
    rerender({ q: "ab" });
    await advance(100);
    rerender({ q: "abc" });
    await advance(DEBOUNCE_MS - 1);
    expect(fetchMockPalette).not.toHaveBeenCalled();

    await advance(1);
    expect(fetchMockPalette).toHaveBeenCalledTimes(1);
    expect(fetchMockPalette.mock.calls[0][0]).toEqual({ q: "abc", more: false });
  });

  it("latest query wins when answers arrive out of order", async () => {
    const first = deferred<PaletteOut>();
    const second = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const { result, rerender } = setup({ q: "а" });
    rerender({ q: "ab" });
    await advance(DEBOUNCE_MS);
    expect(fetchMockPalette).toHaveBeenCalledTimes(2);

    const firstSignal = fetchMockPalette.mock.calls[0][1] as AbortSignal;
    expect(firstSignal.aborted).toBe(true);

    await act(async () => {
      second.resolve(answerFor("новый"));
    });
    await act(async () => {
      first.resolve(answerFor("хуучин"));
    });
    expect(result.current.answer?.groups[0].title).toBe("новый");
  });

  it("busy appears only after 150 ms", async () => {
    fetchMockPalette.mockReturnValueOnce(new Promise(() => undefined));
    const { result } = setup({ q: "Бат" });
    await advance(BUSY_MS - 1);
    expect(result.current.busy).toBe(false);
    await advance(1);
    expect(result.current.busy).toBe(true);
  });

  it("busy clears on answer and on error", async () => {
    const answered = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(answered.promise);
    const { result } = setup({ q: "Бат" });
    await advance(BUSY_MS);
    expect(result.current.busy).toBe(true);
    await act(async () => {
      answered.resolve(answerFor("Хүмүүс"));
    });
    expect(result.current.busy).toBe(false);

    const failing = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(failing.promise);
    const second = setup({ q: "Бат" });
    await advance(BUSY_MS);
    expect(second.result.current.busy).toBe(true);
    await act(async () => {
      failing.reject(new Error("HTTP 500"));
    });
    expect(second.result.current.busy).toBe(false);
  });

  it("failed shows after a rejected request and clears on the next success", async () => {
    fetchMockPalette.mockRejectedValueOnce(new Error("HTTP 500"));
    const { result, rerender } = setup({ q: "Бат" });
    await act(async () => undefined);
    expect(result.current.failed).toBe(true);
    expect(result.current.answer).toBeNull();

    rerender({ q: "Бат2" });
    await advance(DEBOUNCE_MS);
    expect(result.current.failed).toBe(false);
    expect(result.current.answer?.groups[0].title).toBe("Хүмүүс");
  });

  it("showAll re-asks with more=1 and keeps the answer", async () => {
    const { result } = setup({ q: "Бат" });
    await advance(DEBOUNCE_MS);
    expect(result.current.answer).not.toBeNull();
    fetchMockPalette.mockClear();

    act(() => result.current.showAll());
    expect(fetchMockPalette).toHaveBeenCalledTimes(1);
    expect(fetchMockPalette.mock.calls[0][0]).toEqual({ q: "Бат", more: true });
    expect(result.current.answer).not.toBeNull();
  });

  it("empty box sends the recent param and the from path", async () => {
    const storage = memoryStorage();
    remember(storage, "p:3", 7);
    remember(storage, "s:/leave/", 7);
    setup({ q: "", from: "/employees/5/", storage });
    await act(async () => undefined);
    expect(fetchMockPalette.mock.calls[0][0]).toEqual({
      q: "",
      recent: "s:/leave/,p:3",
      from: "/employees/5/",
    });
  });

  it("an aborted request is not an error", async () => {
    const first = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(first.promise);
    const { result, rerender } = setup({ q: "а" });
    rerender({ q: "ab" });
    // The superseded request rejects the way a fetch does when it is aborted.
    await act(async () => {
      first.reject(new DOMException("The operation was aborted.", "AbortError"));
    });
    expect(result.current.failed).toBe(false);
  });

  it("a new query keeps the dim until its own answer arrives", async () => {
    const first = deferred<PaletteOut>();
    const second = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = setup({ q: "а" });
    await advance(BUSY_MS);
    expect(result.current.busy).toBe(true);

    rerender({ q: "ab" });
    await advance(DEBOUNCE_MS);
    expect(result.current.busy).toBe(true);

    await act(async () => {
      second.resolve(answerFor("Хүмүүс"));
    });
    expect(result.current.busy).toBe(false);
  });

  it("unmounting aborts the request in flight and clears the busy timer", async () => {
    const pending = deferred<PaletteOut>();
    fetchMockPalette.mockReturnValueOnce(pending.promise);
    const { unmount } = setup({ q: "Бат" });
    await advance(BUSY_MS - 50);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    const signal = fetchMockPalette.mock.calls[0][1] as AbortSignal;

    unmount();
    expect(signal.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    // A late answer or error after close changes nothing and does not throw.
    await act(async () => {
      pending.reject(new Error("HTTP 500"));
    });
  });

  it("reports more for a show-all answer", async () => {
    const { result } = setup({ q: "Бат" });
    await advance(DEBOUNCE_MS);
    expect(result.current.more).toBe(false);
    act(() => result.current.showAll());
    await act(async () => undefined);
    expect(result.current.more).toBe(true);
  });
});

describe("requestKeyOf", () => {
  it("different requests never share a key, even when a plain join would collide", () => {
    // "a1" + more 1 + tick 1 and "a" + more 1 + tick 11 would both read "a11" with a plain join.
    expect(requestKeyOf("a1", true, 1)).not.toBe(requestKeyOf("a", true, 11));
    expect(requestKeyOf("a", false, 0)).not.toBe(requestKeyOf("a", true, 0));
    expect(requestKeyOf("a", true, 2)).toBe(requestKeyOf("a", true, 2));
  });
});

