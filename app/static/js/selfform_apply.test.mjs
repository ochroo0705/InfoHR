// Unit tests for selfform_apply.js: the pure helpers (row index, row cap, send rule, placeholder, draft fields).
// Run: node --test app/static/js/selfform_apply.test.mjs
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { nextRowIndex, canAddRow, sendEnabled, replacePlaceholder, draftFields, PLACEHOLDER } = require("./selfform_apply.js");

test("the next row index is one more than the highest index in use, 0 when there are none", () => {
  assert.equal(nextRowIndex([]), 0);
  assert.equal(nextRowIndex([0, 1, 2]), 3);
  assert.equal(nextRowIndex([0, 4]), 5);
  assert.equal(nextRowIndex([NaN, 2]), 3);
});

test("a row can be added only below the cap", () => {
  assert.equal(canAddRow(9, 10), true);
  assert.equal(canAddRow(10, 10), false);
  assert.equal(canAddRow(0, 20), true);
  assert.equal(canAddRow(20, 20), false);
});

test("send is enabled only when both ticks are on", () => {
  assert.equal(sendEnabled(true, true), true);
  assert.equal(sendEnabled(true, false), false);
  assert.equal(sendEnabled(false, true), false);
  assert.equal(sendEnabled(false, false), false);
  assert.equal(sendEnabled(undefined, undefined), false);
});

test("the placeholder is replaced in every occurrence", () => {
  assert.equal(PLACEHOLDER, "__i__");
  assert.equal(replacePlaceholder("edu-__i__-org_name", 3), "edu-3-org_name");
  assert.equal(replacePlaceholder("__i__/__i__", 0), "0/0");
  assert.equal(replacePlaceholder("person-given_name", 7), "person-given_name");
});

test("the draft leaves out the photo and both ticks, and keeps the text fields", () => {
  const data = new FormData();
  data.append("csrfmiddlewaretoken", "t");
  data.append("person-given_name", "Сараа");
  data.append("photo", new Blob(["x"], { type: "image/png" }), "a.png");
  data.append("agreed_correct", "1");
  data.append("consent", "1");

  const kept = draftFields(data);

  assert.deepEqual([...kept.keys()].sort(), ["csrfmiddlewaretoken", "person-given_name"]);
});

test("Enter in a text box or select moves to the next step before the last one", () => {
  const { enterAction } = require("./selfform_apply.js");
  assert.equal(enterAction(0, 3, "INPUT"), "next");
  assert.equal(enterAction(2, 3, "INPUT"), "next");
  assert.equal(enterAction(1, 3, "SELECT"), "next");
});

test("Enter on the last step, in a textarea, a button or a link is left to the browser", () => {
  const { enterAction } = require("./selfform_apply.js");
  assert.equal(enterAction(3, 3, "INPUT"), "allow");
  assert.equal(enterAction(3, 3, "SELECT"), "allow");
  assert.equal(enterAction(0, 3, "TEXTAREA"), "allow");
  assert.equal(enterAction(0, 3, "BUTTON"), "allow");
  assert.equal(enterAction(0, 3, "A"), "allow");
});
