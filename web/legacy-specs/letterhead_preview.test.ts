// Unit tests for the pure helper of letterhead_preview.js (Task 8 of plan 2026-11-13-order-template-editor).
// Run: node --test app/static/js/letterhead_preview.test.mjs. The script is a classic browser script loaded through
// require; under Node it exports only mockStyle.
import { createRequire } from "node:module";
import { test } from "vitest";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { mockStyle } = require("../../app/static/js/letterhead_preview.js");

test("defaults are left logo, left text, medium logo, no rule", () => {
  const s = mockStyle({});
  assert.equal(s.place, "left");
  assert.equal(s.textAlign, "left");
  assert.equal(s.logoSize, "medium");
  assert.equal(s.rule, false);
  assert.equal(s.showLogo, true);
  assert.equal(s.showText, true);
});

test("logo widths are 20, 30 and 45 mm on a 210 mm page", () => {
  assert.equal(mockStyle({ logo_size: "small" }).logoWidthPct, 9.5);
  assert.equal(mockStyle({ logo_size: "medium" }).logoWidthPct, 14.3);
  assert.equal(mockStyle({ logo_size: "large" }).logoWidthPct, 21.4);
});

test("logo only hides the text", () => {
  const s = mockStyle({ logo_place: "logo_only", rule: true });
  assert.equal(s.place, "logo_only");
  assert.equal(s.showText, false);
  assert.equal(s.showLogo, true);
  assert.equal(s.rule, true);
});

test("classes name the place, alignment, size and rule", () => {
  const s = mockStyle({ logo_place: "top", text_align: "center", logo_size: "large", rule: true });
  assert.deepEqual(s.classes, ["lh-mock", "lh-place-top", "lh-align-center", "lh-size-large", "lh-rule"]);
});

test("unknown values fall back to the defaults, never to raw input", () => {
  const s = mockStyle({ logo_place: "<script>", text_align: "justify", logo_size: "huge", rule: "on" });
  assert.equal(s.place, "left");
  assert.equal(s.textAlign, "left");
  assert.equal(s.logoSize, "medium");
  assert.equal(s.rule, false);
});

test("a missing argument gives the defaults", () => {
  assert.equal(mockStyle().place, "left");
});

test("expandLines replaces the company and director tokens and drops empty lines", () => {
  const { expandLines } = require("../../app/static/js/letterhead_preview.js");
  const lines = expandLines("{company_name}\n\n  Захирал: {director_name}  \nУлаанбаатар", "MACS ХХК", "Б.Бат");
  assert.deepEqual(lines, ["MACS ХХК", "Захирал: Б.Бат", "Улаанбаатар"]);
});

test("expandLines with no names keeps the rest of the line", () => {
  const { expandLines } = require("../../app/static/js/letterhead_preview.js");
  assert.deepEqual(expandLines("{company_name} тел: 7711", "", ""), ["тел: 7711"]);
});
