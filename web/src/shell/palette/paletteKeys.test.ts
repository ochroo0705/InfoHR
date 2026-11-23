// Keyboard rules of the palette (palette.js keydown handler): Ctrl/Cmd+K, the arrows and Escape.
import { describe, expect, it } from "vitest";
import { escapeAction, isOpenShortcut, nextIndex, shouldIgnoreKey } from "./paletteKeys";

type KeyInit = { code: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean };

const key = (over: Partial<KeyInit> = {}): KeyInit => ({
  code: "KeyK",
  ctrlKey: true,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...over,
});

describe("isOpenShortcut", () => {
  it("matches Ctrl+K and Cmd+K", () => {
    expect(isOpenShortcut(key())).toBe(true);
    expect(isOpenShortcut(key({ ctrlKey: false, metaKey: true }))).toBe(true);
  });

  it("test_isOpenShortcut_matches_cyrillic_layout", () => {
    // On a Cyrillic layout the key that gives K reports e.key as "к"; only e.code is looked at, so the key is irrelevant.
    const cyrillic = { code: "KeyK", key: "к", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false };
    expect(isOpenShortcut(cyrillic)).toBe(true);
  });

  it("test_isOpenShortcut_accepts_shift_rejects_alt", () => {
    // Alt (AltGr) is rejected; Shift is not, as in palette.js, so Ctrl+Shift+K opens the panel too.
    expect(isOpenShortcut(key({ altKey: true }))).toBe(false);
    expect(isOpenShortcut(key({ shiftKey: true }))).toBe(true);
  });

  it("shouldIgnoreKey: an IME composition is ignored for every key", () => {
    expect(shouldIgnoreKey({ isComposing: true }, false)).toBe(true);
    expect(shouldIgnoreKey({ keyCode: 229 }, false)).toBe(true);
    expect(shouldIgnoreKey({ isComposing: true }, true)).toBe(true);
    expect(shouldIgnoreKey({ keyCode: 13 }, false)).toBe(false);
  });

  it("shouldIgnoreKey: a repeated keydown is ignored for the open shortcut only", () => {
    expect(shouldIgnoreKey({ repeat: true }, true)).toBe(true);
    expect(shouldIgnoreKey({ repeat: true }, false)).toBe(false);
    expect(shouldIgnoreKey({ repeat: false }, true)).toBe(false);
  });

  it("needs Ctrl or Cmd and the K key", () => {
    expect(isOpenShortcut(key({ ctrlKey: false }))).toBe(false);
    expect(isOpenShortcut(key({ code: "KeyJ" }))).toBe(false);
  });
});

describe("nextIndex", () => {
  it("steps forward and back inside the list", () => {
    expect(nextIndex(0, 1, 3)).toBe(1);
    expect(nextIndex(2, -1, 3)).toBe(1);
  });

  it("wraps at both ends", () => {
    expect(nextIndex(2, 1, 3)).toBe(0);
    expect(nextIndex(0, -1, 3)).toBe(2);
  });

  it("with nothing highlighted, down picks the first and up picks the last", () => {
    expect(nextIndex(-1, 1, 3)).toBe(0);
    expect(nextIndex(-1, -1, 3)).toBe(2);
  });

  it("an empty list gives -1", () => {
    expect(nextIndex(-1, 1, 0)).toBe(-1);
    expect(nextIndex(0, -1, 0)).toBe(-1);
  });
});

describe("escapeAction", () => {
  it("a typed query is cleared first", () => {
    expect(escapeAction("санхүү")).toBe("clear");
    expect(escapeAction(" ")).toBe("clear");
  });

  it("an empty box closes the panel", () => {
    expect(escapeAction("")).toBe("close");
  });
});
