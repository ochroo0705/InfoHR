import { describe, expect, it } from "vitest";
import {
  PICKED_CLASS,
  clearPicks,
  copyNote,
  createState,
  endMode,
  headerMark,
  isOn,
  isPersonId,
  isPicked,
  resetIfNewPage,
  selectAll,
  selectionBody,
  setRow,
  setVisible,
  toggleMode,
} from "./selectionState";

// Port of app/static/js/report_select.test.mjs, one case per test, plus the cases for the immutable state and the body.

describe("selectionState", () => {
  it("a picked row gets the is-picked class (the lime look is in input.css)", () => {
    expect(PICKED_CLASS).toBe("is-picked");
  });

  it("the header box follows the rows on screen: empty, partly picked, all picked, all matching", () => {
    let s = createState();
    expect(headerMark(s, ["1", "2"])).toEqual({ checked: false, indeterminate: false });
    s = setRow(s, "1", true, ["1", "2"]);
    expect(headerMark(s, ["1", "2"])).toEqual({ checked: false, indeterminate: true });
    s = setRow(s, "2", true, ["1", "2"]);
    expect(headerMark(s, ["1", "2"])).toEqual({ checked: true, indeterminate: false });
    expect(headerMark(createState(), [])).toEqual({ checked: false, indeterminate: false });
    const all = selectAll(createState());
    expect(headerMark(all, ["1", "2"])).toEqual({ checked: true, indeterminate: false });
  });

  it("the toggle turns the mode on with nothing picked", () => {
    const s = toggleMode(createState());
    expect(isOn(s)).toBe(true);
    expect(s.ids.size).toBe(0);
    expect(s.all).toBe(false);
  });

  it("the toggle turns the mode off again and clears what was picked", () => {
    let s = toggleMode(createState());
    s = setRow(s, "4", true, ["4", "5"]);
    s = toggleMode(s);
    expect(isOn(s)).toBe(false);
    expect(s.ids.size).toBe(0);
  });

  it("a mode started by a tick ends when the last row is unticked", () => {
    let s = setRow(createState(), "4", true, ["4"]);
    s = setRow(s, "4", false, ["4"]);
    expect(isOn(s)).toBe(false);
  });

  it("a mode started by the toggle survives the last untick", () => {
    let s = toggleMode(createState());
    s = setRow(s, "4", true, ["4"]);
    s = setRow(s, "4", false, ["4"]);
    expect(isOn(s)).toBe(true);
    expect(s.ids.size).toBe(0);
  });

  it("a toggle-started mode also survives a header untick", () => {
    let s = toggleMode(createState());
    s = setVisible(s, true, ["1", "2"]);
    s = setVisible(s, false, ["1", "2"]);
    expect(isOn(s)).toBe(true);
  });

  it("a new report page ends a toggle-started mode too", () => {
    const first = { id: "report-page" };
    const s = toggleMode(createState());
    const r = resetIfNewPage(s, { id: "report-page" }, first);
    expect(r.changed).toBe(true);
    expect(isOn(r.state)).toBe(false);
    expect(r.state.held).toBe(false);
  });

  it("endMode clears the picks and the toggle", () => {
    let s = toggleMode(createState());
    s = setRow(s, "9", true, ["9"]);
    s = endMode(s);
    expect(isOn(s)).toBe(false);
    expect(s.ids.size).toBe(0);
  });

  it("a person id is ASCII digits, at most 12 of them", () => {
    expect(isPersonId("7")).toBe(true);
    expect(isPersonId("123456789012")).toBe(true);
    expect(isPersonId(42)).toBe(true);
    for (const bad of ["", "abc", "1.5", " 3", "3 ", "-1", "1234567890123", "٣", "1e3", "[object Object]"]) {
      expect(isPersonId(bad), JSON.stringify(bad)).toBe(false);
    }
  });

  it("a row toggle ignores an id that is not a person id", () => {
    let s = createState();
    s = setRow(s, "x'; drop", true, ["1"]);
    s = setRow(s, "1.5", true, ["1"]);
    expect(s.ids.size).toBe(0);
    expect(isOn(s)).toBe(false);
  });

  it("the header box skips ids that are not person ids", () => {
    const s = setVisible(createState(), true, ["1", "bad", "2"]);
    expect([...s.ids]).toEqual(["1", "2"]);
  });

  it("ticking a row adds it, and unticking the last one turns the mode off", () => {
    let s = setRow(createState(), "3", true, ["3", "4"]);
    expect(isOn(s)).toBe(true);
    expect(isPicked(s, "3")).toBe(true);
    expect(isPicked(s, "4")).toBe(false);
    s = setRow(s, "3", false, ["3", "4"]);
    expect(isOn(s)).toBe(false);
  });

  it("the header box picks every row on screen and clears them again", () => {
    let s = setVisible(createState(), true, ["1", "2"]);
    expect([...s.ids].sort()).toEqual(["1", "2"]);
    s = setVisible(s, false, ["1", "2"]);
    expect(isOn(s)).toBe(false);
  });

  it("all matching picks everyone, sends no ids, and every row shows picked", () => {
    let s = setRow(createState(), "1", true, ["1", "2"]);
    s = selectAll(s);
    expect(s.all).toBe(true);
    expect(s.ids.size).toBe(0);
    expect(isPicked(s, "999")).toBe(true);
    expect(isOn(s)).toBe(true);
  });

  it("ticking a row while all matching is on changes nothing", () => {
    let s = selectAll(createState());
    s = setRow(s, "5", true, ["5"]);
    expect(s.all).toBe(true);
    expect(s.ids.size).toBe(0);
  });

  it("unticking a row while all matching is on ends it and keeps the rows on screen minus that one", () => {
    let s = selectAll(createState());
    s = setRow(s, "2", false, ["1", "2", "3"]);
    expect(s.all).toBe(false);
    expect([...s.ids].sort()).toEqual(["1", "3"]);
    expect(isPicked(s, "2")).toBe(false);
  });

  it("unticking the only visible row while all matching is on leaves the mode off when nothing else is picked", () => {
    let s = selectAll(createState());
    s = setRow(s, "2", false, ["2"]);
    expect(isOn(s)).toBe(false);
  });

  it("clearing ends all matching and every pick", () => {
    const s = clearPicks(selectAll(createState()));
    expect(isOn(s)).toBe(false);
    expect(s.all).toBe(false);
  });

  it("a new report page clears the selection, the same page keeps it", () => {
    const first = { id: "report-page" };
    const a = resetIfNewPage(createState(), first, null);
    expect(a.changed).toBe(true);
    const picked = setRow(a.state, "8", true, ["8"]);
    const same = resetIfNewPage(picked, first, first);
    expect(same.changed).toBe(false);
    expect(isOn(same.state)).toBe(true);
    const next = resetIfNewPage(same.state, { id: "report-page" }, first);
    expect(next.changed).toBe(true);
    expect(isOn(next.state)).toBe(false);
  });

  it("copy note gives the count, and the dropped rows only when there are some", () => {
    expect(copyNote({ count: 3, dropped: 0 })).toBe("Хууллаа: 3");
    expect(copyNote({ count: 3, dropped: 2 })).toBe("Хууллаа: 3 · 2 хасагдсан");
  });

  it("every change returns a new state and leaves the input as it was", () => {
    const before = setRow(createState(), "1", true, ["1", "2"]);
    const ids = before.ids;
    const after = setRow(before, "2", true, ["1", "2"]);
    expect(after).not.toBe(before);
    expect(before.ids).toBe(ids);
    expect([...before.ids]).toEqual(["1"]);
    expect([...after.ids]).toEqual(["1", "2"]);
    const all = selectAll(before);
    expect(before.all).toBe(false);
    expect(all.all).toBe(true);
  });

  it("toggleMode, setVisible, clearPicks, endMode and resetIfNewPage return a new object and never mutate the input", () => {
    const page = { id: "report-page" };
    const start = setRow(toggleMode(createState()), "1", true, ["1", "2"]);
    const snapshot = { ids: [...start.ids], all: start.all, held: start.held };
    const same = (s: typeof start) => {
      expect([...s.ids]).toEqual(snapshot.ids);
      expect(s.all).toBe(snapshot.all);
      expect(s.held).toBe(snapshot.held);
    };

    const toggled = toggleMode(start);
    expect(toggled).not.toBe(start);
    same(start);

    const shown = setVisible(start, true, ["2"]);
    expect(shown).not.toBe(start);
    same(start);

    const cleared = clearPicks(start);
    expect(cleared).not.toBe(start);
    same(start);

    const ended = endMode(start);
    expect(ended).not.toBe(start);
    same(start);

    const first = resetIfNewPage(start, page, null);
    expect(first.changed).toBe(true);
    expect(first.state).not.toBe(start);
    same(start);
  });

  it("the body of an all-matching selection sends all and no ids", () => {
    const s = selectAll(setRow(createState(), "3", true, ["3"]));
    expect(selectionBody("state=all", s)).toEqual({ query: "state=all", ids: [], all: true });
  });

  it("the body of a picked selection lists the ids in the order they were picked, person ids only", () => {
    let s = setRow(createState(), "7", true, ["3", "7"]);
    s = setRow(s, "3", true, ["3", "7"]);
    s = setVisible(s, true, ["bad", "9"]);
    expect(selectionBody("q=1", s)).toEqual({ query: "q=1", ids: ["7", "3", "9"], all: false });
  });

  it("the body of an empty selection has no ids", () => {
    expect(selectionBody("q=1", createState())).toEqual({ query: "q=1", ids: [], all: false });
  });
});
