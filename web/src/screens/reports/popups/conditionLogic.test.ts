import { describe, expect, it } from "vitest";
import {
  NUMBER_TEXT,
  cleanValue,
  ruleReady,
  sanitizeCondition,
  type ColumnKind,
  type OpOut,
} from "./conditionLogic";

const COLUMNS: ColumnKind[] = [
  { key: "name", kind: "text", label: "Нэр" },
  { key: "salary", kind: "number", label: "Цалин" },
  { key: "joined", kind: "date", label: "Элссэн" },
];

const OPS: Record<string, OpOut[]> = {
  text: [
    { code: "contains", label: "агуулсан" },
    { code: "empty", label: "хоосон" },
  ],
  number: [
    { code: "gte", label: "≥" },
    { code: "between", label: "хооронд" },
  ],
  date: [
    { code: "on", label: "өдөр" },
    { code: "next_days", label: "ирэх … хоногт" },
  ],
};

describe("conditionLogic", () => {
  it("NUMBER_TEXT accepts exponent and rejects junk", () => {
    expect(NUMBER_TEXT.test("12")).toBe(true);
    expect(NUMBER_TEXT.test("-3.5")).toBe(true);
    expect(NUMBER_TEXT.test("1e5")).toBe(true);
    expect(NUMBER_TEXT.test("1E-12")).toBe(true);
    expect(NUMBER_TEXT.test("12abc")).toBe(false);
    expect(NUMBER_TEXT.test("1e1234")).toBe(false);
    expect(NUMBER_TEXT.test("")).toBe(false);
  });

  it("cleanValue between keeps two parts and blanks a bad side", () => {
    expect(cleanValue("number", "between", "10..20")).toBe("10..20");
    expect(cleanValue("number", "between", "10..abc")).toBe("10..");
    expect(cleanValue("date", "between", "2026-01-01..junk")).toBe("2026-01-01..");
    expect(cleanValue("number", "between", "10")).toBe("");
  });

  it("cleanValue days only 1-6 digits", () => {
    expect(cleanValue("date", "next_days", "30")).toBe("30");
    expect(cleanValue("date", "last_days", "1234567")).toBe("");
    expect(cleanValue("date", "next_days", "-3")).toBe("");
    expect(cleanValue("date", "last_days", "3.5")).toBe("");
  });

  it("cleanValue clears the value of empty and filled", () => {
    expect(cleanValue("text", "empty", "anything")).toBe("");
    expect(cleanValue("text", "filled", "anything")).toBe("");
  });

  it("ruleReady between needs one side", () => {
    expect(ruleReady({ o: "between", v: "..5" })).toBe(true);
    expect(ruleReady({ o: "between", v: "3.." })).toBe(true);
    expect(ruleReady({ o: "between", v: ".." })).toBe(false);
    expect(ruleReady({ o: "between", v: " .. " })).toBe(false);
    expect(ruleReady({ o: "contains", v: "  " })).toBe(false);
    expect(ruleReady({ o: "empty", v: "" })).toBe(true);
  });

  it("sanitize resets unknown operator and clears the value", () => {
    expect(sanitizeCondition({ c: "salary", o: "contains", v: "5" }, COLUMNS, OPS)).toEqual({
      c: "salary",
      o: "gte",
      v: "",
    });
    expect(sanitizeCondition({ c: "salary", o: "gte", v: "12abc" }, COLUMNS, OPS)).toEqual({
      c: "salary",
      o: "gte",
      v: "",
    });
  });

  it("sanitize resets an unknown column to the first column", () => {
    expect(sanitizeCondition({ c: "gone", o: "contains", v: "x" }, COLUMNS, OPS)).toEqual({
      c: "name",
      o: "contains",
      v: "x",
    });
  });
});
