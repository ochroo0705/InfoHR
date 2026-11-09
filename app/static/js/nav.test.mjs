// Unit tests for the menu closer in nav.js (top-bar and row-action menus). Run: node --test <this file>.
// nav.js is a classic browser script; under Node it exports createCloser, reopen and pickOpenMenu only. The menus and panels here are
// duck-typed stand-ins, and the fake hrLeave does what the real one does to the element (data-leaving + inert).
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { createCloser, pickOpenMenu } = require("./nav.js");

function makePanel() {
  const attrs = new Set();
  return {
    inert: false,
    hasAttribute: (name) => attrs.has(name),
    setAttribute: (name) => attrs.add(name),
    removeAttribute: (name) => attrs.delete(name),
  };
}

function makeMenu(open, panel) {
  return {
    open,
    querySelector: (sel) => (sel === "[data-nav-panel]" ? panel : null),
  };
}

// Records each call. Like the real hrLeave, it marks the element leaving and ignores a second call on it.
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

test("an open menu's panel leaves once, and done closes the menu and clears the leaving state", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  closeMenu(menu);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].el, panel);
  assert.equal(typeof calls[0].opts.done, "function");
  assert.equal(menu.open, true, "the menu stays open until its exit finishes");

  calls[0].opts.done();
  assert.equal(menu.open, false);
  assert.equal(panel.hasAttribute("data-leaving"), false);
  assert.equal(panel.inert, false);
});

test("a closed menu does nothing", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(false, panel);

  closeMenu(menu);
  assert.equal(calls.length, 0);
  assert.equal(menu.open, false);
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("a second close while the panel is leaving does not call hrLeave again", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  closeMenu(menu);
  closeMenu(menu);
  assert.equal(calls.length, 1);

  calls[0].opts.done();
  assert.equal(menu.open, false);
});

test("with no hrLeave the menu closes at once", () => {
  const closeMenu = createCloser(undefined);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  closeMenu(menu);
  assert.equal(menu.open, false);
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("a menu with no panel closes at once", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const menu = makeMenu(true, null);

  closeMenu(menu);
  assert.equal(calls.length, 0);
  assert.equal(menu.open, false);
});

// Fix round 1: a close can be undone by a reopen during its exit. The stale done() of the old exit must then do nothing.
const { reopen } = require("./nav.js");

test("close, reopen, then the pending done leaves the menu open", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  closeMenu(menu);
  reopen(menu);
  assert.equal(panel.hasAttribute("data-leaving"), false);
  assert.equal(panel.inert, false);
  calls[0].opts.done();
  assert.equal(menu.open, true, "the stale done of the undone exit must not close the menu");
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("reopen on a menu with no leaving panel is a no-op", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  reopen(menu);
  assert.equal(menu.open, true);
  assert.equal(panel.hasAttribute("data-leaving"), false);
  assert.equal(calls.length, 0);
  closeMenu(menu);  // still closes normally afterwards
  assert.equal(calls.length, 1);
});

test("a stale done from an older exit does not close a menu that is mid-way through a newer exit", () => {
  const { fn, calls } = fakeLeave();
  const closeMenu = createCloser(fn);
  const panel = makePanel();
  const menu = makeMenu(true, panel);

  closeMenu(menu);          // exit 1
  reopen(menu);             // undone
  closeMenu(menu);          // exit 2, in flight
  assert.equal(calls.length, 2);
  calls[0].opts.done();     // stale done of exit 1
  assert.equal(menu.open, true, "exit 2 is still in flight: the menu must stay open until its own done");
  assert.equal(panel.hasAttribute("data-leaving"), true);
  calls[1].opts.done();     // exit 2 finishes
  assert.equal(menu.open, false);
  assert.equal(panel.hasAttribute("data-leaving"), false);
});

test("pickOpenMenu skips a menu whose panel is leaving, and returns the really open one", () => {
  const leavingPanel = makePanel();
  leavingPanel.setAttribute("data-leaving");
  const leaving = makeMenu(true, leavingPanel);
  const openPanel = makePanel();
  const open = makeMenu(true, openPanel);
  assert.equal(pickOpenMenu([leaving, open]), open, "the mid-exit menu must not be picked");
  assert.equal(pickOpenMenu([open, leaving]), open, "document order does not matter");
});

test("pickOpenMenu returns null when every open menu is leaving or closed", () => {
  const leavingPanel = makePanel();
  leavingPanel.setAttribute("data-leaving");
  assert.equal(pickOpenMenu([makeMenu(true, leavingPanel), makeMenu(false, makePanel())]), null);
  assert.equal(pickOpenMenu([]), null);
});
