import { describe, expect, it } from "vitest";
import { changedNames, pruneEdits, storedValueOf, type PersonalFieldOut } from "./sectionEdit";

function field(overrides: Partial<PersonalFieldOut>): PersonalFieldOut {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    kind: "text",
    label: "",
    name: "",
    placeholder: "",
    required: false,
    value: "",
    ...overrides,
  };
}

const fields: PersonalFieldOut[] = [
  field({ name: "register_no", value: "УБ99112233" }),
  field({ name: "gender", kind: "select", value: "F" }),
  field({ name: "retired", kind: "checkbox", checked: true, value: "" }),
];

describe("storedValueOf", () => {
  it("a text or select field holds its value", () => {
    expect(storedValueOf(fields[0])).toBe("УБ99112233");
    expect(storedValueOf(fields[1])).toBe("F");
  });

  it("a checkbox holds \"on\" when ticked and \"\" when not, as the browser posts it", () => {
    expect(storedValueOf(fields[2])).toBe("on");
    expect(storedValueOf(field({ kind: "checkbox", checked: false, value: "on" }))).toBe("");
  });
});

describe("changedNames", () => {
  it("keeps only the edits that differ from the stored values", () => {
    expect(changedNames({ register_no: "УБ1", gender: "F" }, fields)).toEqual({ register_no: "УБ1" });
  });

  it("returns nothing when no edit differs", () => {
    expect(changedNames({}, fields)).toEqual({});
    expect(changedNames({ register_no: "УБ99112233" }, fields)).toEqual({});
  });

  it("compares a checkbox edit with its stored \"on\" or \"\"", () => {
    expect(changedNames({ retired: "" }, fields)).toEqual({ retired: "" });
    expect(changedNames({ retired: "on" }, fields)).toEqual({});
  });
});

describe("pruneEdits", () => {
  it("drops an edit that now equals the stored value", () => {
    const edits = { register_no: "УБ2", gender: "M" };
    const refreshed = [field({ name: "register_no", value: "УБ2" }), field({ name: "gender", kind: "select", value: "F" })];
    expect(pruneEdits(edits, refreshed)).toEqual({ gender: "M" });
  });

  it("keeps an edit whose stored value is still different (a refetch does not drop the user's typing)", () => {
    const edits = { register_no: "УБ2" };
    expect(pruneEdits(edits, fields)).toEqual({ register_no: "УБ2" });
  });

  it("returns the same object when nothing is dropped", () => {
    const edits = { register_no: "УБ2" };
    expect(pruneEdits(edits, fields)).toBe(edits);
  });
});
