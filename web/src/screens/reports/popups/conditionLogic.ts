import type { components } from "../../../api/schema";

// The rules and format pop-ups share one condition row. This module is the client copy of the checks in the Django
// pop-up scripts (_rules_modal.html and _format_modal.html); the limits and regexes mirror reports/rules.py and
// reports/marks.py. The server reads the same text and is the only parser of the address, so these checks only stop a
// bad value early.

export type ColumnKind = components["schemas"]["ReportColumnKindOut"];
export type OpOut = components["schemas"]["ReportOpOut"];

// A condition: a column key, an operator code and the value as text («a..b» for «между»).
export type Condition = { c: string; o: string; v: string };

// The limits the Django pop-ups enforce: rule depth 3 (the root is depth 1), 20 rules, a value 100 characters, the
// text 2000 characters, 5 colour rules.
export const MAX_DEPTH = 3;
export const MAX_RULES = 20;
export const MAX_VALUE = 100;
export const MAX_TEXT = 2000;
export const MAX_MARKS = 5;

// The same number text reports/rules.py reads (an exponent allowed), the same day count and the same date text.
export const NUMBER_TEXT = /^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]{1,3})?$/;
export const DAY_COUNT = /^[0-9]{1,6}$/;
export const DATE_TEXT = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;

// The column with this key, or null.
export function columnOf(columns: ColumnKind[], key: string): ColumnKind | null {
  return columns.find((column) => column.key === key) ?? null;
}

// The kind of the column, «text» when the column is unknown (as the script does).
export function kindOf(columns: ColumnKind[], key: string): string {
  return columnOf(columns, key)?.kind ?? "text";
}

// The operators of a kind, falling back to the text operators (as the script does).
export function opsFor(ops: Record<string, OpOut[]>, kind: string): OpOut[] {
  return ops[kind] ?? ops.text ?? [];
}

// The first operator code of a kind, or "" when the kind has none.
export function firstOpFor(ops: Record<string, OpOut[]>, kind: string): string {
  const list = opsFor(ops, kind);
  return list.length ? list[0].code : "";
}

// The operators that take a number of days («ирэх … хоногт», «өнгөрсөн … хоногт»).
export function isDays(op: string): boolean {
  return op === "next_days" || op === "last_days";
}

// Option text: the operator's label without its «…» placeholder («ирэх … хоногт» reads «ирэх»).
export function opText(label: string): string {
  return label.replace(/\s*….*$/, "");
}

// The input type of a value box for a kind.
export function inputKind(kind: string): "date" | "number" | "text" {
  return kind === "date" ? "date" : kind === "number" ? "number" : "text";
}

// A single value the kind can read, or "" (the box then shows empty too, so the box and the stored value agree).
export function goodPart(kind: string, text: string): string {
  if (text === "") return "";
  if (kind === "number") return NUMBER_TEXT.test(text) ? text : "";
  if (kind === "date") return DATE_TEXT.test(text) ? text : "";
  return text;
}

// The value the operator and kind can keep: nothing for «хоосон» and «хоосон биш», two cleaned sides for «между», a
// day count for the days operators, a single cleaned value otherwise.
export function cleanValue(kind: string, op: string, value: string): string {
  if (op === "empty" || op === "filled") return "";
  if (op === "between") {
    const parts = value.split("..");
    if (parts.length !== 2) return "";
    return goodPart(kind, parts[0]) + ".." + goodPart(kind, parts[1]);
  }
  if (isDays(op)) return DAY_COUNT.test(value) ? value : "";
  return goodPart(kind, value);
}

// A condition is ready when it has a value (or needs none). A «между» condition needs at least one side.
export function ruleReady(condition: { o: string; v: string }): boolean {
  if (condition.o === "empty" || condition.o === "filled") return true;
  if (condition.o === "between") {
    const parts = condition.v.split("..");
    return (parts[0] ?? "").trim() !== "" || (parts[1] ?? "").trim() !== "";
  }
  return condition.v.trim() !== "";
}

// A loaded condition whose column or operator does not fit is made valid: an unknown column becomes the first column,
// an unknown operator becomes the kind's first operator with an empty value. Otherwise the value is cleaned for the
// operator. Returns a new condition; the input is not changed.
export function sanitizeCondition(cond: Condition, columns: ColumnKind[], ops: Record<string, OpOut[]>): Condition {
  const c = columnOf(columns, cond.c) ? cond.c : (columns[0]?.key ?? "");
  const kind = kindOf(columns, c);
  const known = opsFor(ops, kind).some((op) => op.code === cond.o);
  if (!known) return { c, o: firstOpFor(ops, kind), v: "" };
  return { c, o: cond.o, v: cleanValue(kind, cond.o, cond.v) };
}
