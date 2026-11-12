// Unit tests for report_memory.js: the pure helpers. Run: node --test <this file>.
// The script is a classic browser script, so it is loaded through require; under Node it exports these helpers only.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { storageKey, rememberable, restoreTarget, isResetLink } = require("./report_memory.js");

test("the key carries the user id and the report key", () => {
  assert.equal(storageKey("7", "/reports/orders/"), "hr.reportQuery.u7.orders");
});

test("no key without a user id, or outside a report's plain address", () => {
  assert.equal(storageKey("", "/reports/orders/"), null);
  assert.equal(storageKey("7", "/reports/"), null);
  assert.equal(storageKey("7", "/reports/orders/print/"), null);
});

test("rememberable drops the day and month parameters and keeps the rest in order", () => {
  assert.equal(rememberable("?state=all&as_of=2026-10-31&sort=name"), "?state=all&sort=name");
  assert.equal(rememberable("?layout=calendar&lmonth=2025-02&lby=hired"), "?layout=calendar&lby=hired");
});

test("rememberable drops the calendar week, a fixed date, and keeps the year window and grouping", () => {
  assert.equal(rememberable("?layout=calendar&lweek=2026-11-02"), "?layout=calendar");
  assert.equal(rememberable("?layout=timeline&lyear=2026&lgroup=dept&lweek=2026-11-02"), "?layout=timeline&lyear=2026&lgroup=dept");
});

test("rememberable returns nothing when only the day or month was set, or the search is empty", () => {
  assert.equal(rememberable("?as_of=2026-10-31"), "");
  assert.equal(rememberable(""), "");
});

test("rememberable keeps the other parameters exactly as encoded", () => {
  assert.equal(rememberable("?rules=%7B%22op%22%3A%22and%22%7D"), "?rules=%7B%22op%22%3A%22and%22%7D");
  assert.equal(rememberable("?q=a%20b+c&as_of=2026-10-31"), "?q=a%20b+c");
});

test("rememberable removes every occurrence of the day and month parameters", () => {
  assert.equal(rememberable("?as_of=2026-01-01&state=all&as_of=2026-02-02"), "?state=all");
});

test("a plain navigation with a saved setup goes to the setup", () => {
  assert.equal(restoreTarget("navigate", "/reports/orders/", "", "?order_type=1"), "/reports/orders/?order_type=1");
});

test("no restore on reload or back/forward", () => {
  assert.equal(restoreTarget("reload", "/reports/orders/", "", "?order_type=1"), null);
  assert.equal(restoreTarget("back_forward", "/reports/orders/", "", "?order_type=1"), null);
});

test("no restore when the address already has a query", () => {
  assert.equal(restoreTarget("navigate", "/reports/orders/", "?state=all", "?order_type=1"), null);
});

test("no restore when nothing usable is saved", () => {
  assert.equal(restoreTarget("navigate", "/reports/orders/", "", null), null);
  assert.equal(restoreTarget("navigate", "/reports/orders/", "", "x=1"), null);
});

test("no restore for a saved value that is only the question mark (corrupt storage would reload forever)", () => {
  assert.equal(restoreTarget("navigate", "/reports/orders/", "", "?"), null);
  assert.equal(restoreTarget("navigate", "/reports/orders/", "", ""), null);
});

test("a percent-encoded day or month parameter name is dropped too", () => {
  assert.equal(rememberable("?%61s_of=2026-01-01&state=all"), "?state=all");
  assert.equal(rememberable("?%6Cmonth=2026-01&state=all"), "?state=all");
});

test("a parameter name that cannot be decoded is not remembered", () => {
  assert.equal(rememberable("?%E0%A4%A=1&state=all"), "?state=all");
});

test("a reset link is one with data-reset-all, itself or above", () => {
  assert.equal(isResetLink({ closest: (s) => (s === "[data-reset-all]" ? {} : null) }), true);
  assert.equal(isResetLink({ closest: () => null }), false);
  assert.equal(isResetLink(null), false);
});
