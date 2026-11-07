// Unit tests for report_select.js: the pure helpers and the selection state machine. Run: node --test <this file>.
// The script is a classic browser script, so it is loaded through require; under Node it exports these helpers only.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const {
  isPersonId,
  createState,
  isOn,
  isPicked,
  setRow,
  setVisible,
  selectAll,
  clearPicks,
  toggleMode,
  endMode,
  headerMark,
  resetIfNewPage,
  selectionPairs,
  pairsToValues,
  filenameFrom,
  copyNote,
} = require("./report_select.js");

test("the header box follows the rows on screen: empty, partly picked, all picked, all matching", () => {
  const s = createState();
  assert.deepEqual(headerMark(s, ["1", "2"]), { checked: false, indeterminate: false });
  setRow(s, "1", true, ["1", "2"]);
  assert.deepEqual(headerMark(s, ["1", "2"]), { checked: false, indeterminate: true });
  setRow(s, "2", true, ["1", "2"]);
  assert.deepEqual(headerMark(s, ["1", "2"]), { checked: true, indeterminate: false });
  assert.deepEqual(headerMark(createState(), []), { checked: false, indeterminate: false });
  const all = createState();
  selectAll(all);
  assert.deepEqual(headerMark(all, ["1", "2"]), { checked: true, indeterminate: false });
});

test("the toggle turns the mode on with nothing picked", () => {
  const s = createState();
  toggleMode(s);
  assert.equal(isOn(s), true);
  assert.equal(s.ids.size, 0);
  assert.equal(s.all, false);
});

test("the toggle turns the mode off again and clears what was picked", () => {
  const s = createState();
  toggleMode(s);
  setRow(s, "4", true, ["4", "5"]);
  toggleMode(s);
  assert.equal(isOn(s), false);
  assert.equal(s.ids.size, 0);
});

test("a mode started by a tick ends when the last row is unticked", () => {
  const s = createState();
  setRow(s, "4", true, ["4"]);
  setRow(s, "4", false, ["4"]);
  assert.equal(isOn(s), false);
});

test("a mode started by the toggle survives the last untick", () => {
  const s = createState();
  toggleMode(s);
  setRow(s, "4", true, ["4"]);
  setRow(s, "4", false, ["4"]);
  assert.equal(isOn(s), true);
  assert.equal(s.ids.size, 0);
});

test("a toggle-started mode also survives a header untick", () => {
  const s = createState();
  toggleMode(s);
  setVisible(s, true, ["1", "2"]);
  setVisible(s, false, ["1", "2"]);
  assert.equal(isOn(s), true);
});

test("a new #report-page ends a toggle-started mode too", () => {
  const s = createState();
  toggleMode(s);
  resetIfNewPage(s, { id: "report-page" });
  assert.equal(isOn(s), false);
  assert.equal(s.held, false);
});

test("endMode clears the picks and the toggle", () => {
  const s = createState();
  toggleMode(s);
  setRow(s, "9", true, ["9"]);
  endMode(s);
  assert.equal(isOn(s), false);
  assert.equal(s.ids.size, 0);
});

test("a person id is ASCII digits, at most 12 of them", () => {
  assert.equal(isPersonId("7"), true);
  assert.equal(isPersonId("123456789012"), true);
  assert.equal(isPersonId(42), true);
  for (const bad of ["", "abc", "1.5", " 3", "3 ", "-1", "1234567890123", "٣", "1e3", "[object Object]"]) {
    assert.equal(isPersonId(bad), false, JSON.stringify(bad));
  }
});

test("a row toggle ignores an id that is not a person id", () => {
  const s = createState();
  setRow(s, "x'; drop", true, ["1"]);
  setRow(s, "1.5", true, ["1"]);
  assert.equal(s.ids.size, 0);
  assert.equal(isOn(s), false);
});

test("the header box skips ids that are not person ids", () => {
  const s = createState();
  setVisible(s, true, ["1", "bad", "2"]);
  assert.deepEqual([...s.ids], ["1", "2"]);
});

test("ticking a row adds it, and unticking the last one turns the mode off", () => {
  const s = createState();
  setRow(s, "3", true, ["3", "4"]);
  assert.equal(isOn(s), true);
  assert.equal(isPicked(s, "3"), true);
  assert.equal(isPicked(s, "4"), false);
  setRow(s, "3", false, ["3", "4"]);
  assert.equal(isOn(s), false);
});

test("the header box picks every row on screen and clears them again", () => {
  const s = createState();
  setVisible(s, true, ["1", "2"]);
  assert.deepEqual([...s.ids].sort(), ["1", "2"]);
  setVisible(s, false, ["1", "2"]);
  assert.equal(isOn(s), false);
});

test("all matching picks everyone, sends no ids, and every row shows picked", () => {
  const s = createState();
  setRow(s, "1", true, ["1", "2"]);
  selectAll(s);
  assert.equal(s.all, true);
  assert.equal(s.ids.size, 0);
  assert.equal(isPicked(s, "999"), true);
  assert.equal(isOn(s), true);
});

test("ticking a row while all matching is on changes nothing", () => {
  const s = createState();
  selectAll(s);
  setRow(s, "5", true, ["5"]);
  assert.equal(s.all, true);
  assert.equal(s.ids.size, 0);
});

test("unticking a row while all matching is on ends it and keeps the rows on screen minus that one", () => {
  const s = createState();
  selectAll(s);
  setRow(s, "2", false, ["1", "2", "3"]);
  assert.equal(s.all, false);
  assert.deepEqual([...s.ids].sort(), ["1", "3"]);
  assert.equal(isPicked(s, "2"), false);
});

test("unticking the only visible row while all matching is on leaves the mode off when nothing else is picked", () => {
  const s = createState();
  selectAll(s);
  setRow(s, "2", false, ["2"]);
  assert.equal(isOn(s), false);
});

test("clearing ends all matching and every pick", () => {
  const s = createState();
  selectAll(s);
  clearPicks(s);
  assert.equal(isOn(s), false);
  assert.equal(s.all, false);
});

test("a new #report-page clears the selection, the same element keeps it", () => {
  const s = createState();
  const first = { id: "report-page" };
  assert.equal(resetIfNewPage(s, first), true);
  setRow(s, "8", true, ["8"]);
  assert.equal(resetIfNewPage(s, first), false);
  assert.equal(isOn(s), true);
  assert.equal(resetIfNewPage(s, { id: "report-page" }), true);
  assert.equal(isOn(s), false);
});

test("the fields hold the report address, then one ids field per picked person", () => {
  assert.deepEqual(selectionPairs("state=all", ["3", "7"], false), [
    ["query", "state=all"],
    ["ids", "3"],
    ["ids", "7"],
  ]);
});

test("all-matching sends all=1 and no ids", () => {
  assert.deepEqual(selectionPairs("q=1", ["3"], true), [["query", "q=1"], ["all", "1"]]);
});

test("htmx values turn a repeated key into an array and keep a single key as it is", () => {
  assert.deepEqual(pairsToValues([["query", "q"], ["ids", "3"], ["ids", "7"]]), { query: "q", ids: ["3", "7"] });
  assert.deepEqual(pairsToValues([["query", "q"], ["all", "1"]]), { query: "q", all: "1" });
});

test("the file name comes from Content-Disposition, plain or RFC 5987", () => {
  assert.equal(
    filenameFrom('attachment; filename="staff-list-selected-2026-11-07.xlsx"', "report.xlsx"),
    "staff-list-selected-2026-11-07.xlsx",
  );
  assert.equal(
    filenameFrom("attachment; filename*=UTF-8''%D0%A2%D0%B5%D1%81%D1%82.csv", "report.csv"),
    "Тест.csv",
  );
});

test("a missing or unreadable Content-Disposition falls back to the given name", () => {
  assert.equal(filenameFrom(null, "report.csv"), "report.csv");
  assert.equal(filenameFrom("attachment", "report.xlsx"), "report.xlsx");
  assert.equal(filenameFrom("attachment; filename*=UTF-8''%E0%A4%A", "report.csv"), "report.csv");
});

test("the copy note gives the count, and the dropped rows only when there are some", () => {
  assert.equal(copyNote({ count: 3, dropped: 0 }), "Хууллаа: 3");
  assert.equal(copyNote({ count: 3, dropped: 2 }), "Хууллаа: 3 · 2 хасагдсан");
});
