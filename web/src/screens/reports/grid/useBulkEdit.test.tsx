import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportCellOut } from "../../../api/reports";
import {
  bulkCells,
  SESSION_LOST_TEXT,
  SessionLost,
  type ReportEditTarget,
} from "../../../api/reportsEdit";
import { useBulkEdit, MAX_CELLS, TOO_MANY, type BulkLookupRow } from "./useBulkEdit";
import { targetKey } from "./useCellEdit";

vi.mock("../../../api/reportsEdit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/reportsEdit")>();
  return { ...actual, bulkCells: vi.fn() };
});

const mockBulk = vi.mocked(bulkCells);

// An edit target of the cell route for one person's field.
function T(person: number, field: string): ReportEditTarget {
  return { route: "cell", person, field, kind: "", key: 0, record: 0, salary: false };
}

// A drawn cell: its text and the edit target it carries (null: it cannot be edited).
function cell(text: string, edit: ReportEditTarget | null): ReportCellOut {
  return { value: text, text, money: false, href: "", css: "", style: "", person: 0, edit };
}

function row(...cells: ReportCellOut[]): BulkLookupRow {
  return { texts: cells.map((c) => c.text), cells };
}

// The answer of the server: a cell is refused when its person|field is in `refused`; the others keep the posted text.
function answer(cells: { person: number; field: string; text: string }[], refused: string[] = []) {
  return {
    saved: 0,
    cells: cells.map((c) => {
      const no = refused.includes(`${c.person}|${c.field}`);
      return { person: c.person, field: c.field, ok: !no, text: no ? "" : c.text, error: no ? "Алдаа" : "" };
    }),
  };
}

// Two people with two fields each, texts "Бат" and "Сарнай".
function twoByTwo(): BulkLookupRow[] {
  return [
    row(cell("Бат", T(1, "f1")), cell("Бат", T(1, "f2"))),
    row(cell("Сарнай", T(2, "f1")), cell("Сарнай", T(2, "f2"))),
  ];
}

function setup(rows: BulkLookupRow[], resetKey = "k1") {
  const setTexts = vi.fn();
  const onClosed = vi.fn();
  const hook = renderHook(
    (props: { resetKey: string; rows: BulkLookupRow[] }) =>
      useBulkEdit({ resetKey: props.resetKey, rows: props.rows, currentEpoch: () => 1, setTexts, onClosed }),
    { initialProps: { resetKey, rows } },
  );
  return { hook, setTexts, onClosed };
}

beforeEach(() => {
  mockBulk.mockReset();
  mockBulk.mockImplementation(async (cells) => answer(cells));
});

describe("useBulkEdit: paste and the dry run", () => {
  it("a paste of 2x2 text makes ONE dry run with four cells, apply false", async () => {
    const { hook } = setup(twoByTwo());
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "a\tb\nc\td", null));

    await waitFor(() => expect(hook.result.current.bar?.message).toBeDefined());
    expect(mockBulk).toHaveBeenCalledTimes(1);
    expect(mockBulk).toHaveBeenCalledWith(
      [
        { person: 1, field: "f1", text: "a", old: "Бат" },
        { person: 1, field: "f2", text: "b", old: "Бат" },
        { person: 2, field: "f1", text: "c", old: "Сарнай" },
        { person: 2, field: "f2", text: "d", old: "Сарнай" },
      ],
      false,
    );
  });

  it("the preview marks the right cells: amber for a change, red with the reason for a refusal", async () => {
    const { hook } = setup(twoByTwo());
    mockBulk.mockImplementation(async (cells) => answer(cells, ["2|f1"]));
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x\tБат\ny\tz", null));

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("2 нүд өөрчлөгдөнө · 1 алдаатай · 0 засах боломжгүй"));
    expect(hook.result.current.marks.get("0:0")).toEqual({ kind: "pending" });
    expect(hook.result.current.marks.has("0:1")).toBe(false); // unchanged text: no mark
    expect(hook.result.current.marks.get("1:0")).toEqual({ kind: "rejected", title: "Алдаа" });
    expect(hook.result.current.marks.get("1:1")).toEqual({ kind: "pending" });
    expect(hook.result.current.previews.get(targetKey(T(1, "f1")))).toBe("x");
  });

  it("a Shift range with one pasted value fills every cell of the range", async () => {
    const { hook } = setup(twoByTwo());
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "Жишээ", { r0: 0, r1: 1, c0: 0, c1: 1 }));

    await waitFor(() => expect(mockBulk).toHaveBeenCalledTimes(1));
    expect(mockBulk.mock.calls[0][0].map((c) => c.text)).toEqual(["Жишээ", "Жишээ", "Жишээ", "Жишээ"]);
  });
});

describe("useBulkEdit: save and undo", () => {
  it("Хадгалах sends apply true with only the ok changed cells, then sets their texts", async () => {
    const { hook, setTexts } = setup(twoByTwo());
    mockBulk.mockImplementation(async (cells) => answer(cells, ["2|f1"]));
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x\tБат\ny\tz", null));
    await waitFor(() => expect(hook.result.current.bar?.actions.length).toBe(2));

    mockBulk.mockClear();
    mockBulk.mockImplementation(async (cells) => answer(cells));
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run());

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("2 нүд хадгалагдлаа · 1 хадгалагдсангүй"));
    expect(mockBulk).toHaveBeenCalledTimes(1);
    expect(mockBulk).toHaveBeenCalledWith(
      [
        { person: 1, field: "f1", text: "x", old: "Бат" },
        { person: 2, field: "f2", text: "z", old: "Сарнай" },
      ],
      true,
    );
    expect(setTexts).toHaveBeenCalledWith(
      [
        { target: T(1, "f1"), text: "x" },
        { target: T(2, "f2"), text: "z" },
      ],
      1,
    );
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Буцаах", "Хаах"]);
  });

  it("Буцаах sends the old texts as a new batch with apply true", async () => {
    const { hook, setTexts } = setup(twoByTwo());
    mockBulk.mockImplementation(async (cells) => answer(cells, ["2|f1"]));
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x\tБат\ny\tz", null));
    await waitFor(() => expect(hook.result.current.bar?.actions.length).toBe(2));
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run());
    await waitFor(() => expect(hook.result.current.bar?.actions.some((a) => a.label === "Буцаах")).toBe(true));

    mockBulk.mockClear();
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Буцаах")!.run());

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("Буцаалаа: 2"));
    expect(mockBulk).toHaveBeenCalledWith(
      [
        { person: 1, field: "f1", text: "Бат", old: "x" },
        { person: 2, field: "f2", text: "Сарнай", old: "z" },
      ],
      true,
    );
    expect(setTexts).toHaveBeenLastCalledWith(
      [
        { target: T(1, "f1"), text: "Бат" },
        { target: T(2, "f2"), text: "Сарнай" },
      ],
      1,
    );
  });
});

describe("useBulkEdit: limits, targets and the bar", () => {
  it("over 500 cells shows TOO_MANY and sends no request", () => {
    const rows = Array.from({ length: MAX_CELLS + 1 }, (_, i) => row(cell(`v${i}`, T(i + 1, "f"))));
    const { hook } = setup(rows);
    act(() => hook.result.current.setRange({ r0: 0, r1: MAX_CELLS, c0: 0, c1: 0 }, "x"));

    expect(mockBulk).not.toHaveBeenCalled();
    expect(hook.result.current.bar?.message).toBe(TOO_MANY);
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Хаах"]);
  });

  it("a correction cell and a row cell in the range are counted as not editable", async () => {
    const rows = [
      row(
        cell("Бат", T(1, "f1")),
        cell("Бат", { ...T(1, "f2"), route: "correct", record: 3 }),
        cell("Бат", { ...T(1, "f3"), route: "row", kind: "child", key: 4 }),
      ),
    ];
    const { hook } = setup(rows);
    act(() => hook.result.current.setRange({ r0: 0, r1: 0, c0: 0, c1: 2 }, "x"));

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("1 нүд өөрчлөгдөнө · 0 алдаатай · 2 засах боломжгүй"));
    expect(mockBulk).toHaveBeenCalledTimes(1);
    expect(mockBulk.mock.calls[0][0]).toEqual([{ person: 1, field: "f1", text: "x", old: "Бат" }]);
  });

  it("Esc discards the preview and changes nothing", async () => {
    const { hook, setTexts, onClosed } = setup(twoByTwo());
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x\ty\nz\tw", null));
    await waitFor(() => expect(hook.result.current.bar?.actions.length).toBe(2));

    const preventDefault = vi.fn();
    act(() => {
      expect(hook.result.current.onKey({ key: "Escape", preventDefault })).toBe(true);
    });

    expect(preventDefault).toHaveBeenCalled();
    expect(hook.result.current.bar).toBeNull();
    expect(hook.result.current.marks.size).toBe(0);
    expect(hook.result.current.previews.size).toBe(0);
    expect(mockBulk).toHaveBeenCalledTimes(1); // the dry run only
    expect(setTexts).not.toHaveBeenCalled();
    expect(onClosed).toHaveBeenCalledTimes(1);
  });

  it("a session-lost answer shows the verbatim text in the bar and marks nothing", async () => {
    const { hook } = setup(twoByTwo());
    mockBulk.mockRejectedValueOnce(new SessionLost());
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x", { r0: 0, r1: 0, c0: 0, c1: 1 }));

    await waitFor(() => expect(hook.result.current.bar?.message).toBe(SESSION_LOST_TEXT));
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Хаах"]);
    expect(hook.result.current.marks.size).toBe(0);
  });

  it("a new address discards the batch", async () => {
    const { hook } = setup(twoByTwo());
    act(() => hook.result.current.paste({ r: 0, c: 0 }, "x", null));
    await waitFor(() => expect(hook.result.current.bar).not.toBeNull());

    hook.rerender({ resetKey: "k2", rows: twoByTwo() });

    await waitFor(() => expect(hook.result.current.bar).toBeNull());
    expect(hook.result.current.marks.size).toBe(0);
  });

  it("a batch with no editable cell shows the not-editable count and only a close button", () => {
    const rows = [row(cell("Бат", null), cell("Сарнай", null))];
    const { hook } = setup(rows);
    act(() => hook.result.current.setRange({ r0: 0, r1: 0, c0: 0, c1: 1 }, "x"));

    expect(mockBulk).not.toHaveBeenCalled();
    expect(hook.result.current.bar?.message).toBe("0 нүд өөрчлөгдөнө · 0 алдаатай · 2 засах боломжгүй");
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Хаах"]);
  });
});

// A preview of a 2x2 paste where (2, f1) is refused: two cells will change, one is refused.
async function previewOf(hook: ReturnType<typeof setup>["hook"]) {
  mockBulk.mockImplementation(async (cells) => answer(cells, ["2|f1"]));
  act(() => hook.result.current.paste({ r: 0, c: 0 }, "x\tБат\ny\tz", null));
  await waitFor(() => expect(hook.result.current.bar?.actions.length).toBe(2));
}

describe("useBulkEdit: double save, session lost, undo timer", () => {
  it("Хадгалах pressed twice sends ONE apply true request", async () => {
    const { hook } = setup(twoByTwo());
    await previewOf(hook);
    mockBulk.mockClear();
    mockBulk.mockImplementation(async (cells) => answer(cells));

    const save = hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run;
    await act(async () => {
      save();
      save();
    });

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("2 нүд хадгалагдлаа · 1 хадгалагдсангүй"));
    expect(mockBulk.mock.calls.filter((c) => c[1] === true)).toHaveLength(1);
  });

  it("Enter pressed twice in the preview sends ONE apply true request", async () => {
    const { hook } = setup(twoByTwo());
    await previewOf(hook);
    mockBulk.mockClear();
    mockBulk.mockImplementation(async (cells) => answer(cells));

    await act(async () => {
      hook.result.current.onKey({ key: "Enter", preventDefault: vi.fn() });
      hook.result.current.onKey({ key: "Enter", preventDefault: vi.fn() });
    });

    await waitFor(() => expect(hook.result.current.bar?.message).toBe("2 нүд хадгалагдлаа · 1 хадгалагдсангүй"));
    expect(mockBulk.mock.calls.filter((c) => c[1] === true)).toHaveLength(1);
  });

  it("a 401 on save shows the verbatim session-lost text and changes no cell", async () => {
    const { hook, setTexts } = setup(twoByTwo());
    await previewOf(hook);
    mockBulk.mockRejectedValueOnce(new SessionLost());
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run());

    await waitFor(() => expect(hook.result.current.bar?.message).toBe(SESSION_LOST_TEXT));
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Хаах"]);
    expect(hook.result.current.marks.size).toBe(0);
    expect(setTexts).not.toHaveBeenCalled();
  });

  it("a 401 on undo shows the verbatim session-lost text in the bar", async () => {
    const { hook } = setup(twoByTwo());
    await previewOf(hook);
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run());
    await waitFor(() => expect(hook.result.current.bar?.actions.some((a) => a.label === "Буцаах")).toBe(true));

    mockBulk.mockRejectedValueOnce(new SessionLost());
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Буцаах")!.run());

    await waitFor(() => expect(hook.result.current.bar?.message).toBe(SESSION_LOST_TEXT));
    expect(hook.result.current.bar?.actions.map((a) => a.label)).toEqual(["Хаах"]);
  });

  it("after an undo the bar closes itself after 4 seconds", async () => {
    const { hook } = setup(twoByTwo());
    await previewOf(hook);
    await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Хадгалах")!.run());
    await waitFor(() => expect(hook.result.current.bar?.actions.some((a) => a.label === "Буцаах")).toBe(true));
    // The fake clock starts after the real-time waits (waitFor needs real timers).
    vi.useFakeTimers();
    try {
      await act(async () => hook.result.current.bar!.actions.find((a) => a.label === "Буцаах")!.run());
      expect(hook.result.current.bar?.message).toBe("Буцаалаа: 2");

      act(() => vi.advanceTimersByTime(3999));
      expect(hook.result.current.bar).not.toBeNull();
      act(() => vi.advanceTimersByTime(1));
      expect(hook.result.current.bar).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
