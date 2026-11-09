// Unit tests for motion.js: the shared exit helper hrLeave. Run: node --test <this file>.
// motion.js is a classic browser script; under Node it exports createLeave and hrLeave only. The DOM is faked here
// (only the members hrLeave uses), and timers and reduced motion are injected through the env argument of createLeave.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { createLeave, createCollapse, deleteRow } = require("./motion.js");

function fakeEl(opts = {}) {
  const attrs = new Set();
  const listeners = {};
  const el = {
    isConnected: opts.isConnected !== false,
    inert: false,
    removed: 0,
    setAttribute(name) {
      attrs.add(name);
    },
    removeAttribute(name) {
      attrs.delete(name);
    },
    hasAttribute(name) {
      return attrs.has(name);
    },
    addEventListener(type, fn) {
      (listeners[type] ||= new Set()).add(fn);
    },
    removeEventListener(type, fn) {
      if (listeners[type]) listeners[type].delete(fn);
    },
    remove() {
      el.removed += 1;
      el.isConnected = false;
    },
    // Fires an event on the element; target defaults to the element itself (a bubbled child event passes its own).
    // Extra event fields (propertyName for transitionend) go in extra.
    fire(type, target, extra = {}) {
      for (const fn of [...(listeners[type] || [])]) fn({ type, target: target ?? el, ...extra });
    },
    listenerCount(type) {
      return (listeners[type] || new Set()).size;
    },
  };
  return el;
}

function fakeEnv(opts = {}) {
  const timers = new Map();
  let nextId = 1;
  const env = {
    timers,
    matchMedia(query) {
      return { matches: !!opts.reduced && query.includes("prefers-reduced-motion") };
    },
    setTimeout(fn, ms) {
      const id = nextId++;
      timers.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    runTimers() {
      for (const [id, t] of [...timers]) {
        timers.delete(id);
        t.fn();
      }
    },
  };
  return env;
}

test("finishes via the 250 ms fallback timer when no animation event fires", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  assert.equal(el.hasAttribute("data-leaving"), true, "the element is marked data-leaving");
  assert.equal(el.inert, true, "the element is inert while it leaves");
  assert.equal(calls, 0, "done waits for the exit");
  assert.equal(env.timers.size, 1, "one fallback timer is scheduled");
  assert.equal([...env.timers.values()][0].ms, 250, "the fallback is 250 ms");
  env.runTimers();
  assert.equal(calls, 1, "the fallback timer finishes the exit");
});

test("calls done exactly once when hrLeave is called twice on the same element", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  const done = () => (calls += 1);
  hrLeave(el, { done });
  hrLeave(el, { done });
  assert.equal(env.timers.size, 1, "the second call schedules nothing");
  el.fire("animationend");
  assert.equal(calls, 1, "animationend finishes the exit");
  env.runTimers();
  assert.equal(calls, 1, "a late fallback does not call done again");
  assert.equal(el.listenerCount("animationend"), 0, "listeners are removed on finish");
  assert.equal(el.listenerCount("transitionend"), 0, "listeners are removed on finish");
  assert.equal(env.timers.size, 0, "the fallback timer is cleared on finish");
});

test("finishes at once, without a timer, when reduced motion matches", () => {
  const env = fakeEnv({ reduced: true });
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  assert.equal(calls, 1, "done runs synchronously under reduced motion");
  assert.equal(env.timers.size, 0, "no timer is scheduled");
});

test("removes the element at once by default under reduced motion", () => {
  const env = fakeEnv({ reduced: true });
  const hrLeave = createLeave(env);
  const el = fakeEl();
  hrLeave(el);
  assert.equal(el.removed, 1, "the default done removes the element");
});

test("does not throw when the element is already disconnected or removed meanwhile", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const gone = fakeEl({ isConnected: false });
  let calls = 0;
  assert.doesNotThrow(() => hrLeave(gone, { done: () => (calls += 1) }));
  assert.equal(calls, 1, "a disconnected element finishes at once");

  const el = fakeEl();
  hrLeave(el, { done: () => (calls += 1) });
  el.remove();
  assert.doesNotThrow(() => env.runTimers());
  assert.equal(calls, 2, "done still runs once after the element was removed meanwhile");
});

test("an animationend from a child (target !== el) is ignored", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  const child = {};
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  el.fire("animationend", child);
  el.fire("transitionend", child);
  assert.equal(calls, 0, "bubbled child events do not finish the exit");
  assert.equal(env.timers.size, 1, "the fallback timer is still pending");
  el.fire("animationend");
  assert.equal(calls, 1, "the element's own animationend finishes the exit");
});

test("done that throws still clears the leaving state, runs once, and rethrows", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, {
    done: () => {
      calls += 1;
      throw new Error("boom");
    },
  });
  assert.throws(() => el.fire("animationend"), /boom/, "the error from done is rethrown");
  assert.equal(calls, 1, "done ran once");
  assert.equal(el.hasAttribute("data-leaving"), false, "data-leaving is cleared even though done threw");
  assert.equal(el.inert, false, "the element is no longer inert even though done threw");
  assert.equal(env.timers.size, 0, "the fallback timer is cleared");
  env.runTimers();
  assert.equal(calls, 1, "a late fallback does not call done again");
});

test("transitionend counts only for opacity or transform", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  el.fire("transitionend", undefined, { propertyName: "color" });
  assert.equal(calls, 0, "a colour transition does not finish the exit");
  el.fire("transitionend", undefined, { propertyName: "opacity" });
  assert.equal(calls, 1, "an opacity transition finishes the exit");

  const other = fakeEl();
  hrLeave(other, { done: () => (calls += 1) });
  other.fire("transitionend", undefined, { propertyName: "transform" });
  assert.equal(calls, 2, "a transform transition finishes the exit");
});

test("hrCollapse removes the element once after the fallback", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const hrCollapse = createCollapse(hrLeave);
  const row = fakeEl();
  hrCollapse(row);
  assert.equal(row.hasAttribute("data-leaving"), true, "the row is marked leaving");
  assert.equal(row.inert, true, "the row is inert while it leaves");
  assert.equal(row.removed, 0, "the row stays until the exit is over");
  env.runTimers();
  assert.equal(row.removed, 1, "the row is removed once after the fallback");
});

test("hrCollapse is idempotent: a second call does not remove again", () => {
  const env = fakeEnv();
  const hrCollapse = createCollapse(createLeave(env));
  const row = fakeEl();
  hrCollapse(row);
  hrCollapse(row);
  env.runTimers();
  assert.equal(row.removed, 1, "the row is removed once");
});

test("hrCollapse removes at once under reduced motion", () => {
  const env = fakeEnv({ reduced: true });
  const hrCollapse = createCollapse(createLeave(env));
  const row = fakeEl();
  hrCollapse(row);
  assert.equal(row.removed, 1, "removed synchronously");
  assert.equal(env.timers.size, 0, "no timer is scheduled");
});

test("hrCollapse ignores a missing element", () => {
  const env = fakeEnv();
  const hrCollapse = createCollapse(createLeave(env));
  assert.doesNotThrow(() => hrCollapse(null));
  assert.equal(env.timers.size, 0, "nothing is scheduled");
});

test("an inherited key such as constructor does not end the exit", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  el.fire("transitionend", undefined, { propertyName: "constructor" });
  el.fire("transitionend", undefined, { propertyName: "toString" });
  assert.equal(calls, 0, "inherited property names are not exit properties");
  assert.equal(env.timers.size, 1, "the fallback is still pending");
});

// Fix round 1 (task 9): a superseded exit must not touch the element. Scenario: exit A starts, the caller cancels it
// (clears data-leaving and inert itself, as cancelExit does) and exit B starts; A's fallback then fires during B.
function runTimerAt(env, index) {
  const id = [...env.timers.keys()][index];
  const t = env.timers.get(id);
  env.timers.delete(id);
  t.fn();
}

test("a superseded exit's fallback does not clear a newer exit's leaving state or call its done", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let aCalls = 0;
  let bCalls = 0;
  hrLeave(el, { done: () => (aCalls += 1) });          // exit A
  el.removeAttribute("data-leaving");                  // the caller cancels A
  el.inert = false;
  hrLeave(el, { done: () => (bCalls += 1) });          // exit B starts
  assert.equal(env.timers.size, 2, "A's fallback and B's fallback are both pending");
  runTimerAt(env, 0);                                  // A's fallback fires during B
  assert.equal(aCalls, 0, "a superseded done is not called");
  assert.equal(bCalls, 0, "B's done is not called early");
  assert.equal(el.hasAttribute("data-leaving"), true, "B's data-leaving survives A's fallback");
  assert.equal(el.inert, true, "B's inert survives A's fallback");
  assert.equal(el.removed, 0, "the element is not removed by A");
  el.fire("animationend");                             // B's own animation ends
  assert.equal(bCalls, 1, "B finishes through its own events");
  assert.equal(aCalls, 0, "A never calls its done");
  assert.equal(el.hasAttribute("data-leaving"), false, "B clears its own leaving state");
  assert.equal(el.inert, false);
});

test("a superseded exit's own animationend does not finish the newer exit early", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let aCalls = 0;
  let bCalls = 0;
  hrLeave(el, { done: () => (aCalls += 1) });          // exit A
  el.removeAttribute("data-leaving");                  // cancelled
  el.inert = false;
  hrLeave(el, { done: () => (bCalls += 1) });          // exit B
  el.fire("animationend");                             // A's listener is still attached: it must do nothing
  assert.equal(aCalls, 0, "A's done is not called");
  assert.equal(bCalls, 1, "the one animationend finishes B");
  assert.equal(env.timers.size, 0, "A's and B's fallback timers are both cleared");
  el.fire("animationend");
  assert.equal(aCalls, 0, "A's done never runs, even on a later event");
  assert.equal(bCalls, 1, "B's done runs once");
});

test("a superseded exit with no newer exit still finishes quietly (its own done, once)", () => {
  const env = fakeEnv();
  const hrLeave = createLeave(env);
  const el = fakeEl();
  let calls = 0;
  hrLeave(el, { done: () => (calls += 1) });
  el.removeAttribute("data-leaving");                  // cancelled, nothing new starts
  el.inert = false;
  runTimerAt(env, 0);
  assert.equal(calls, 1, "without a newer exit the caller's done runs as before");
  assert.equal(el.hasAttribute("data-leaving"), false);
});

// beforeSwap detail for a delete: elt is the SWAP TARGET (the list block) in htmx 2.0.7; the issuing element (the Тийм
// button) is requestConfig.elt. A node here has attributes and a closest() that finds its inline row.
function fakeNode(attrs = [], row = null) {
  return {
    hasAttribute(name) {
      return attrs.includes(name);
    },
    closest(sel) {
      return sel === "[data-inline-row]" ? row : null;
    },
  };
}
function deleteDetail(opts) {
  return {
    elt: opts.elt,
    requestConfig: opts.requestConfig,
    shouldSwap: opts.shouldSwap ?? true,
    isError: opts.isError ?? false,
    serverResponse: opts.serverResponse ?? "<div id=\"list-contact\" data-inline-list></div>",
  };
}

test("deleteRow: elt is the list block, requestConfig.elt is the Тийм button: returns the row", () => {
  const row = fakeNode(["data-inline-row"]);
  const btn = fakeNode(["data-inline-delete"], row);
  const list = fakeNode(["data-inline-list"]);
  assert.equal(deleteRow(deleteDetail({ elt: list, requestConfig: { elt: btn } })), row);
});

test("deleteRow: only elt is the Тийм button (no requestConfig): returns the row", () => {
  const row = fakeNode(["data-inline-row"]);
  const btn = fakeNode(["data-inline-delete"], row);
  assert.equal(deleteRow(deleteDetail({ elt: btn })), row);
});

test("deleteRow: neither element is a delete button: null", () => {
  const row = fakeNode(["data-inline-row"]);
  const other = fakeNode([], row);
  const list = fakeNode(["data-inline-list"]);
  assert.equal(deleteRow(deleteDetail({ elt: list, requestConfig: { elt: other } })), null);
  assert.equal(deleteRow(deleteDetail({ elt: list })), null);
});

test("deleteRow: a failed or unswapped response leaves the row alone", () => {
  const row = fakeNode(["data-inline-row"]);
  const btn = fakeNode(["data-inline-delete"], row);
  assert.equal(deleteRow(deleteDetail({ elt: btn, shouldSwap: false })), null, "shouldSwap false");
  assert.equal(deleteRow(deleteDetail({ elt: btn, isError: true })), null, "isError");
  const open = '<tr data-inline-row class="x"></tr>';
  assert.equal(deleteRow(deleteDetail({ elt: btn, serverResponse: open })), null, "the row came back open");
});

test("deleteRow: a delete button outside any inline row: null", () => {
  const btn = fakeNode(["data-inline-delete"], null);
  assert.equal(deleteRow(deleteDetail({ elt: btn })), null);
});
