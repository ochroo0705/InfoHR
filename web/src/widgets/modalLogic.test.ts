// Port of web/legacy-specs/modal.test.ts (the 13 cases of app/static/js/modal.js helpers) against modalLogic.ts.
// The scenarios are kept. Shells are plain objects instead of DOM nodes; tryClose is async, so its cases await it.
import { describe, expect, it } from "vitest";
import { DIRTY_CONFIRM_MESSAGE, hasServerErrors, pickTopShell, shouldAnimateRemoval, tryClose } from "./modalLogic";

type FakeShell = { name: string; closable: boolean; leaving: boolean; isShell: boolean; noAnim: boolean };

function fake(overrides: Partial<FakeShell> = {}): FakeShell {
  return { name: "shell", closable: true, leaving: false, isShell: true, noAnim: false, ...overrides };
}

describe("pickTopShell", () => {
  it("skips shells that are leaving", () => {
    const below = fake({ name: "below" });
    const top = fake({ name: "top", leaving: true });
    expect(pickTopShell([below, top])).toBe(below);
  });

  it("returns the topmost closable shell that is not leaving", () => {
    const a = fake({ name: "a" });
    const b = fake({ name: "b" });
    expect(pickTopShell([a, b])).toBe(b);
  });

  it("returns null when every shell is leaving", () => {
    expect(pickTopShell([fake({ leaving: true }), fake({ leaving: true })])).toBeNull();
  });

  it("returns null for no shells and skips non-closable ones", () => {
    expect(pickTopShell([])).toBeNull();
    expect(pickTopShell([fake({ closable: false })])).toBeNull();
  });
});

describe("shouldAnimateRemoval", () => {
  it("a pop-up shell is removed through its exit", () => {
    expect(shouldAnimateRemoval(fake(), true)).toBe(true);
  });

  it("a noAnim shell is removed at once", () => {
    expect(shouldAnimateRemoval(fake({ noAnim: true }), true)).toBe(false);
  });

  it("a shell already leaving is removed at once (no second exit)", () => {
    expect(shouldAnimateRemoval(fake({ leaving: true }), true)).toBe(false);
  });

  it("a non-shell element is not intercepted", () => {
    expect(shouldAnimateRemoval(fake({ isShell: false }), true)).toBe(false);
  });

  it("without an exit to play (canLeave false) nothing is intercepted", () => {
    expect(shouldAnimateRemoval(fake(), false)).toBe(false);
  });
});

// A fake pop-up for tryClose: close() counts calls and marks the shell leaving, as the exit does in the browser.
function closingShell({ dirty = false } = {}) {
  const shell = {
    closeCalls: 0,
    dirty,
    leaving: false,
    close() {
      shell.closeCalls += 1;
      shell.leaving = true;
    },
  };
  return shell;
}

describe("tryClose", () => {
  it("a second tryClose on the same shell does not close it again", async () => {
    const shell = closingShell();
    await tryClose(shell, () => true);
    await tryClose(shell, () => true);
    expect(shell.closeCalls).toBe(1);
  });

  it("a dirty shell with a declined confirm is not closed", async () => {
    const shell = closingShell({ dirty: true });
    let asked = 0;
    await tryClose(shell, (message) => {
      asked += 1;
      expect(message).toBe(DIRTY_CONFIRM_MESSAGE);
      return false;
    });
    expect(asked).toBe(1);
    expect(shell.closeCalls).toBe(0);
    expect(shell.leaving).toBe(false);
  });

  it("a dirty shell with an accepted confirm starts its close", async () => {
    const shell = closingShell({ dirty: true });
    await tryClose(shell, () => true);
    expect(shell.closeCalls).toBe(1);
  });

  it("a clean shell is closed without asking", async () => {
    const shell = closingShell();
    let asked = 0;
    await tryClose(shell, () => {
      asked += 1;
      return false;
    });
    expect(asked).toBe(0);
    expect(shell.closeCalls).toBe(1);
  });
});

describe("hasServerErrors", () => {
  it("is false for no errors and for empty lists", () => {
    expect(hasServerErrors(null)).toBe(false);
    expect(hasServerErrors({ field_errors: {}, form_errors: [] })).toBe(false);
    expect(hasServerErrors({ field_errors: { name: [] } })).toBe(false);
  });

  it("is true for a field message or a form message", () => {
    expect(hasServerErrors({ field_errors: { name: ["Заавал бөглөнө"] } })).toBe(true);
    expect(hasServerErrors({ form_errors: ["Алдаа"] })).toBe(true);
  });
});
