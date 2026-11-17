// Unit tests for the pure helpers of order_template_editor.js (Task 7 of plan 2026-11-13-order-template-editor).
// Run: node --test app/static/js/order_template_editor.test.mjs. The script is a classic browser script loaded through
// require; under Node it exports only the two converters (toEditorJson, fromEditorJson). The Tiptap part is browser only.
import { createRequire } from "node:module";
import { test } from "vitest";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { toEditorJson, fromEditorJson, fieldIndex } = require("../../app/static/js/order_template_editor.js");

// An EditorDoc (the shape of app/employees/services/order_template_editor.py): a centred bold paragraph, a blank
// paragraph, and a paragraph with two field chips and text between them.
const doc = {
  paragraphs: [
    { align: "center", bold: true, italic: false, size: 14, show_if: null, numbered: false, parts: [{ text: "ТУШААЛ" }] },
    { align: "left", bold: false, italic: false, size: null, show_if: null, numbered: false, parts: [] },
    {
      align: "justify",
      bold: false,
      italic: true,
      size: 11,
      show_if: null,
      numbered: false,
      parts: [
        { text: "Ажилтан " },
        { field: "employee_full_name" },
        { text: " ажлаас гарсантай холбогдуулан, " },
        { field: "order_date" },
        { text: " өдрөөс эхлэн." },
      ],
    },
  ],
};

test("fromEditorJson(toEditorJson(doc)) gives back the same doc", () => {
  assert.deepEqual(fromEditorJson(toEditorJson(doc)), doc);
});

test("toEditorJson writes a ProseMirror doc with paragraph and field nodes", () => {
  const json = toEditorJson(doc);
  assert.equal(json.type, "doc");
  assert.equal(json.content[0].type, "paragraph");
  assert.deepEqual(json.content[0].attrs, { align: "center", bold: true, italic: false, size: 14, numbered: false, showIf: null });
  const chip = json.content[2].content[1];
  assert.deepEqual(chip, { type: "field", attrs: { name: "employee_full_name" } });
});

test("toEditorJson of a size null paragraph has no size attribute", () => {
  const json = toEditorJson({
    paragraphs: [{ align: "left", bold: false, italic: false, size: null, show_if: null, numbered: false, parts: [{ text: "x" }] }],
  });
  assert.equal(Object.prototype.hasOwnProperty.call(json.content[0].attrs, "size"), false);
});

test("an unknown align falls back to left in fromEditorJson", () => {
  const json = {
    type: "doc",
    content: [
      {
        type: "paragraph",
        attrs: { align: "middle", bold: false, italic: false, size: null },
        content: [{ type: "text", text: "a" }],
      },
    ],
  };
  assert.equal(fromEditorJson(json).paragraphs[0].align, "left");
});

test("an empty paragraph (no parts) round trips to parts []", () => {
  const blank = { paragraphs: [{ align: "left", bold: false, italic: false, size: null, show_if: null, numbered: false, parts: [] }] };
  const back = fromEditorJson(toEditorJson(blank));
  assert.deepEqual(back.paragraphs[0].parts, []);
  assert.deepEqual(back, blank);
});

test("text with leading and trailing spaces is preserved", () => {
  const spaced = {
    paragraphs: [{ align: "left", bold: false, italic: false, size: null, show_if: null, numbered: false, parts: [{ text: "  Тушаал  " }] }],
  };
  const back = fromEditorJson(toEditorJson(spaced));
  assert.equal(back.paragraphs[0].parts[0].text, "  Тушаал  ");
  assert.deepEqual(back, spaced);
});

test("two chips side by side round trip with no text between them", () => {
  const adjacent = {
    paragraphs: [
      {
        align: "right",
        bold: false,
        italic: false,
        size: 12,
        show_if: null,
        numbered: false,
        parts: [{ field: "employee_full_name" }, { field: "order_date" }],
      },
    ],
  };
  assert.deepEqual(fromEditorJson(toEditorJson(adjacent)), adjacent);
});

test("special characters and Cyrillic text round trip unchanged", () => {
  const text = `<b>Ажилтан</b> & "Өгөгдөл" 'тест' < > &amp; Ү ө`;
  const special = {
    paragraphs: [{ align: "left", bold: false, italic: false, size: null, show_if: null, numbered: false, parts: [{ text }, { field: "order_date" }, { text: ` ${text}` }] }],
  };
  const json = toEditorJson(special);
  assert.equal(json.content[0].content[0].text, text);
  assert.deepEqual(fromEditorJson(json), special);
});

test("a field node without attrs is dropped instead of throwing", () => {
  const json = {
    type: "doc",
    content: [
      {
        type: "paragraph",
        attrs: { align: "left", bold: false, italic: false, size: null },
        content: [{ type: "field" }, { type: "text", text: "a" }],
      },
    ],
  };
  assert.deepEqual(fromEditorJson(json).paragraphs[0].parts, [{ text: "a" }]);
});

test("a field named constructor does not resolve to Object.prototype members", () => {
  const map = fieldIndex([{ name: "constructor", label: "Х", for_this_type: true }]);
  assert.equal(map.constructor.label, "Х");
  assert.equal(Object.getPrototypeOf(map), null);
  assert.equal(fieldIndex([]).constructor, undefined);
  assert.equal(fieldIndex([]).toString, undefined);
  assert.equal(fieldIndex([{ name: "toString" }]).hasOwnProperty, undefined);
});

test("a numbered, conditional paragraph survives the round trip", () => {
  const item = {
    paragraphs: [
      { align: "left", bold: false, italic: false, size: null, show_if: "salary", numbered: true, parts: [{ text: "Цалин" }] },
    ],
  };
  const json = toEditorJson(item);
  assert.equal(json.content[0].attrs.numbered, true);
  assert.equal(json.content[0].attrs.showIf, "salary");
  assert.deepEqual(fromEditorJson(json), item);
});
