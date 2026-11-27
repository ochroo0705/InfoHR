import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchEditor,
  NO_FORM_MSG,
  SESSION_LOST_TEXT,
  SessionLost,
  type ReportEditor,
  type ReportEditTarget,
} from "../../../api/reportsEdit";
import { bufferName, NO_EDIT_MSG, targetKey, useCellEdit, type CellEditOptions } from "./useCellEdit";

vi.mock("../../../api/reportsEdit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/reportsEdit")>();
  return { ...actual, fetchEditor: vi.fn() };
});

const mockFetch = vi.mocked(fetchEditor);

const TARGET: ReportEditTarget = { route: "cell", person: 7, field: "job_title", kind: "", key: 0, record: 0, salary: false };
const OTHER: ReportEditTarget = { route: "cell", person: 8, field: "job_title", kind: "", key: 0, record: 0, salary: false };

function editor(over: Partial<ReportEditor> = {}): ReportEditor {
  return {
    blocked: "",
    choices: [],
    error: "",
    hidden: {},
    kind: "text",
    label: "Албан тушаал",
    loaded: "tok1",
    maxlength: 50,
    name: "job_title",
    note: "",
    old: "Бат",
    reason: false,
    reason_text: "",
    required: false,
    value: "Бат",
    ...over,
  };
}

// A fetch that the test settles by hand.
function deferredEditor() {
  let resolve!: (value: ReportEditor) => void;
  mockFetch.mockImplementationOnce(
    () =>
      new Promise<ReportEditor>((res) => {
        resolve = res;
      }),
  );
  return { resolve: (e: ReportEditor) => resolve(e) };
}

const ALL_TEXT = (): ReportEditTarget | null => TARGET;

function setup(over: Partial<CellEditOptions> = {}) {
  const props: CellEditOptions = { resetKey: "staff?q=a|1", targetAt: ALL_TEXT, ...over };
  return renderHook((p: CellEditOptions) => useCellEdit(p), { initialProps: props });
}

beforeEach(() => {
  mockFetch.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useCellEdit open", () => {
  it("open with no typed key fetches the editor of the cell and opens it once it has loaded", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 1, c: 2 }));
    expect(mockFetch).toHaveBeenCalledWith(TARGET);
    expect(result.current.editing).toEqual({ r: 1, c: 2 });
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.session?.editor?.name).toBe("job_title");
    expect(result.current.session?.initialText).toBeUndefined();
    expect(result.current.session?.buffered).toEqual([]);
  });

  it("a printable key opens the editor with that key as its starting text", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }, "x"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.session?.initialText).toBe("x");
  });

  it("keys typed while the editor loads are kept, in order, for the editor", async () => {
    const pending = deferredEditor();
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }, "a"));
    act(() => {
      result.current.buffer("b");
      result.current.buffer("Backspace");
      result.current.buffer("c");
    });
    expect(result.current.loading).toBe(true);

    await act(async () => pending.resolve(editor()));
    expect(result.current.loading).toBe(false);
    expect(result.current.session?.initialText).toBe("a");
    expect(result.current.session?.buffered).toEqual(["b", "Backspace", "c"]);
  });

  it("a key typed after the answer but before the render is kept for the editor (the render gap)", async () => {
    const pending = deferredEditor();
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await act(async () => pending.resolve(editor()));
    // The session is set in the ref at once: a key that arrives now still reaches the same buffer the editor mounts with.
    act(() => result.current.buffer("q"));
    expect(result.current.current()?.buffered).toEqual(["q"]);
    expect(result.current.session?.buffered).toEqual(["q"]);
  });

  it("only one editor is open at a time", async () => {
    mockFetch.mockResolvedValue(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    act(() => result.current.open({ r: 1, c: 0 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(result.current.editing).toEqual({ r: 0, c: 0 });
  });

  it("a cell with no edit target never opens an editor and does not fetch", () => {
    const { result } = setup({ targetAt: () => null });

    act(() => result.current.open({ r: 0, c: 0 }, "x"));
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current.editing).toBeNull();
    expect(result.current.session).toBeNull();
  });

  it("a failed open draws no editor and shows the open-failure message, which can be dismissed", async () => {
    mockFetch.mockRejectedValueOnce(new Error("HTTP 500"));
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.notice).not.toBeNull());
    expect(result.current.notice).toEqual({ text: NO_FORM_MSG, tone: "error" });
    expect(result.current.editing).toBeNull();

    act(() => result.current.dismissNotice());
    expect(result.current.notice).toBeNull();
  });

  it("an expired session shows the session-lost text on the open failure", async () => {
    mockFetch.mockRejectedValueOnce(new SessionLost());
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.notice).not.toBeNull());
    expect(result.current.notice?.text).toBe(SESSION_LOST_TEXT);
    expect(result.current.editing).toBeNull();
  });
});

describe("useCellEdit saved texts and epochs", () => {
  it("onSaved closes the editor and keeps the saved text by the target, with no refetch", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 2, c: 1 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.onSaved(TARGET, "Ахлах", result.current.currentEpoch()));

    expect(result.current.editing).toBeNull();
    expect(result.current.overrides.get(targetKey(TARGET))).toBe("Ахлах");
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("setTexts writes many saved texts at once, each under its own target", () => {
    const { result } = setup();

    act(() =>
      result.current.setTexts([
        { target: TARGET, text: "А" },
        { target: OTHER, text: "Б" },
      ]),
    );
    expect(result.current.overrides.get(targetKey(TARGET))).toBe("А");
    expect(result.current.overrides.get(targetKey(OTHER))).toBe("Б");
  });

  it("cancel closes the editor and saves nothing", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.cancel());
    expect(result.current.editing).toBeNull();
    expect(result.current.overrides.size).toBe(0);
  });

  it("cancel during loading drops the answer when it comes", async () => {
    const pending = deferredEditor();
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    act(() => result.current.cancel());
    await act(async () => pending.resolve(editor()));
    expect(result.current.session).toBeNull();
  });

  it("a click or cancel does nothing while a save runs; the editor stays open", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setSaving(true, result.current.currentEpoch()));
    expect(result.current.saving).toBe(true);
    expect(result.current.isSaving()).toBe(true);

    act(() => result.current.cancel());
    expect(result.current.editing).toEqual({ r: 0, c: 0 });

    act(() => result.current.setSaving(false, result.current.currentEpoch()));
    act(() => result.current.cancel());
    expect(result.current.editing).toBeNull();
  });

  it("a new address drops the open editor and the saved texts", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result, rerender } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.onSaved(TARGET, "Шинэ", result.current.currentEpoch()));
    expect(result.current.overrides.size).toBe(1);

    rerender({ resetKey: "staff?q=b|1", targetAt: ALL_TEXT });
    expect(result.current.overrides.size).toBe(0);
    expect(result.current.editing).toBeNull();
  });

  it("an A to B and back to A round trip starts empty: no old saved text comes back", () => {
    const { result, rerender } = setup();

    act(() => result.current.setTexts([{ target: TARGET, text: "Ахлах" }]));
    expect(result.current.overrides.size).toBe(1);

    rerender({ resetKey: "staff?q=b|1", targetAt: ALL_TEXT });
    expect(result.current.overrides.size).toBe(0);
    rerender({ resetKey: "staff?q=a|1", targetAt: ALL_TEXT });
    expect(result.current.overrides.size).toBe(0);
  });

  it("a refetch of the rows (a new data version on the same address) clears the saved texts", () => {
    const { result, rerender } = setup();

    act(() => result.current.setTexts([{ target: TARGET, text: "Ахлах" }]));
    rerender({ resetKey: "staff?q=a|2", targetAt: ALL_TEXT });
    expect(result.current.overrides.size).toBe(0);
  });

  it("a save that finishes after the address changed writes nothing, even after coming back", async () => {
    mockFetch.mockResolvedValueOnce(editor());
    const { result, rerender } = setup();

    act(() => result.current.open({ r: 0, c: 0 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const epochAtSave = result.current.currentEpoch();
    act(() => result.current.setSaving(true, epochAtSave));

    rerender({ resetKey: "staff?q=b|1", targetAt: ALL_TEXT });
    // The old save answers now, from epoch A.
    act(() => result.current.onSaved(TARGET, "Поздно", epochAtSave));
    rerender({ resetKey: "staff?q=a|1", targetAt: ALL_TEXT });
    expect(result.current.overrides.size).toBe(0);
    expect(result.current.session).toBeNull();
  });

  it("a stale setSaving from an old epoch does not lock the new one", () => {
    const { result, rerender } = setup();
    const old = result.current.currentEpoch();
    rerender({ resetKey: "staff?q=b|1", targetAt: ALL_TEXT });
    act(() => result.current.setSaving(true, old));
    expect(result.current.isSaving()).toBe(false);
  });
});

describe("useCellEdit note", () => {
  it("note shows the line and clears it after three seconds", () => {
    vi.useFakeTimers();
    const { result } = setup();

    act(() => result.current.note(NO_EDIT_MSG));
    expect(result.current.notice).toEqual({ text: NO_EDIT_MSG, tone: "note" });

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(result.current.notice).toBeNull();
  });
});

describe("bufferName", () => {
  const key = (k: string, mods: Partial<{ shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }> = {}) => ({
    key: k,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
  });

  it("names the keys grid_nav.js keeps while an editor loads", () => {
    expect(bufferName(key("q"))).toBe("q");
    expect(bufferName(key("1"))).toBe("1");
    expect(bufferName(key("Backspace"))).toBe("Backspace");
    expect(bufferName(key("Enter"))).toBe("Enter");
    expect(bufferName(key("Tab"))).toBe("Tab");
    expect(bufferName(key("Tab", { shiftKey: true }))).toBe("ShiftTab");
    expect(bufferName(key("Escape"))).toBe("Escape");
    expect(bufferName(key("a", { ctrlKey: true }))).toBe("Ctrl+A");
  });

  it("leaves arrows, other shortcuts and names it does not know to the grid", () => {
    expect(bufferName(key("ArrowDown"))).toBeNull();
    expect(bufferName(key("c", { ctrlKey: true }))).toBeNull();
    expect(bufferName(key("Shift"))).toBeNull();
  });
});
