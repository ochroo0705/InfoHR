import type { components } from "../../../api/schema";
import {
  MAX_MARKS,
  MAX_VALUE,
  firstOpFor,
  kindOf,
  ruleReady,
  sanitizeCondition,
  type ColumnKind,
  type Condition,
  type OpOut,
} from "./conditionLogic";

// The colour rules of the «Хэлбэр» pop-up, pure: loading the saved ones, a blank one, the JSON the address carries and the
// totals text. The Django script (_format_modal.html) does the same work inline; the limits come from conditionLogic.

export type ColourKind = components["schemas"]["ReportColourOut"];
export type MarkIn = components["schemas"]["ReportMarkOut"];

// A colour rule: a condition plus the colour key. uid names the row for focus (the rules pop-up's uid counter).
export type Mark = Condition & { k: string; uid: number };

let uidSeq = 0;

function nextUid(): number {
  uidSeq += 1;
  return uidSeq;
}

// Restarts the uid counter. Tests use it for determinism.
export function resetMarkUids(): void {
  uidSeq = 0;
}

// The saved colour rules, cleaned as the script does: at most 5, a column or operator that does not fit made valid, a
// value cleaned for its operator, and an unknown colour replaced by the first colour.
export function marksFromServer(
  list: MarkIn[],
  columns: ColumnKind[],
  ops: Record<string, OpOut[]>,
  colours: ColourKind[],
): Mark[] {
  return list.slice(0, MAX_MARKS).map((item) => {
    const cond = sanitizeCondition({ c: item.c, o: item.o, v: item.v ?? "" }, columns, ops);
    const known = colours.some((colour) => colour.key === item.k);
    return { uid: nextUid(), ...cond, k: known ? item.k : (colours[0]?.key ?? "") };
  });
}

// A new colour rule: the first column, its first operator, no value, the first colour.
export function blankMark(columns: ColumnKind[], ops: Record<string, OpOut[]>, colours: ColourKind[]): Mark {
  const c = columns[0]?.key ?? "";
  return { uid: nextUid(), c, o: firstOpFor(ops, kindOf(columns, c)), v: "", k: colours[0]?.key ?? "" };
}

// The address text of the colour rules: the ready ones only, as [{c, o, v, k}] (the value is "" for «хоосон» and
// «хоосон биш»). tooLong is set when a kept value is over 100 characters. text is "" when no rule is kept.
export function marksJson(marks: Mark[]): { text: string; tooLong: boolean } {
  const items: { c: string; o: string; v: string; k: string }[] = [];
  let tooLong = false;
  for (const mark of marks) {
    if (!ruleReady(mark)) continue;
    const value = mark.o === "empty" || mark.o === "filled" ? "" : mark.v;
    if (value.length > MAX_VALUE) tooLong = true;
    items.push({ c: mark.c, o: mark.o, v: value, k: mark.k });
  }
  return { text: items.length ? JSON.stringify(items) : "", tooLong };
}

// The totals text of the address: «key:agg» pairs joined by ",", blank aggregates dropped. The caller builds the record
// in the order the columns are drawn.
export function totalsText(pairs: Record<string, string>): string {
  return Object.entries(pairs)
    .filter(([, agg]) => agg !== "")
    .map(([key, agg]) => `${key}:${agg}`)
    .join(",");
}
