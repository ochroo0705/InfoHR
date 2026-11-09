// Unit tests for the pure decision helpers of modal.js (pop-up exit, plan 2026-11-08-selection-motion, task 4).
// Run: node --test app/static/js/modal.test.mjs. modal.js is a classic browser script, loaded through require; under
// Node it exports its helpers only. The helpers take duck-typed elements, so plain objects stand in for DOM nodes.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { pickTopShell, shouldAnimateRemoval, tryClose } = require("./modal.js");

// A fake element: shell = a `.fixed.inset-0.z-50` pop-up; leaving = has data-leaving; classes = its class names.
function fake({ shell = true, leaving = false, classes = [], closable = true, name = "shell" } = {}) {
  return {
    name,
    closable,
    matches(sel) {
      return shell && sel === ".fixed.inset-0.z-50";
    },
    hasAttribute(attr) {
      return attr === "data-leaving" && leaving;
    },
    classList: {
      contains(c) {
        return classes.indexOf(c) >= 0;
      },
    },
  };
}

const isClosable = (el) => el.closable;

test("pickTopShell skips shells that are leaving", () => {
  const below = fake({ name: "below" });
  const top = fake({ name: "top", leaving: true });
  assert.equal(pickTopShell([below, top], isClosable), below);
});

test("pickTopShell returns the topmost closable shell that is not leaving", () => {
  const a = fake({ name: "a" });
  const b = fake({ name: "b" });
  assert.equal(pickTopShell([a, b], isClosable), b);
});

test("pickTopShell returns null when every shell is leaving", () => {
  const a = fake({ leaving: true });
  const b = fake({ leaving: true });
  assert.equal(pickTopShell([a, b], isClosable), null);
});

test("pickTopShell returns null for no shells and skips non-closable ones", () => {
  assert.equal(pickTopShell([], isClosable), null);
  assert.equal(pickTopShell([fake({ closable: false })], isClosable), null);
});

test("a pop-up shell is removed through its exit", () => {
  assert.equal(shouldAnimateRemoval(fake(), true), true);
});

test("a no-anim shell is removed at once", () => {
  assert.equal(shouldAnimateRemoval(fake({ classes: ["no-anim"] }), true), false);
});

test("a shell already leaving is removed at once (no second exit)", () => {
  assert.equal(shouldAnimateRemoval(fake({ leaving: true }), true), false);
});

test("a non-shell element is not intercepted", () => {
  assert.equal(shouldAnimateRemoval(fake({ shell: false }), true), false);
});

test("without window.hrLeave nothing is intercepted", () => {
  assert.equal(shouldAnimateRemoval(fake(), false), false);
});

// A fake pop-up shell for tryClose: its remove() counts calls and marks it leaving, as hrLeave does in the browser.
function closingShell({ dirty = false } = {}) {
  const shell = {
    removeCalls: 0,
    dataset: dirty ? { dirty: "1" } : {},
    hasAttribute(attr) {
      return attr === "data-leaving" && shell.leaving === true;
    },
    remove() {
      shell.removeCalls += 1;
      shell.leaving = true;
    },
    leaving: false,
  };
  return shell;
}

test("a second tryClose on the same shell does not remove it again", () => {
  const shell = closingShell();
  tryClose(shell, () => true);
  tryClose(shell, () => true);
  assert.equal(shell.removeCalls, 1);
});

test("a dirty shell with a declined confirm is not closed", () => {
  const shell = closingShell({ dirty: true });
  let asked = 0;
  tryClose(shell, () => {
    asked += 1;
    return false;
  });
  assert.equal(asked, 1);
  assert.equal(shell.removeCalls, 0);
  assert.equal(shell.leaving, false);
});

test("a dirty shell with an accepted confirm starts its removal", () => {
  const shell = closingShell({ dirty: true });
  tryClose(shell, () => true);
  assert.equal(shell.removeCalls, 1);
});

test("a clean shell is closed without asking", () => {
  const shell = closingShell();
  let asked = 0;
  tryClose(shell, () => {
    asked += 1;
    return false;
  });
  assert.equal(asked, 0);
  assert.equal(shell.removeCalls, 1);
});
