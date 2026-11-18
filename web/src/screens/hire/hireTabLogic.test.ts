import { describe, expect, it } from "vitest";
import { firstErrorTab, requiredNames, tabBadge, tabOfField, tabNames, type FieldLike, type TabLike } from "./hireTabLogic";

const tabs: TabLike[] = [
  { key: "basic", sections: [{ names: ["family_name", "start"] }, { names: ["position"] }] },
  { key: "personal", sections: [{ names: ["birth_city"] }] },
  { key: "login", sections: [{ names: ["username"] }] },
];

const fields: FieldLike[] = [
  { name: "family_name", kind: "text", required: true },
  { name: "start", kind: "date", required: true },
  { name: "position", kind: "select", required: false },
  { name: "birth_city", kind: "text", required: false },
  { name: "is_active", kind: "checkbox", required: true },
  { name: "photo", kind: "file", required: true },
  { name: "username", kind: "text", required: false },
];

describe("tabNames and tabOfField", () => {
  it("flattens the section names of a tab in layout order", () => {
    expect(tabNames(tabs[0])).toEqual(["family_name", "start", "position"]);
  });

  it("finds the tab of a field name", () => {
    expect(tabOfField(tabs, "birth_city")).toBe("personal");
    expect(tabOfField(tabs, "position")).toBe("basic");
  });

  it("returns null for an unknown name", () => {
    expect(tabOfField(tabs, "no_such_field")).toBeNull();
  });
});

describe("requiredNames", () => {
  it("keeps required text and date fields and never a checkbox or the photo", () => {
    expect(requiredNames(fields, ["family_name", "start", "is_active", "photo"])).toEqual(["family_name", "start"]);
  });

  it("gives an empty list for a tab with no required fields", () => {
    expect(requiredNames(fields, ["position", "birth_city"])).toEqual([]);
  });
});

describe("tabBadge", () => {
  it("gives a blank badge when the tab has no required fields", () => {
    expect(tabBadge({ required: [], names: ["position"] }, { position: "x" }, {})).toEqual({ text: "", tone: "none" });
  });

  it("gives a blank badge when a required field is empty", () => {
    expect(
      tabBadge({ required: ["family_name", "start"], names: ["family_name", "start"] }, { family_name: "Бат", start: "  " }, {}),
    ).toEqual({ text: "", tone: "none" });
  });

  it("gives the done tick when every required field is filled", () => {
    expect(
      tabBadge({ required: ["family_name", "start"], names: ["family_name", "start"] }, { family_name: "Бат", start: "2026-01-02" }, {}),
    ).toEqual({ text: "✓", tone: "done" });
  });

  it("counts error messages, not fields, and shows the error tone even when everything is filled", () => {
    const section = { required: ["family_name"], names: ["family_name", "start"] };
    const values = { family_name: "Бат", start: "2026-01-02" };
    const errors = { family_name: ["Алдаа нэг."], start: ["Алдаа хоёр.", "Алдаа гурав."] };
    expect(tabBadge(section, values, errors)).toEqual({ text: "3", tone: "error" });
    expect(tabBadge({ required: [], names: ["family_name", "start"] }, values, { family_name: ["a"], start: ["b"] })).toEqual({
      text: "2",
      tone: "error",
    });
  });

  it("ignores errors of names outside the tab", () => {
    expect(tabBadge({ required: [], names: ["position"] }, {}, { family_name: ["x"] })).toEqual({ text: "", tone: "none" });
  });
});

describe("firstErrorTab", () => {
  it("returns the first tab in tab order that holds an error", () => {
    expect(firstErrorTab(tabs, { username: ["x"], birth_city: ["y"] })).toBe("personal");
    expect(firstErrorTab(tabs, { start: ["x"], username: ["y"] })).toBe("basic");
  });

  it("returns null when there are no errors", () => {
    expect(firstErrorTab(tabs, {})).toBeNull();
  });

  it("returns null when an error names no tab", () => {
    expect(firstErrorTab(tabs, { no_such_field: ["x"] })).toBeNull();
  });
});
