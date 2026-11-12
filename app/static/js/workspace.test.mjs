// Unit tests for workspace.js: the pure helpers only. Run: node --test <this file>.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { cleanCell, tsvText, countLabel, moreOffered } = require("./workspace.js");

test("cleanCell removes tabs and line breaks and trims", () => {
  assert.equal(cleanCell("  a\tb\r\nc  "), "a b c");
  assert.equal(cleanCell(null), "");
  assert.equal(cleanCell(undefined), "");
  assert.equal(cleanCell(12), "12");
});

test("cleanCell makes a formula-like cell text with one single quote in front", () => {
  assert.equal(cleanCell("=1+1"), "'=1+1");
  assert.equal(cleanCell(" =1"), "'=1");
  assert.equal(cleanCell("@x"), "'@x");
  assert.equal(cleanCell("-2"), "'-2");
  assert.equal(cleanCell("+5"), "'+5");
  assert.equal(cleanCell("\t=x"), "'=x");
  assert.equal(cleanCell("a=b"), "a=b"); // not at the start: untouched
  assert.equal(cleanCell("Aigerim"), "Aigerim");
  assert.equal(cleanCell(""), "");
});

test("cleanCell cleans first, then quotes: hidden whitespace cannot hide a formula start", () => {
  assert.equal(cleanCell("\n=1+1"), "'=1+1");
  assert.equal(cleanCell(" =1+1"), "'=1+1");
  assert.equal(cleanCell("\t=x"), "'=x");
  assert.equal(cleanCell("\u00a0=1"), "'=1");
  assert.equal(cleanCell("\x1c=1"), "'=1");
  assert.equal(cleanCell("\ufeff+5"), "'+5");
  assert.equal(cleanCell("ok"), "ok");
  assert.equal(cleanCell("a=b"), "a=b");
  assert.equal(cleanCell("  "), "");
});

test("tsvText writes the header line and one line per row", () => {
  const text = tsvText(["ID", "NAME"], [["1", "Aigerim"], ["2", "Bat\tX"]]);
  assert.equal(text, "ID\tNAME\n1\tAigerim\n2\tBat X");
});

test("tsvText with no rows is the header alone", () => {
  assert.equal(tsvText(["ID"], []), "ID");
});

test("countLabel says whether the count covers all matching rows", () => {
  assert.equal(countLabel(3, false), "3 мөр сонгосон");
  assert.equal(countLabel(250, true), "250 мөр сонгосон (бүгд)");
});

test("moreOffered needs the header box, a copy address, more rows than drawn and not all-mode yet", () => {
  assert.equal(moreOffered(false, true, 100, 250, true), true);
  assert.equal(moreOffered(false, false, 100, 250, true), false); // header box not ticked
  assert.equal(moreOffered(false, true, 100, 100, true), false); // every row is drawn already
  assert.equal(moreOffered(true, true, 100, 250, true), false); // already all rows
  assert.equal(moreOffered(false, true, 100, 250, false), false); // no server address
});
