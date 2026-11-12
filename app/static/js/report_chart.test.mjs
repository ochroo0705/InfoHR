// Unit tests for report_chart.js: the click target of a chart point. Run: node --test <this file>.
// The script is a classic browser script, so it is loaded through require; under Node it exports clickTarget only.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { clickTarget, layout } = require("./report_chart.js");

const theme = { text: "#000", grid: "#ccc", accent: "#c00", series: ["#111"], surface: "#fff" };

test("the category axis is categorical, so labels like 2024-07 are not read as dates", () => {
  assert.equal(layout({ kind: "line", labels: ["2024-07"], values: [1] }, theme).xaxis.type, "category");
  assert.equal(layout({ kind: "bar", labels: ["2024-07"], values: [1] }, theme).xaxis.type, "category");
  const horizontal = { kind: "bar", labels: Array.from({ length: 8 }, (_, i) => "2024-0" + (i + 1)), values: [1] };
  assert.equal(layout(horizontal, theme).yaxis.type, "category");
  assert.equal(layout(horizontal, theme).yaxis.autorange, "reversed");
});

test("a percent chart's ticks keep their decimals, so small fractions do not repeat", () => {
  const fractions = { kind: "line", labels: ["A", "B"], values: [0.2, 0.4], percent: true };
  assert.equal(layout(fractions, theme).yaxis.tickformat, ",.1~f");
  assert.equal(layout({ kind: "line", labels: ["A"], values: [3], money: true }, theme).yaxis.tickformat, ",.0f");
  assert.equal(layout({ kind: "line", labels: ["A"], values: [3] }, theme).yaxis.tickformat, "d");
});

const data = { labels: ["A", "B", "—"], hrefs: ["/reports/x/?rules=a", "", "/reports/x/?rules=c"] };

test("a point with a link gives its address", () => {
  assert.equal(clickTarget(data, 0), "/reports/x/?rules=a");
  assert.equal(clickTarget(data, 2), "/reports/x/?rules=c");
});

test("a point without a link gives the empty text", () => {
  assert.equal(clickTarget(data, 1), "");
});

test("an index out of range, negative or not an integer gives the empty text", () => {
  assert.equal(clickTarget(data, 3), "");
  assert.equal(clickTarget(data, -1), "");
  assert.equal(clickTarget(data, 0.5), "");
  assert.equal(clickTarget(data, "0"), "");
  assert.equal(clickTarget(data, NaN), "");
});

test("data without hrefs gives the empty text", () => {
  assert.equal(clickTarget({ labels: ["A"] }, 0), "");
  assert.equal(clickTarget({ labels: ["A"], hrefs: "/x" }, 0), "");
  assert.equal(clickTarget(null, 0), "");
});

test("a non-string entry gives the empty text", () => {
  assert.equal(clickTarget({ hrefs: [42] }, 0), "");
});
