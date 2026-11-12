// Unit tests for the signature pad (signature_pad.js). Run: node --test app/static/js/signature_pad.test.mjs
// signature_pad.js is a classic browser script; under Node it exports canvasPoint, modeFor, nextMode and install.
// install(doc) registers the same delegated listeners the browser gets, so the tests drive them through a fake
// document and duck-typed elements (only the methods the script uses).
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { canvasPoint, modeFor, nextMode, install } = require("./signature_pad.js");

// --- duck-typed DOM ---------------------------------------------------------------------------------------------

// Matches the simple selectors the script uses: an optional tag, then [name] or [name="value"] parts.
function matchesSimple(node, sel) {
  const m = /^([a-z]*)((?:\[[^\]]+\])*)$/i.exec(sel);
  if (!m) throw new Error(`unsupported selector: ${sel}`);
  if (m[1] && node.tagName !== m[1].toUpperCase()) return false;
  const parts = m[2].match(/\[[^\]]+\]/g) || [];
  return parts.every((part) => {
    const [name, value] = part.slice(1, -1).split("=");
    if (!node.hasAttribute(name)) return false;
    return value === undefined || node.getAttribute(name) === value.replace(/^"|"$/g, "");
  });
}

function walk(node, visit) {
  for (const child of node.children) {
    visit(child);
    walk(child, visit);
  }
}

function el(tag, attrs = {}, parent = null) {
  const node = {
    tagName: tag.toUpperCase(),
    attrs: { ...attrs },
    parent,
    children: [],
    value: attrs.value ?? "",
    disabled: false,
    style: {},
    rect: { left: 0, top: 0, width: 600, height: 200 },
    width: 600,
    height: 200,
    calls: [],
    hasAttribute: (n) => n in node.attrs,
    getAttribute: (n) => (n in node.attrs ? node.attrs[n] : null),
    setAttribute: (n, v) => { node.attrs[n] = String(v); },
    removeAttribute: (n) => { delete node.attrs[n]; },
    matches: (sel) => matchesSimple(node, sel),
    closest: (sel) => {
      for (let n = node; n; n = n.parent) if (n.matches(sel)) return n;
      return null;
    },
    querySelector: (sel) => {
      let found = null;
      walk(node, (c) => { if (!found && matchesSimple(c, sel)) found = c; });
      return found;
    },
    querySelectorAll: (sel) => {
      const out = [];
      walk(node, (c) => { if (matchesSimple(c, sel)) out.push(c); });
      return out;
    },
    getBoundingClientRect: () => node.rect,
    getContext: () => node.ctx,
    toDataURL: () => "data:image/png;base64,AAAA",
    setPointerCapture: () => node.calls.push(["setPointerCapture"]),
    releasePointerCapture: () => node.calls.push(["releasePointerCapture"]),
    isConnected: true,
    events: [],
    dispatchEvent: (ev) => { node.events.push(ev); return true; },
  };
  node.ctx = recordingContext(node.calls);
  if (parent) parent.children.push(node);
  return node;
}

// A 2D context that records what the script does to it.
function recordingContext(calls) {
  const ctx = {
    strokeStyle: null,
    fillStyle: null,
    lineWidth: null,
    lineCap: null,
    lineJoin: null,
  };
  for (const name of ["beginPath", "moveTo", "lineTo", "stroke", "fill", "arc", "clearRect"]) {
    ctx[name] = (...args) => calls.push([name, ...args]);
  }
  return ctx;
}

function fakeDocument() {
  const listeners = {};
  return {
    addEventListener(type, fn, capture) {
      (listeners[type] ||= []).push({ fn, capture: !!capture });
    },
    // Runs the listeners of one type; capture listeners first, as the browser does for document-level listeners.
    fire(type, event) {
      const list = listeners[type] || [];
      for (const { fn } of list.filter((l) => l.capture)) fn(event);
      for (const { fn } of list.filter((l) => !l.capture)) fn(event);
      return event;
    },
  };
}

function makeEvent(target, extra = {}) {
  const ev = {
    target,
    pointerId: 1,
    button: 0,
    clientX: 0,
    clientY: 0,
    defaultPrevented: false,
    propagationStopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.propagationStopped = true; },
    ...extra,
  };
  return ev;
}

// A pop-up form as _order_sign.html renders it. withSaved adds the saved-signature section; the draw section is
// hidden then, as in the template.
function signForm({ withSaved }) {
  const root = el("div", {});
  const form = el("form", { "data-signature-form": "" }, root);
  el("input", { type: "hidden", name: "mode", value: withSaved ? "saved" : "drawn" }, form);
  el("input", { type: "hidden", name: "signature", value: "" }, form);
  if (withSaved) {
    const saved = el("section", { "data-sign-section": "saved" }, form);
    el("button", { type: "button", "data-sign-show": "draw" }, saved);
  }
  const draw = el("section", { "data-sign-section": "draw", ...(withSaved ? { hidden: "" } : {}) }, form);
  const canvas = el("canvas", { "data-signature-pad": "", width: "600", height: "200" }, draw);
  el("button", { type: "button", "data-signature-clear": "" }, draw);
  el("button", { type: "submit", "data-signature-submit": "", disabled: "" }, draw);
  if (withSaved) el("button", { type: "button", "data-sign-show": "saved" }, draw);
  const submit = form.querySelector("[data-signature-submit]");
  submit.disabled = true;
  return { root, form, canvas, draw, submit, mode: form.querySelector('input[name="mode"]'), sig: form.querySelector('input[name="signature"]') };
}

function setup(opts) {
  const doc = fakeDocument();
  install(doc);
  return { doc, ...signForm(opts) };
}

function stroke(doc, canvas, points) {
  const [first, ...rest] = points;
  doc.fire("pointerdown", makeEvent(canvas, { clientX: first[0], clientY: first[1] }));
  for (const [x, y] of rest) doc.fire("pointermove", makeEvent(canvas, { clientX: x, clientY: y }));
  doc.fire("pointerup", makeEvent(canvas, { clientX: points[points.length - 1][0], clientY: points[points.length - 1][1] }));
}

// --- pure helpers -----------------------------------------------------------------------------------------------

test("canvasPoint maps client coordinates to canvas pixels on a scaled canvas", () => {
  // The canvas is 600x200 pixels but drawn 300x100 CSS pixels at (100, 50).
  const rect = { left: 100, top: 50, width: 300, height: 100 };
  const size = { width: 600, height: 200 };
  assert.deepEqual(canvasPoint(rect, size, 250, 100), { x: 300, y: 100 });
  assert.deepEqual(canvasPoint(rect, size, 100, 50), { x: 0, y: 0 });
  assert.deepEqual(canvasPoint(rect, size, 400, 150), { x: 600, y: 200 });
});

test("canvasPoint keeps a 1:1 canvas unchanged apart from the offset", () => {
  const rect = { left: 10, top: 20, width: 600, height: 200 };
  assert.deepEqual(canvasPoint(rect, { width: 600, height: 200 }, 35, 45), { x: 25, y: 25 });
});

test("modeFor maps the switch buttons to the mode value", () => {
  assert.equal(modeFor("draw"), "drawn");
  assert.equal(modeFor("saved"), "saved");
  assert.equal(modeFor("other"), null);
});

test("nextMode takes a known wanted mode and keeps the current value otherwise", () => {
  assert.equal(nextMode("saved", "drawn"), "drawn");
  assert.equal(nextMode("drawn", "saved"), "saved");
  assert.equal(nextMode("saved", "bogus"), "saved");
  assert.equal(nextMode("drawn", null), "drawn");
});

// --- delegated behaviour ----------------------------------------------------------------------------------------

test("a fresh pad with no stroke keeps the sign button disabled and the signature empty", () => {
  const { submit, sig } = setup({ withSaved: false });
  assert.equal(submit.disabled, true);
  assert.equal(sig.value, "");
});

test("one stroke writes the PNG into the signature input and enables the sign button", () => {
  const { doc, canvas, sig, submit } = setup({ withSaved: false });
  stroke(doc, canvas, [[10, 10], [50, 40], [90, 20]]);
  assert.equal(sig.value, "data:image/png;base64,AAAA");
  assert.equal(submit.disabled, false);
});

test("the stroke uses the ink colour, width and round caps, and draws segments while the pointer is down", () => {
  const { doc, canvas } = setup({ withSaved: false });
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  const calls = canvas.calls.map((c) => c[0]);
  assert.ok(calls.includes("stroke"), "a moved pointer strokes a segment");
  assert.equal(canvas.ctx.strokeStyle, "#1a3a8a");
  assert.equal(canvas.ctx.lineWidth, 2.5);
  assert.equal(canvas.ctx.lineCap, "round");
  assert.equal(canvas.ctx.lineJoin, "round");
  assert.ok(calls.includes("setPointerCapture"), "the pointer is captured on pointerdown");
});

test("a finished stroke dispatches a bubbling input event on the signature input", () => {
  const { doc, canvas, sig } = setup({ withSaved: false });
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  assert.equal(sig.events.length, 1);
  assert.equal(sig.events[0].type, "input");
  assert.equal(sig.events[0].bubbles, true);
});

test("clearing a drawn signature dispatches input once; clearing an empty pad dispatches nothing", () => {
  const { doc, root, canvas, sig } = setup({ withSaved: false });
  const clear = root.querySelector("[data-signature-clear]");
  doc.fire("click", makeEvent(clear));
  assert.equal(sig.events.length, 0, "nothing changed, no event");
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  assert.equal(sig.events.length, 1);
  doc.fire("click", makeEvent(clear));
  assert.equal(sig.events.length, 2);
  assert.equal(sig.events[1].type, "input");
  assert.equal(sig.events[1].bubbles, true);
  doc.fire("click", makeEvent(clear));
  assert.equal(sig.events.length, 2, "a second clear changes nothing");
});

test("a second pointer going down during a stroke is ignored; only the first pointer ends it", () => {
  const { doc, canvas, sig } = setup({ withSaved: false });
  doc.fire("pointerdown", makeEvent(canvas, { pointerId: 1, clientX: 10, clientY: 10 }));
  doc.fire("pointerdown", makeEvent(canvas, { pointerId: 2, clientX: 200, clientY: 100 }));
  assert.equal(canvas.calls.filter((c) => c[0] === "setPointerCapture").length, 1);
  doc.fire("pointermove", makeEvent(canvas, { pointerId: 2, clientX: 300, clientY: 150 }));
  doc.fire("pointerup", makeEvent(canvas, { pointerId: 2, clientX: 300, clientY: 150 }));
  assert.equal(sig.value, "", "the second pointer's release does not finish the stroke");
  assert.equal(sig.events.length, 0);
  doc.fire("pointermove", makeEvent(canvas, { pointerId: 1, clientX: 50, clientY: 40 }));
  doc.fire("pointerup", makeEvent(canvas, { pointerId: 1, clientX: 50, clientY: 40 }));
  assert.equal(sig.value, "data:image/png;base64,AAAA");
  assert.equal(sig.events.length, 1);
});

test("a stroke on a pad removed mid-drag (no up) does not block a stroke on another pad", () => {
  const { doc, canvas: padA } = setup({ withSaved: false });
  const { canvas: padB, sig: sigB, submit: submitB } = signForm({ withSaved: false });
  doc.fire("pointerdown", makeEvent(padA, { pointerId: 1, clientX: 10, clientY: 10 }));
  padA.isConnected = false;  // the pop-up was removed; no pointerup or cancel arrives
  doc.fire("pointerdown", makeEvent(padB, { pointerId: 1, clientX: 20, clientY: 20 }));
  assert.ok(padB.calls.some((c) => c[0] === "setPointerCapture"), "pad B takes the new stroke");
  doc.fire("pointermove", makeEvent(padB, { pointerId: 1, clientX: 60, clientY: 50 }));
  doc.fire("pointerup", makeEvent(padB, { pointerId: 1, clientX: 60, clientY: 50 }));
  assert.equal(sigB.value, "data:image/png;base64,AAAA");
  assert.equal(submitB.disabled, false);
});

test("a lost pointer capture ends the stroke and writes the signature", () => {
  const { doc, canvas, sig, submit } = setup({ withSaved: false });
  doc.fire("pointerdown", makeEvent(canvas, { pointerId: 1, clientX: 10, clientY: 10 }));
  doc.fire("lostpointercapture", makeEvent(canvas, { pointerId: 1 }));
  assert.equal(sig.value, "data:image/png;base64,AAAA");
  assert.equal(submit.disabled, false);
});

test("pointermove without a pointerdown on the pad draws nothing", () => {
  const { doc, canvas, sig, submit } = setup({ withSaved: false });
  doc.fire("pointermove", makeEvent(canvas, { clientX: 20, clientY: 20 }));
  doc.fire("pointerup", makeEvent(canvas, { clientX: 20, clientY: 20 }));
  assert.equal(canvas.calls.length, 0);
  assert.equal(sig.value, "");
  assert.equal(submit.disabled, true);
});

test("a right-button press does not start a stroke", () => {
  const { doc, canvas, submit } = setup({ withSaved: false });
  doc.fire("pointerdown", makeEvent(canvas, { button: 2, clientX: 5, clientY: 5 }));
  doc.fire("pointerup", makeEvent(canvas, { button: 2, clientX: 5, clientY: 5 }));
  assert.equal(submit.disabled, true);
});

test("pointercancel ends the stroke and writes the signature like pointerup", () => {
  const { doc, canvas, sig, submit } = setup({ withSaved: false });
  doc.fire("pointerdown", makeEvent(canvas, { clientX: 5, clientY: 5 }));
  doc.fire("pointercancel", makeEvent(canvas, { clientX: 5, clientY: 5 }));
  assert.equal(sig.value, "data:image/png;base64,AAAA");
  assert.equal(submit.disabled, false);
});

test("clear empties the canvas and the input and disables the sign button again", () => {
  const { doc, root, canvas, sig, submit } = setup({ withSaved: false });
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  assert.equal(submit.disabled, false);
  const clear = root.querySelector("[data-signature-clear]");
  doc.fire("click", makeEvent(clear));
  assert.equal(sig.value, "");
  assert.equal(submit.disabled, true);
  assert.ok(canvas.calls.some((c) => c[0] === "clearRect"), "the canvas is cleared");
});

test("the canvas is never filled with a background (it stays transparent)", () => {
  const { doc, canvas } = setup({ withSaved: false });
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  assert.ok(!canvas.calls.some((c) => c[0] === "fillRect"), "no fillRect on the canvas");
});

test("clicking «Өөр гарын үсэг зурах» shows the draw section and sets mode to drawn", () => {
  const { doc, form, draw, mode } = setup({ withSaved: true });
  const saved = form.querySelector('[data-sign-section="saved"]');
  assert.equal(draw.hasAttribute("hidden"), true);
  assert.equal(mode.value, "saved");
  doc.fire("click", makeEvent(saved.querySelector('[data-sign-show="draw"]')));
  assert.equal(saved.hasAttribute("hidden"), true);
  assert.equal(draw.hasAttribute("hidden"), false);
  assert.equal(mode.value, "drawn");
});

test("clicking «Буцах» shows the saved section again, sets mode to saved and clears the drawing", () => {
  const { doc, form, draw, canvas, sig, submit, mode } = setup({ withSaved: true });
  const saved = form.querySelector('[data-sign-section="saved"]');
  doc.fire("click", makeEvent(saved.querySelector('[data-sign-show="draw"]')));
  stroke(doc, canvas, [[10, 10], [50, 40]]);
  assert.equal(submit.disabled, false);
  doc.fire("click", makeEvent(draw.querySelector('[data-sign-show="saved"]')));
  assert.equal(saved.hasAttribute("hidden"), false);
  assert.equal(draw.hasAttribute("hidden"), true);
  assert.equal(mode.value, "saved");
  assert.equal(sig.value, "");
  assert.equal(submit.disabled, true);
  assert.ok(canvas.calls.some((c) => c[0] === "clearRect"));
});

test("Enter on a drawn form with no signature is stopped before the form is sent", () => {
  const { doc, form } = setup({ withSaved: false });
  const ev = makeEvent(form);
  doc.fire("submit", ev);
  assert.equal(ev.defaultPrevented, true);
  assert.equal(ev.propagationStopped, true);
});

test("a submit with a drawn signature, or in saved mode, goes through", () => {
  const drawn = setup({ withSaved: false });
  stroke(drawn.doc, drawn.canvas, [[10, 10], [50, 40]]);
  const ev1 = makeEvent(drawn.form);
  drawn.doc.fire("submit", ev1);
  assert.equal(ev1.defaultPrevented, false);

  const saved = setup({ withSaved: true });
  const ev2 = makeEvent(saved.form);
  saved.doc.fire("submit", ev2);
  assert.equal(ev2.defaultPrevented, false);
});

test("a submit of a form that is not a signature form is left alone", () => {
  const { doc } = setup({ withSaved: false });
  const other = el("form", {}, null);
  const ev = makeEvent(other);
  doc.fire("submit", ev);
  assert.equal(ev.defaultPrevented, false);
});

test("an inserted pad gets role img, the Mongolian aria-label and touch-action none, keeping an existing label", () => {
  const doc = fakeDocument();
  install(doc);
  const root = el("div", {});
  const canvas = el("canvas", { "data-signature-pad": "" }, root);
  const labelled = el("canvas", { "data-signature-pad": "", "aria-label": "Өөр", role: "group" }, root);
  doc.fire("htmx:load", { detail: { elt: root } });
  assert.equal(canvas.getAttribute("role"), "img");
  assert.equal(canvas.getAttribute("aria-label"), "Гарын үсэг зурах талбар");
  assert.equal(canvas.style.touchAction, "none");
  assert.equal(labelled.getAttribute("aria-label"), "Өөр");
  assert.equal(labelled.getAttribute("role"), "group");
});
