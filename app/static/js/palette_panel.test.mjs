// Unit tests for the assistant panel's exit state in palette.js (plan 2026-11-08-selection-motion, task 9). Run:
// node --test <this file>. palette.js is a classic browser script; under Node it exports only its pure exit helpers.
// The panel is a duck-typed stand-in, and the fake hrLeave does what the real one does to the element (data-leaving +
// inert) and calls done only when the test says the exit has ended.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { isPanelOpen, startExit, cancelExit, workspaceFormPlan } = require("./palette.js");

function makePanel(hidden) {
  const attrs = new Set();
  return {
    hidden,
    inert: false,
    hasAttribute: (name) => attrs.has(name),
    setAttribute: (name) => attrs.add(name),
    removeAttribute: (name) => attrs.delete(name),
  };
}

function fakeLeave() {
  const calls = [];
  const fn = (el, opts) => {
    calls.push({ el, opts });
    if (el.hasAttribute("data-leaving")) return;
    el.setAttribute("data-leaving");
    el.inert = true;
  };
  return { fn, calls };
}

test("a visible panel that is not leaving is open; hidden or leaving is not", () => {
  const panel = makePanel(false);
  assert.equal(isPanelOpen(panel), true);
  panel.setAttribute("data-leaving");
  assert.equal(isPanelOpen(panel), false, "a leaving panel is not open from the moment its exit starts");
  assert.equal(isPanelOpen(makePanel(true)), false);
});

test("closing starts the exit: the panel is no longer open but stays visible until the exit ends", () => {
  const panel = makePanel(false);
  const { fn, calls } = fakeLeave();
  let hides = 0;
  startExit(panel, fn, () => { hides += 1; panel.hidden = true; });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].el, panel);
  assert.equal(isPanelOpen(panel), false);
  assert.equal(panel.hidden, false, "hidden is delayed until the slide-out ends");
  assert.equal(hides, 0);
  calls[0].opts.done();
  assert.equal(hides, 1);
  assert.equal(panel.hidden, true);
  assert.equal(panel.hasAttribute("data-leaving"), false);
  assert.equal(panel.inert, false);
});

test("open, close, open quickly: the panel ends visible, not leaving, and open", () => {
  const panel = makePanel(false);
  const { fn, calls } = fakeLeave();
  startExit(panel, fn, () => { panel.hidden = true; });  // close
  cancelExit(panel);                                      // open again before the exit ends
  assert.equal(isPanelOpen(panel), true);
  calls[0].opts.done();                                   // the exit that was cancelled ends now
  assert.equal(panel.hidden, false, "the stale done must not hide the reopened panel");
  assert.equal(panel.hasAttribute("data-leaving"), false);
  assert.equal(panel.inert, false);
  assert.equal(isPanelOpen(panel), true);
});

test("close, reopen, close again: only the newest exit hides the panel", () => {
  const panel = makePanel(false);
  const { fn, calls } = fakeLeave();
  const hide = () => { panel.hidden = true; };
  startExit(panel, fn, hide);  // exit 1
  cancelExit(panel);           // reopened
  startExit(panel, fn, hide);  // exit 2, in flight
  calls[0].opts.done();        // stale done of exit 1
  assert.equal(panel.hidden, false, "exit 2 is still in flight");
  assert.equal(panel.hasAttribute("data-leaving"), true);
  calls[1].opts.done();        // exit 2 ends
  assert.equal(panel.hidden, true);
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("without hrLeave the panel is hidden at once", () => {
  const panel = makePanel(false);
  let hides = 0;
  startExit(panel, undefined, () => { hides += 1; panel.hidden = true; });
  assert.equal(hides, 1);
  assert.equal(panel.hidden, true);
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("the «Хүснэгт болгон нээх» form posts to its own address with the token as a hidden field", () => {
  const plan = workspaceFormPlan("/assistant/workspace/open/42/", "tok123");
  assert.equal(plan.method, "post");
  assert.equal(plan.action, "/assistant/workspace/open/42/");
  assert.deepEqual(plan.fields, [{ name: "csrfmiddlewaretoken", value: "tok123" }]);
});

test("no CSRF token gives no form plan, so nothing is sent without one", () => {
  assert.equal(workspaceFormPlan("/assistant/workspace/open/42/", ""), null);
  assert.equal(workspaceFormPlan("/assistant/workspace/open/42/", undefined), null);
});
