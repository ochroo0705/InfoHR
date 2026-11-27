// Port of app/static/js/grid_nav.test.mjs (the pure helpers). Each case of the Node spec is one case here, with the same
// inputs and expected outputs, in the same order.
import { describe, expect, it } from "vitest";
import {
  applyBuffered,
  box,
  columnKinds,
  isPrintable,
  move,
  parseTsv,
  planFill,
  planPaste,
  planSet,
  sessionLost,
  splitBuffered,
  toTsv,
} from "./gridMath";

const W = [4, 4, 1, 4]; // row 2 is a group title (one wide cell)

// A keyboard event with the three modifier flags the helper reads.
function ev(key: string, mods: { ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean } = {}) {
  return { key, ctrlKey: mods.ctrlKey ?? false, metaKey: mods.metaKey ?? false, altKey: mods.altKey ?? false };
}

describe("gridMath (port of grid_nav.test.mjs)", () => {
  it("arrows move one cell and stop at the edges", () => {
    expect(move({ r: 0, c: 0 }, "ArrowRight", W)).toEqual({ r: 0, c: 1 });
    expect(move({ r: 0, c: 0 }, "ArrowUp", W)).toEqual({ r: 0, c: 0 });
    expect(move({ r: 0, c: 0 }, "ArrowLeft", W)).toEqual({ r: 0, c: 0 });
    expect(move({ r: 3, c: 3 }, "ArrowDown", W)).toEqual({ r: 3, c: 3 });
  });

  it("a narrow row clamps the column", () => {
    expect(move({ r: 1, c: 3 }, "ArrowDown", W)).toEqual({ r: 2, c: 0 });
  });

  it("Home/End and Ctrl variants", () => {
    expect(move({ r: 1, c: 2 }, "Home", W)).toEqual({ r: 1, c: 0 });
    expect(move({ r: 1, c: 0 }, "End", W)).toEqual({ r: 1, c: 3 });
    expect(move({ r: 1, c: 2 }, "Home", W, true)).toEqual({ r: 0, c: 0 });
    expect(move({ r: 0, c: 0 }, "End", W, true)).toEqual({ r: 3, c: 3 });
    expect(move({ r: 1, c: 2 }, "ArrowDown", W, true)).toEqual({ r: 3, c: 2 });
  });

  it("PageDown clamps to the last row", () => {
    expect(move({ r: 0, c: 1 }, "PageDown", W)).toEqual({ r: 3, c: 1 });
  });

  it("Tab wraps to the next row and stays put at the very end", () => {
    expect(move({ r: 0, c: 3 }, "Tab", W)).toEqual({ r: 1, c: 0 });
    expect(move({ r: 3, c: 3 }, "Tab", W)).toEqual({ r: 3, c: 3 });
    expect(move({ r: 1, c: 0 }, "ShiftTab", W)).toEqual({ r: 0, c: 3 });
    expect(move({ r: 0, c: 0 }, "ShiftTab", W)).toEqual({ r: 0, c: 0 });
  });

  it("other keys are not moves", () => {
    expect(move({ r: 0, c: 0 }, "a", W)).toBeNull();
  });

  it("box and TSV", () => {
    expect(box({ r: 3, c: 0 }, { r: 1, c: 2 })).toEqual({ r0: 1, r1: 3, c0: 0, c1: 2 });
    expect(toTsv([["a", "b\tc"], [" d\n", 1]])).toBe("a\tb c\nd\t1");
  });

  it("parseTsv splits rows on line breaks and cells on tabs", () => {
    expect(parseTsv("a\tb\nc\td")).toEqual([["a", "b"], ["c", "d"]]);
    expect(parseTsv("a\tb\r\nc\td\r\n")).toEqual([["a", "b"], ["c", "d"]]);
    expect(parseTsv("a\tb\n")).toEqual([["a", "b"]]);
    expect(parseTsv("a\n\n")).toEqual([["a"], [""]]);
    expect(parseTsv("")).toEqual([]);
  });

  it('parseTsv reads Excel quoted cells: "" is a quote, tabs and line breaks stay inside', () => {
    expect(parseTsv('"Ж""К"\tx')).toEqual([['Ж"К', "x"]]);
    expect(parseTsv('"a\nb"\tc\n')).toEqual([["a\nb", "c"]]);
    expect(parseTsv('"a\tb"\tc')).toEqual([["a\tb", "c"]]);
    expect(parseTsv('""\tx')).toEqual([["", "x"]]);
    expect(parseTsv('"a\r\nb"\r\nc')).toEqual([["a\r\nb"], ["c"]]);
  });

  it("parseTsv keeps a quote inside unquoted text as text", () => {
    expect(parseTsv('x"y\tz')).toEqual([['x"y', "z"]]);
  });

  it("applyBuffered: text keys append, Backspace removes the last character", () => {
    expect(applyBuffered("Аб", ["в", "г"])).toBe("Абвг");
    expect(applyBuffered("abc", ["Backspace", "Backspace"])).toBe("a");
    expect(applyBuffered("", ["Backspace"])).toBe("");
  });

  it("applyBuffered: Ctrl+A then typing replaces the text; Ctrl+A then Backspace clears it", () => {
    expect(applyBuffered("old", ["Ctrl+A", "n", "e", "w"])).toBe("new");
    expect(applyBuffered("old", ["Ctrl+A", "Backspace"])).toBe("");
    expect(applyBuffered("old", ["Ctrl+A"])).toBe("old");
    expect(applyBuffered("old", ["x", "Ctrl+A", "y"])).toBe("y");
  });

  it("splitBuffered: the text keys before the first Enter, Tab or Escape, and that key", () => {
    expect(splitBuffered(["a", "b", "Enter", "c"])).toEqual({ text: ["a", "b"], action: "Enter" });
    expect(splitBuffered(["a", "ShiftTab"])).toEqual({ text: ["a"], action: "ShiftTab" });
    expect(splitBuffered(["Escape"])).toEqual({ text: [], action: "Escape" });
    expect(splitBuffered(["a"])).toEqual({ text: ["a"], action: null });
    expect(splitBuffered([])).toEqual({ text: [], action: null });
  });

  it("planPaste lays rows from the origin, right and down", () => {
    const W3 = [4, 4, 4];
    expect(planPaste({ r: 1, c: 1 }, [["a", "b"], ["c", "d"]], W3, null)).toEqual([
      { r: 1, c: 1, text: "a" },
      { r: 1, c: 2, text: "b" },
      { r: 2, c: 1, text: "c" },
      { r: 2, c: 2, text: "d" },
    ]);
  });

  it("planPaste clips rows past widths.length and cells past a row's width", () => {
    expect(planPaste({ r: 1, c: 0 }, [["a"], ["b"], ["c"]], [4, 4], null)).toEqual([{ r: 1, c: 0, text: "a" }]);
    expect(planPaste({ r: 0, c: 1 }, [["a", "b", "c"]], [2, 2], null)).toEqual([{ r: 0, c: 1, text: "a" }]);
    // a group-title row has one cell: a second column of the paste is dropped there
    expect(planPaste({ r: 1, c: 0 }, [["a", "b"]], [4, 1], null)).toEqual([{ r: 1, c: 0, text: "a" }]);
  });

  it("planPaste of one value onto a range fills the whole range", () => {
    const out = planPaste({ r: 0, c: 0 }, [["x"]], [3, 3], { r0: 0, r1: 1, c0: 0, c1: 2 });
    expect(out).toEqual([
      { r: 0, c: 0, text: "x" }, { r: 0, c: 1, text: "x" }, { r: 0, c: 2, text: "x" },
      { r: 1, c: 0, text: "x" }, { r: 1, c: 1, text: "x" }, { r: 1, c: 2, text: "x" },
    ]);
  });

  it("planPaste of one value without a range writes one cell", () => {
    expect(planPaste({ r: 2, c: 1 }, [["x"]], [3, 3, 3], null)).toEqual([{ r: 2, c: 1, text: "x" }]);
  });

  it("planPaste of a block onto a range lays it from the origin, not repeated", () => {
    const out = planPaste({ r: 0, c: 0 }, [["a", "b"]], [2, 2], { r0: 0, r1: 1, c0: 0, c1: 1 });
    expect(out).toEqual([{ r: 0, c: 0, text: "a" }, { r: 0, c: 1, text: "b" }]);
  });

  it("planPaste of parsed text with a trailing line break adds no row", () => {
    expect(planPaste({ r: 0, c: 0 }, parseTsv("a\n"), [2, 2], null)).toEqual([{ r: 0, c: 0, text: "a" }]);
  });

  it("planFill copies the top row of each column down the range", () => {
    const out = planFill({ r0: 0, r1: 2, c0: 0, c1: 1 }, (r, c) => `${r}${c}`);
    expect(out).toEqual([
      { r: 1, c: 0, text: "00" }, { r: 2, c: 0, text: "00" },
      { r: 1, c: 1, text: "01" }, { r: 2, c: 1, text: "01" },
    ]);
  });

  it("planFill of a single row changes nothing", () => {
    expect(planFill({ r0: 4, r1: 4, c0: 0, c1: 2 }, () => "v")).toEqual([]);
  });

  it("planSet gives every cell of the range the text", () => {
    expect(planSet({ r0: 1, r1: 2, c0: 0, c1: 1 }, "v")).toEqual([
      { r: 1, c: 0, text: "v" }, { r: 1, c: 1, text: "v" },
      { r: 2, c: 0, text: "v" }, { r: 2, c: 1, text: "v" },
    ]);
  });

  it("isPrintable: one character, no Ctrl, Meta or Alt", () => {
    // The JS spec also passes shiftKey: true for "A"; Shift is not read by the helper, so it is left out here.
    expect(isPrintable(ev("a"))).toBe(true);
    expect(isPrintable(ev("A"))).toBe(true);
    expect(isPrintable(ev("ө"))).toBe(true);
    expect(isPrintable(ev("a", { ctrlKey: true }))).toBe(false);
    expect(isPrintable(ev("c", { metaKey: true }))).toBe(false);
    expect(isPrintable(ev("a", { altKey: true }))).toBe(false);
  });

  it("isPrintable: names of keys are not printable", () => {
    expect(isPrintable(ev("Enter"))).toBe(false);
    expect(isPrintable(ev("F2"))).toBe(false);
    expect(isPrintable(ev("ArrowDown"))).toBe(false);
    expect(isPrintable(ev("Dead"))).toBe(false);
  });

  it("sessionLost: a fetch that ended on the login page", () => {
    expect(sessionLost({ url: "http://x/login/?next=/a" })).toBe(true);
    expect(sessionLost({ url: "http://x/reports/cell/" })).toBe(false);
    expect(sessionLost({ url: "http://x/reports/x/" })).toBe(false);
  });

  it("columnKinds: a column with an editable cell is edit, with a correction cell is correct, else empty", () => {
    const E = { edit: true, correct: false };
    const C = { edit: true, correct: true };
    const N = { edit: false, correct: false };
    expect(columnKinds([[N, E, N], [N, E, N]])).toEqual(["", "edit", ""]);
    expect(columnKinds([[C, N], [N, N]])).toEqual(["correct", ""]);
    // one correction cell makes the whole column a correction column
    expect(columnKinds([[E, E], [C, N]])).toEqual(["correct", "edit"]);
  });

  it("columnKinds: ragged rows give one kind per column of the widest row", () => {
    const E = { edit: true, correct: false };
    const N = { edit: false, correct: false };
    expect(columnKinds([[N], [N, N, E]])).toEqual(["", "", "edit"]);
    expect(columnKinds([])).toEqual([]);
    expect(columnKinds([[]])).toEqual([]);
  });
});
