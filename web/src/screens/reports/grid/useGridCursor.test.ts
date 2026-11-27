import { act, renderHook } from "@testing-library/react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { useGridCursor, type GridCursorOptions } from "./useGridCursor";

type Fake = ReactKeyboardEvent<Element> & { preventDefault: Mock };

// A key event whose target is the table itself (the focused grid), as the browser sends it.
function keyEvent(key: string, mods: { shift?: boolean; ctrl?: boolean } = {}): Fake {
  const target = document.createElement("table");
  return {
    key,
    shiftKey: !!mods.shift,
    ctrlKey: !!mods.ctrl,
    metaKey: false,
    altKey: false,
    target,
    currentTarget: target,
    preventDefault: vi.fn(),
  } as unknown as Fake;
}

// Three body rows of three cells each.
const ROWS: string[][] = [
  ["Бат", "Алба", "1"],
  ["Сарнай", "Алба", "2"],
  ["Номин", "Хүний нөөц", "3"],
];

function setup(overrides: Partial<GridCursorOptions> = {}) {
  const props: GridCursorOptions = { rows: ROWS, resetKey: "staff?q=a", ...overrides };
  return renderHook((p: GridCursorOptions) => useGridCursor(p), { initialProps: props });
}

describe("useGridCursor", () => {
  let writeText: Mock;

  beforeEach(() => {
    writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts with no cursor and a click places it", () => {
    const { result } = setup();
    expect(result.current.active).toBeNull();
    act(() => result.current.onCellClick(1, 2, false));
    expect(result.current.active).toEqual({ r: 1, c: 2 });
    expect(result.current.range).toBeNull();
  });

  it("arrows move the cursor and stop at the table edges", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    act(() => result.current.onKeyDown(keyEvent("ArrowDown")));
    expect(result.current.active).toEqual({ r: 1, c: 0 });
    act(() => result.current.onKeyDown(keyEvent("ArrowRight")));
    expect(result.current.active).toEqual({ r: 1, c: 1 });
    act(() => result.current.onKeyDown(keyEvent("ArrowUp")));
    act(() => result.current.onKeyDown(keyEvent("ArrowUp")));
    act(() => result.current.onKeyDown(keyEvent("ArrowUp")));
    expect(result.current.active).toEqual({ r: 0, c: 1 });
    act(() => result.current.onKeyDown(keyEvent("ArrowLeft")));
    act(() => result.current.onKeyDown(keyEvent("ArrowLeft")));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
  });

  it("Home and End go to the row start and end, Ctrl+Home and Ctrl+End to the table corners", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(1, 1, false));
    act(() => result.current.onKeyDown(keyEvent("End")));
    expect(result.current.active).toEqual({ r: 1, c: 2 });
    act(() => result.current.onKeyDown(keyEvent("Home")));
    expect(result.current.active).toEqual({ r: 1, c: 0 });
    act(() => result.current.onKeyDown(keyEvent("End", { ctrl: true })));
    expect(result.current.active).toEqual({ r: 2, c: 2 });
    act(() => result.current.onKeyDown(keyEvent("Home", { ctrl: true })));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
  });

  it("PageDown moves ten rows and stops at the last row", () => {
    const many = Array.from({ length: 25 }, (_, i) => [`n${i}`, "x"]);
    const { result } = setup({ rows: many });
    act(() => result.current.onCellClick(0, 1, false));
    act(() => result.current.onKeyDown(keyEvent("PageDown")));
    expect(result.current.active).toEqual({ r: 10, c: 1 });
    act(() => result.current.onKeyDown(keyEvent("PageDown")));
    act(() => result.current.onKeyDown(keyEvent("PageDown")));
    expect(result.current.active).toEqual({ r: 24, c: 1 });
  });

  it("Tab moves to the next cell and wraps to the next row", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 2, false));
    const tab = keyEvent("Tab");
    act(() => result.current.onKeyDown(tab));
    expect(result.current.active).toEqual({ r: 1, c: 0 });
    expect(tab.preventDefault).toHaveBeenCalled();
  });

  it("Shift+Tab moves back and wraps to the previous row", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(1, 0, false));
    act(() => result.current.onKeyDown(keyEvent("Tab", { shift: true })));
    expect(result.current.active).toEqual({ r: 0, c: 2 });
  });

  it("Tab at the last cell leaves the table: the key is not prevented and the cursor stays", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(2, 2, false));
    const tab = keyEvent("Tab");
    act(() => result.current.onKeyDown(tab));
    expect(result.current.active).toEqual({ r: 2, c: 2 });
    expect(tab.preventDefault).not.toHaveBeenCalled();
  });

  it("Shift+Tab at the first cell leaves the table", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    const tab = keyEvent("Tab", { shift: true });
    act(() => result.current.onKeyDown(tab));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
    expect(tab.preventDefault).not.toHaveBeenCalled();
  });

  it("Shift+arrows grow a range from the cell where it started; a plain arrow drops it", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    act(() => result.current.onKeyDown(keyEvent("ArrowRight", { shift: true })));
    act(() => result.current.onKeyDown(keyEvent("ArrowDown", { shift: true })));
    expect(result.current.active).toEqual({ r: 1, c: 1 });
    expect(result.current.range).toEqual({ r0: 0, r1: 1, c0: 0, c1: 1 });
    act(() => result.current.onKeyDown(keyEvent("ArrowDown")));
    expect(result.current.range).toBeNull();
  });

  it("Shift+click grows the range from the active cell", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    act(() => result.current.onCellClick(2, 1, true));
    expect(result.current.range).toEqual({ r0: 0, r1: 2, c0: 0, c1: 1 });
  });

  it("Escape drops the range and keeps the cursor", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    act(() => result.current.onKeyDown(keyEvent("ArrowDown", { shift: true })));
    act(() => result.current.onKeyDown(keyEvent("Escape")));
    expect(result.current.range).toBeNull();
    expect(result.current.active).toEqual({ r: 1, c: 0 });
  });

  it("Ctrl+C copies the cell as TSV, and the range when there is one", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 1, false));
    const single = keyEvent("c", { ctrl: true });
    act(() => result.current.onKeyDown(single));
    expect(writeText).toHaveBeenLastCalledWith("Алба");
    expect(single.preventDefault).toHaveBeenCalled();

    act(() => result.current.onKeyDown(keyEvent("ArrowDown", { shift: true })));
    act(() => result.current.onKeyDown(keyEvent("ArrowRight", { shift: true })));
    act(() => result.current.onKeyDown(keyEvent("C", { ctrl: true })));
    // The range runs from (0,1) to (1,2): two rows, two columns.
    expect(writeText).toHaveBeenLastCalledWith("Алба\t1\nАлба\t2");
  });

  it("Enter calls onOpenRow for the cell, and Space calls onToggleRow for the row", () => {
    const onOpenRow = vi.fn();
    const onToggleRow = vi.fn();
    const { result } = setup({ onOpenRow, onToggleRow });
    act(() => result.current.onCellClick(1, 0, false));
    const enter = keyEvent("Enter");
    act(() => result.current.onKeyDown(enter));
    expect(onOpenRow).toHaveBeenCalledWith(1, 0);
    expect(enter.preventDefault).toHaveBeenCalled();
    act(() => result.current.onKeyDown(keyEvent(" ")));
    expect(onToggleRow).toHaveBeenCalledWith(1);
  });

  it("an edit hook that takes the key stops Enter from opening the row", () => {
    const onOpenRow = vi.fn();
    const onEditKey = vi.fn(() => true);
    const { result } = setup({ onOpenRow, onEditKey });
    act(() => result.current.onCellClick(0, 2, false));
    act(() => result.current.onKeyDown(keyEvent("Enter")));
    expect(onEditKey).toHaveBeenCalledWith({ r: 0, c: 2 }, expect.anything());
    expect(onOpenRow).not.toHaveBeenCalled();
  });

  it("a click only moves the cursor and never opens the row", () => {
    const onOpenRow = vi.fn();
    const onToggleRow = vi.fn();
    const { result } = setup({ onOpenRow, onToggleRow });
    act(() => result.current.onCellClick(2, 0, false));
    expect(result.current.active).toEqual({ r: 2, c: 0 });
    expect(onOpenRow).not.toHaveBeenCalled();
    expect(onToggleRow).not.toHaveBeenCalled();
  });

  it("keys from an input inside the table are left to that input", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    const input = document.createElement("input");
    const down = keyEvent("ArrowDown");
    Object.defineProperty(down, "target", { value: input });
    act(() => result.current.onKeyDown(down));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
    expect(down.preventDefault).not.toHaveBeenCalled();
  });

  it("a batch append keeps the cursor and the range", () => {
    const { result, rerender } = setup();
    act(() => result.current.onCellClick(2, 1, false));
    act(() => result.current.onKeyDown(keyEvent("ArrowUp", { shift: true })));
    const before = result.current.range;
    rerender({ rows: [...ROWS, ["Дорж", "Алба", "4"], ["Оюун", "Алба", "5"]], resetKey: "staff?q=a" });
    expect(result.current.active).toEqual({ r: 1, c: 1 });
    expect(result.current.range).toEqual(before);
  });

  it("an address change clears the cursor", () => {
    const { result, rerender } = setup();
    act(() => result.current.onCellClick(1, 1, false));
    rerender({ rows: ROWS, resetKey: "staff?q=b" });
    expect(result.current.active).toBeNull();
    expect(result.current.range).toBeNull();
  });

  it("clear() drops the cursor", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(1, 1, false));
    act(() => result.current.clear());
    expect(result.current.active).toBeNull();
  });

  it("focusing the table with no cursor puts it on the first cell", () => {
    const { result } = setup();
    const table = document.createElement("table");
    const focus = { target: table, currentTarget: table } as unknown as Parameters<typeof result.current.onFocus>[0];
    act(() => result.current.onFocus(focus));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
  });

  it("PageUp moves ten rows up and stops at the first row", () => {
    const many = Array.from({ length: 25 }, (_, i) => [`n${i}`, "x"]);
    const { result } = setup({ rows: many });
    act(() => result.current.onCellClick(20, 0, false));
    act(() => result.current.onKeyDown(keyEvent("PageUp")));
    expect(result.current.active).toEqual({ r: 10, c: 0 });
    act(() => result.current.onKeyDown(keyEvent("PageUp")));
    act(() => result.current.onKeyDown(keyEvent("PageUp")));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
  });

  it("with no cursor, the first arrow puts it on row 0, column 0; the next arrow moves from there", () => {
    const { result } = setup();
    act(() => result.current.onKeyDown(keyEvent("ArrowDown")));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
    act(() => result.current.onKeyDown(keyEvent("ArrowDown")));
    expect(result.current.active).toEqual({ r: 1, c: 0 });
  });

  it("Enter with no edit hook opens the row through onOpenRow with the cell; Space ticks the row", () => {
    const onOpenRow = vi.fn();
    const onToggleRow = vi.fn(() => true);
    const { result } = setup({ onOpenRow, onToggleRow });
    act(() => result.current.onCellClick(2, 1, false));
    act(() => result.current.onKeyDown(keyEvent("Enter")));
    expect(onOpenRow).toHaveBeenCalledWith(2, 1);
    act(() => result.current.onKeyDown(keyEvent(" ")));
    expect(onToggleRow).toHaveBeenCalledWith(2);
  });

  it("a Space on a row with no box is not taken", () => {
    const onToggleRow = vi.fn(() => false);
    const { result } = setup({ onToggleRow });
    act(() => result.current.onCellClick(0, 0, false));
    const space = keyEvent(" ");
    act(() => result.current.onKeyDown(space));
    expect(onToggleRow).toHaveBeenCalledWith(0);
    expect(space.preventDefault).not.toHaveBeenCalled();
  });

  it("keys from a header link do not drive the cursor", () => {
    const { result } = setup();
    act(() => result.current.onCellClick(0, 0, false));
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const link = document.createElement("a");
    link.href = "/reports/staff/?sort=name";
    table.append(thead);
    thead.append(link);
    const down = keyEvent("ArrowDown");
    Object.defineProperty(down, "target", { value: link });
    act(() => result.current.onKeyDown(down));
    expect(result.current.active).toEqual({ r: 0, c: 0 });
    expect(down.preventDefault).not.toHaveBeenCalled();
  });

  it("a forward Tab at the last cell focuses the next focusable element after the table and is prevented", () => {
    const before = document.createElement("button");
    const table = document.createElement("table");
    const after = document.createElement("button");
    document.body.append(before, table, after);
    try {
      const { result } = setup();
      act(() => result.current.onCellClick(2, 2, false));
      const tab = keyEvent("Tab");
      Object.defineProperty(tab, "currentTarget", { value: table });
      Object.defineProperty(tab, "target", { value: table });
      act(() => result.current.onKeyDown(tab));
      expect(document.activeElement).toBe(after);
      expect(tab.preventDefault).toHaveBeenCalled();
    } finally {
      before.remove();
      table.remove();
      after.remove();
    }
  });
});
