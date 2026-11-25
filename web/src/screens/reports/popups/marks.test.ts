import { beforeEach, describe, expect, it } from "vitest";
import type { components } from "../../../api/schema";
import { blankMark, marksFromServer, marksJson, resetMarkUids, totalsText, type Mark } from "./marks";

type ColourOut = components["schemas"]["ReportColourOut"];
type MarkIn = components["schemas"]["ReportMarkOut"];

const COLUMNS = [
  { key: "name", kind: "text", label: "Нэр" },
  { key: "salary", kind: "number", label: "Цалин" },
  { key: "joined", kind: "date", label: "Элссэн" },
];

const OPS = {
  text: [
    { code: "eq", label: "Тэнцүү" },
    { code: "contains", label: "Агуулсан" },
    { code: "empty", label: "Хоосон" },
    { code: "filled", label: "Хоосон биш" },
  ],
  number: [
    { code: "gt", label: "Их" },
    { code: "between", label: "Хооронд …" },
  ],
  date: [
    { code: "eq", label: "Тэнцүү" },
    { code: "next_days", label: "ирэх … хоногт" },
  ],
};

const COLOURS: ColourOut[] = [
  { key: "red", label: "Улаан", classes: "bg-red-100 text-red-800" },
  { key: "green", label: "Ногоон", classes: "bg-green-100 text-green-800" },
];

function mark(c: string, o: string, v: string, k: string): MarkIn {
  return { c, o, v, k };
}

beforeEach(() => {
  resetMarkUids();
});

describe("marks", () => {
  it("marksFromServer_caps_at_five_and_fixes_colour", () => {
    const list: MarkIn[] = [
      mark("name", "eq", "a", "green"),
      mark("name", "eq", "b", "red"),
      mark("salary", "gt", "5", "nope"), // unknown colour: the first colour
      mark("ghost", "eq", "x", "red"), // unknown column: the first column; the operator still fits, so the value stays
      mark("name", "zzz", "y", "red"), // unknown operator: the kind's first operator, value cleared
      mark("name", "eq", "z", "red"), // sixth: dropped
    ];
    const marks = marksFromServer(list, COLUMNS, OPS, COLOURS);
    expect(marks).toHaveLength(5);
    expect(marks[2]).toMatchObject({ c: "salary", o: "gt", v: "5", k: "red" });
    expect(marks[3]).toMatchObject({ c: "name", o: "eq", v: "x", k: "red" });
    expect(marks[4]).toMatchObject({ c: "name", o: "eq", v: "", k: "red" });
    expect(marks[2]?.k).toBe("red");
    expect(new Set(marks.map((m) => m.uid)).size).toBe(5);
  });

  it("marksJson_drops_unready_and_flags_long", () => {
    const marks: Mark[] = [
      { uid: 1, c: "name", o: "eq", v: "ab", k: "red" },
      { uid: 2, c: "name", o: "contains", v: "   ", k: "red" }, // not ready: dropped
      { uid: 3, c: "name", o: "empty", v: "junk", k: "green" }, // needs no value: kept, value forced ""
      { uid: 4, c: "salary", o: "between", v: "..", k: "red" }, // both sides blank: dropped
    ];
    const built = marksJson(marks);
    expect(built.tooLong).toBe(false);
    expect(JSON.parse(built.text)).toEqual([
      { c: "name", o: "eq", v: "ab", k: "red" },
      { c: "name", o: "empty", v: "", k: "green" },
    ]);

    const long: Mark[] = [{ uid: 5, c: "name", o: "eq", v: "a".repeat(101), k: "red" }];
    const flagged = marksJson(long);
    expect(flagged.tooLong).toBe(true);

    expect(marksJson([{ uid: 6, c: "name", o: "contains", v: "", k: "red" }])).toEqual({ text: "", tooLong: false });
  });

  it("totalsText_joins_pairs_and_drops_blank", () => {
    expect(totalsText({ name: "count", salary: "", joined: "sum" })).toBe("name:count,joined:sum");
    expect(totalsText({ name: "" })).toBe("");
    expect(totalsText({})).toBe("");
  });

  it("blankMark_takes_first_column_operator_and_colour", () => {
    const created = blankMark(COLUMNS, OPS, COLOURS);
    expect(created).toMatchObject({ c: "name", o: "eq", v: "", k: "red" });
    expect(created.uid).toBeGreaterThan(0);
  });
});
