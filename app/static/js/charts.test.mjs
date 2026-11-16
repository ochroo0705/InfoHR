// Unit tests for charts.js: the ECharts option of each chart kind, and the click target of a chart point.
// Run: node --test <this file>. The script is a classic browser script, so it is loaded through require;
// under Node it exports toOption and clickTarget only.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { toOption, clickTarget, horizontalHeight } = require("./charts.js");

test("a horizontal chart is 32 px a bar plus 60 px, at least 320 px and at most 1200 px", () => {
  assert.equal(horizontalHeight(1), 320);
  assert.equal(horizontalHeight(10), 380);
  assert.equal(horizontalHeight(30), 1020);
  assert.equal(horizontalHeight(100), 1200);
});

const light = {
  accent: "#c0392b", text: "#34495e", grid: "#d5dcdf", surface: "#ffffff",
  series: ["#dc2626", "#f59e0b", "#16a34a", "#3b82f6", "#5f6b6d", "#bdc6c8", "#8a9598"],
};

test("a bar chart is a bar series on a category x axis", () => {
  const option = toOption({ kind: "bar", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.series[0].type, "bar");
  assert.deepEqual(option.xAxis.data, ["A", "B"]);
  assert.notEqual(option.animation, false);
});

test("a horizontal bar chart has a category y axis and a value x axis", () => {
  const option = toOption({ kind: "hbar", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.yAxis.type, "category");
  assert.equal(option.xAxis.type, "value");
});

test("a bar chart with many labels is drawn horizontally", () => {
  const labels = Array.from({ length: 8 }, (_, i) => "L" + (i + 1));
  const option = toOption({ kind: "bar", labels, values: labels.map((_, i) => i), series: [] }, light);
  assert.equal(option.yAxis.type, "category");
  assert.equal(option.xAxis.type, "value");
});

test("a stacked chart has one stacked series per stack and a legend", () => {
  const option = toOption({
    kind: "stacked", labels: ["A", "B"],
    series: [{ label: "x", values: [1, 2] }, { label: "y", values: [3, 4] }],
  }, light);
  assert.equal(option.series.length, 2);
  assert.equal(option.series[0].stack, "total");
  assert.equal(option.series[1].stack, "total");
  assert.equal(option.legend.show, true);
});

test("a line chart is a line series", () => {
  const option = toOption({ kind: "line", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.series[0].type, "line");
});

test("an area chart is a line series with an area fill", () => {
  const option = toOption({ kind: "area", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.series[0].type, "line");
  assert.ok(option.series[0].areaStyle);
});

test("a donut chart is a pie with a hole", () => {
  const option = toOption({ kind: "donut", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.series[0].type, "pie");
  assert.deepEqual(option.series[0].radius, ["55%", "80%"]);
  assert.deepEqual(option.series[0].data, [{ name: "A", value: 1 }, { name: "B", value: 2 }]);
});

test("a pie chart is a full pie", () => {
  const option = toOption({ kind: "pie", labels: ["A", "B"], values: [1, 2], series: [] }, light);
  assert.equal(option.series[0].type, "pie");
  assert.equal(option.series[0].radius, "75%");
});

test("a money chart formats its tooltip values with commas and the tugrik sign", () => {
  const option = toOption({ kind: "bar", labels: ["A"], values: [1234], money: true, series: [] }, light);
  assert.equal(option.tooltip.valueFormatter(1234), "1,234₮");
});

test("a percent chart formats its tooltip values with a percent sign", () => {
  const option = toOption({ kind: "bar", labels: ["A"], values: [12], percent: true, series: [] }, light);
  assert.equal(option.tooltip.valueFormatter(12), "12%");
});

test("a chart without money or percent formats its tooltip values with commas", () => {
  const option = toOption({ kind: "bar", labels: ["A"], values: [1234], series: [] }, light);
  assert.equal(option.tooltip.valueFormatter(1234), "1,234");
});

test("a value that is not a finite number shows as a dash, never as raw markup", () => {
  const bad = ["<img src=x onerror=alert(1)>", null];
  for (const kind of [{}, { money: true }, { percent: true }]) {
    const option = toOption({ kind: "bar", labels: ["A"], values: [1], ...kind, series: [] }, light);
    for (const value of bad) {
      assert.equal(option.tooltip.valueFormatter(value), "—", JSON.stringify(kind) + " " + String(value));
    }
  }
});

test("every chart has the save-as-image tool", () => {
  const option = toOption({ kind: "line", labels: ["A"], values: [1], series: [] }, light);
  assert.ok(option.toolbox.feature.saveAsImage);
});

test("the category axis is categorical, so labels like 2024-07 are not read as dates", () => {
  const option = toOption({ kind: "line", labels: ["2024-07"], values: [1], series: [] }, light);
  assert.equal(option.xAxis.type, "category");
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
