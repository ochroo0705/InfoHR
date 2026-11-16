// Unit tests for grid_nav.js pure helpers. Run: node --test <this file>.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { move, box, toTsv, parseTsv, planPaste, planFill, planSet, isPrintable, splitBuffered, applyBuffered, sessionLost, columnKinds } =
  require("./grid_nav.js");
const W = [4, 4, 1, 4]; // row 2 is a group title (one wide cell)

test("arrows move one cell and stop at the edges", () => {
  assert.deepEqual(move({ r: 0, c: 0 }, "ArrowRight", W), { r: 0, c: 1 });
  assert.deepEqual(move({ r: 0, c: 0 }, "ArrowUp", W), { r: 0, c: 0 });
  assert.deepEqual(move({ r: 0, c: 0 }, "ArrowLeft", W), { r: 0, c: 0 });
  assert.deepEqual(move({ r: 3, c: 3 }, "ArrowDown", W), { r: 3, c: 3 });
});

test("a narrow row clamps the column", () => {
  assert.deepEqual(move({ r: 1, c: 3 }, "ArrowDown", W), { r: 2, c: 0 });
});

test("Home/End and Ctrl variants", () => {
  assert.deepEqual(move({ r: 1, c: 2 }, "Home", W), { r: 1, c: 0 });
  assert.deepEqual(move({ r: 1, c: 0 }, "End", W), { r: 1, c: 3 });
  assert.deepEqual(move({ r: 1, c: 2 }, "Home", W, true), { r: 0, c: 0 });
  assert.deepEqual(move({ r: 0, c: 0 }, "End", W, true), { r: 3, c: 3 });
  assert.deepEqual(move({ r: 1, c: 2 }, "ArrowDown", W, true), { r: 3, c: 2 });
});

test("PageDown clamps to the last row", () => {
  assert.deepEqual(move({ r: 0, c: 1 }, "PageDown", W), { r: 3, c: 1 });
});

test("Tab wraps to the next row and stays put at the very end", () => {
  assert.deepEqual(move({ r: 0, c: 3 }, "Tab", W), { r: 1, c: 0 });
  assert.deepEqual(move({ r: 3, c: 3 }, "Tab", W), { r: 3, c: 3 });
  assert.deepEqual(move({ r: 1, c: 0 }, "ShiftTab", W), { r: 0, c: 3 });
  assert.deepEqual(move({ r: 0, c: 0 }, "ShiftTab", W), { r: 0, c: 0 });
});

test("other keys are not moves", () => {
  assert.equal(move({ r: 0, c: 0 }, "a", W), null);
});

test("box and TSV", () => {
  assert.deepEqual(box({ r: 3, c: 0 }, { r: 1, c: 2 }), { r0: 1, r1: 3, c0: 0, c1: 2 });
  assert.equal(toTsv([["a", "b\tc"], [" d\n", 1]]), "a\tb c\nd\t1");
});

test("parseTsv splits rows on line breaks and cells on tabs", () => {
  assert.deepEqual(parseTsv("a\tb\nc\td"), [["a", "b"], ["c", "d"]]);
  assert.deepEqual(parseTsv("a\tb\r\nc\td\r\n"), [["a", "b"], ["c", "d"]]);
  assert.deepEqual(parseTsv("a\tb\n"), [["a", "b"]]);
  assert.deepEqual(parseTsv("a\n\n"), [["a"], [""]]);
  assert.deepEqual(parseTsv(""), []);
});

test("parseTsv reads Excel quoted cells: \"\" is a quote, tabs and line breaks stay inside", () => {
  assert.deepEqual(parseTsv('"Ж""К"\tx'), [['Ж"К', "x"]]);
  assert.deepEqual(parseTsv('"a\nb"\tc\n'), [["a\nb", "c"]]);
  assert.deepEqual(parseTsv('"a\tb"\tc'), [["a\tb", "c"]]);
  assert.deepEqual(parseTsv('""\tx'), [["", "x"]]);
  assert.deepEqual(parseTsv('"a\r\nb"\r\nc'), [["a\r\nb"], ["c"]]);
});

test("parseTsv keeps a quote inside unquoted text as text", () => {
  assert.deepEqual(parseTsv('x"y\tz'), [['x"y', "z"]]);
});

test("applyBuffered: text keys append, Backspace removes the last character", () => {
  assert.equal(applyBuffered("Аб", ["в", "г"]), "Абвг");
  assert.equal(applyBuffered("abc", ["Backspace", "Backspace"]), "a");
  assert.equal(applyBuffered("", ["Backspace"]), "");
});

test("applyBuffered: Ctrl+A then typing replaces the text; Ctrl+A then Backspace clears it", () => {
  assert.equal(applyBuffered("old", ["Ctrl+A", "n", "e", "w"]), "new");
  assert.equal(applyBuffered("old", ["Ctrl+A", "Backspace"]), "");
  assert.equal(applyBuffered("old", ["Ctrl+A"]), "old");
  assert.equal(applyBuffered("old", ["x", "Ctrl+A", "y"]), "y");
});

test("splitBuffered: the text keys before the first Enter, Tab or Escape, and that key", () => {
  assert.deepEqual(splitBuffered(["a", "b", "Enter", "c"]), { text: ["a", "b"], action: "Enter" });
  assert.deepEqual(splitBuffered(["a", "ShiftTab"]), { text: ["a"], action: "ShiftTab" });
  assert.deepEqual(splitBuffered(["Escape"]), { text: [], action: "Escape" });
  assert.deepEqual(splitBuffered(["a"]), { text: ["a"], action: null });
  assert.deepEqual(splitBuffered([]), { text: [], action: null });
});

test("planPaste lays rows from the origin, right and down", () => {
  const W3 = [4, 4, 4];
  assert.deepEqual(planPaste({ r: 1, c: 1 }, [["a", "b"], ["c", "d"]], W3, null), [
    { r: 1, c: 1, text: "a" },
    { r: 1, c: 2, text: "b" },
    { r: 2, c: 1, text: "c" },
    { r: 2, c: 2, text: "d" },
  ]);
});

test("planPaste clips rows past widths.length and cells past a row's width", () => {
  assert.deepEqual(planPaste({ r: 1, c: 0 }, [["a"], ["b"], ["c"]], [4, 4], null), [{ r: 1, c: 0, text: "a" }]);
  assert.deepEqual(planPaste({ r: 0, c: 1 }, [["a", "b", "c"]], [2, 2], null), [{ r: 0, c: 1, text: "a" }]);
  // a group-title row has one cell: a second column of the paste is dropped there
  assert.deepEqual(planPaste({ r: 1, c: 0 }, [["a", "b"]], [4, 1], null), [{ r: 1, c: 0, text: "a" }]);
});

test("planPaste of one value onto a range fills the whole range", () => {
  const out = planPaste({ r: 0, c: 0 }, [["x"]], [3, 3], { r0: 0, r1: 1, c0: 0, c1: 2 });
  assert.deepEqual(out, [
    { r: 0, c: 0, text: "x" }, { r: 0, c: 1, text: "x" }, { r: 0, c: 2, text: "x" },
    { r: 1, c: 0, text: "x" }, { r: 1, c: 1, text: "x" }, { r: 1, c: 2, text: "x" },
  ]);
});

test("planPaste of one value without a range writes one cell", () => {
  assert.deepEqual(planPaste({ r: 2, c: 1 }, [["x"]], [3, 3, 3], null), [{ r: 2, c: 1, text: "x" }]);
});

test("planPaste of a block onto a range lays it from the origin, not repeated", () => {
  const out = planPaste({ r: 0, c: 0 }, [["a", "b"]], [2, 2], { r0: 0, r1: 1, c0: 0, c1: 1 });
  assert.deepEqual(out, [{ r: 0, c: 0, text: "a" }, { r: 0, c: 1, text: "b" }]);
});

test("planPaste of parsed text with a trailing line break adds no row", () => {
  assert.deepEqual(planPaste({ r: 0, c: 0 }, parseTsv("a\n"), [2, 2], null), [{ r: 0, c: 0, text: "a" }]);
});

test("planFill copies the top row of each column down the range", () => {
  const out = planFill({ r0: 0, r1: 2, c0: 0, c1: 1 }, (r, c) => `${r}${c}`);
  assert.deepEqual(out, [
    { r: 1, c: 0, text: "00" }, { r: 2, c: 0, text: "00" },
    { r: 1, c: 1, text: "01" }, { r: 2, c: 1, text: "01" },
  ]);
});

test("planFill of a single row changes nothing", () => {
  assert.deepEqual(planFill({ r0: 4, r1: 4, c0: 0, c1: 2 }, () => "v"), []);
});

test("planSet gives every cell of the range the text", () => {
  assert.deepEqual(planSet({ r0: 1, r1: 2, c0: 0, c1: 1 }, "v"), [
    { r: 1, c: 0, text: "v" }, { r: 1, c: 1, text: "v" },
    { r: 2, c: 0, text: "v" }, { r: 2, c: 1, text: "v" },
  ]);
});

test("isPrintable: one character, no Ctrl, Meta or Alt", () => {
  assert.equal(isPrintable({ key: "a" }), true);
  assert.equal(isPrintable({ key: "A", shiftKey: true }), true);
  assert.equal(isPrintable({ key: "ө" }), true);
  assert.equal(isPrintable({ key: "a", ctrlKey: true }), false);
  assert.equal(isPrintable({ key: "c", metaKey: true }), false);
  assert.equal(isPrintable({ key: "a", altKey: true }), false);
});

test("isPrintable: names of keys are not printable", () => {
  assert.equal(isPrintable({ key: "Enter" }), false);
  assert.equal(isPrintable({ key: "F2" }), false);
  assert.equal(isPrintable({ key: "ArrowDown" }), false);
  assert.equal(isPrintable({ key: "Dead" }), false);
});

test("sessionLost: a fetch that ended on the login page", () => {
  assert.equal(sessionLost({ redirected: true, url: "http://x/login/?next=/a" }), true);
  assert.equal(sessionLost({ redirected: false, url: "http://x/reports/cell/" }), false);
  assert.equal(sessionLost({ redirected: true, url: "http://x/reports/x/" }), false);
});

test("columnKinds: a column with an editable cell is edit, with a correction cell is correct, else empty", () => {
  const E = { edit: true, correct: false };
  const C = { edit: true, correct: true };
  const N = { edit: false, correct: false };
  assert.deepEqual(columnKinds([[N, E, N], [N, E, N]]), ["", "edit", ""]);
  assert.deepEqual(columnKinds([[C, N], [N, N]]), ["correct", ""]);
  // one correction cell makes the whole column a correction column
  assert.deepEqual(columnKinds([[E, E], [C, N]]), ["correct", "edit"]);
});

test("columnKinds: ragged rows give one kind per column of the widest row", () => {
  const E = { edit: true, correct: false };
  const N = { edit: false, correct: false };
  assert.deepEqual(columnKinds([[N], [N, N, E]]), ["", "", "edit"]);
  assert.deepEqual(columnKinds([]), []);
  assert.deepEqual(columnKinds([[]]), []);
});
