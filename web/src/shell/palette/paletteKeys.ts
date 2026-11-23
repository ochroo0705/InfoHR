// Keyboard rules of the palette. Port of the keydown handler in app/static/js/palette.js: the Ctrl/Cmd+K shortcut, the
// arrow steps through the results (they wrap at both ends), what Escape does to the box, and which keys the panel leaves
// alone. Pure: no DOM, no React.

// Ctrl+K (or Cmd+K) opens and closes the panel. e.code is read, not e.key: on a Cyrillic layout the key that gives K
// reports e.key as "к". As in palette.js, an AltGr combination (altKey) is not the shortcut; Shift is not checked, so
// Ctrl+Shift+K opens the panel too.
export function isOpenShortcut(e: { code: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; repeat?: boolean }): boolean {
  return e.code === "KeyK" && (e.ctrlKey || e.metaKey) && !e.altKey;
}

// Keys the panel must not act on. An IME composition belongs to the input method (isComposing, or keyCode 229). For the
// open shortcut, a repeated keydown (the keys held down) is ignored too, so holding them does not flicker the panel.
//
// Order in the Ctrl+K handler (palette.js, capture-phase keydown): first the shortcut check. A Ctrl+K keydown calls
// preventDefault and stopPropagation, and only then, when e.repeat is set, returns without toggling. So a held Ctrl+K is
// swallowed but never reaches the panel or the page. The IME check comes after the shortcut check, for the other keys.
// Task 16 (the React keydown handler) follows this order.
export function shouldIgnoreKey(
  e: { isComposing?: boolean; keyCode?: number; repeat?: boolean },
  forShortcut: boolean
): boolean {
  if (e.isComposing === true || e.keyCode === 229) return true;
  return forShortcut && e.repeat === true;
}

// The index of the next result. `current` is -1 when nothing is highlighted: a step down then picks the first result, a
// step up the last. Otherwise the step wraps at both ends. An empty list gives -1.
export function nextIndex(current: number, step: 1 | -1, count: number): number {
  if (count <= 0) return -1;
  if (current < 0) return step > 0 ? 0 : count - 1;
  return (current + step + count) % count;
}

// Escape first clears a typed query; with an empty box it closes the panel.
export function escapeAction(boxText: string): "clear" | "close" {
  return boxText !== "" ? "clear" : "close";
}
