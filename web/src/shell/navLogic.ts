// Pure state for the top bar's drop-down menus. Port of the menu rules in app/static/js/nav.js (createCloser, reopen,
// pickOpenMenu), re-shaped as immutable updates so React can hold the state. A menu is "leaving" while its exit plays:
// it stays open until the exit finishes, so the chevron and the summary still show it as open.

export type MenuState = {
  open: boolean;
  leaving: boolean;
  // The token of the exit in flight. finishClose only acts on the exit that carries the same token.
  exit: number | null;
};

export type MenuMap = Record<string, MenuState>;

export const CLOSED: MenuState = { open: false, leaving: false, exit: null };

let exitSeq = 0;

export function menuOf(state: MenuMap, id: string): MenuState {
  return state[id] ?? CLOSED;
}

// Starts a menu's exit. A closed menu does nothing; a menu already leaving is left alone (the exit in flight closes
// it). With animate false (no panel, or no motion) the menu closes at once.
export function closeMenu(state: MenuMap, id: string, opts: { animate?: boolean } = {}): MenuMap {
  const menu = menuOf(state, id);
  if (!menu.open || menu.leaving) return state;
  if (opts.animate === false) return { ...state, [id]: CLOSED };
  exitSeq += 1;
  return { ...state, [id]: { open: true, leaving: true, exit: exitSeq } };
}

// The exit's end: the menu closes only if this exit is still the one in flight. A stale exit (undone by reopen, or
// replaced by a newer exit) does nothing.
export function finishClose(state: MenuMap, id: string, exit: number | null): MenuMap {
  const menu = menuOf(state, id);
  if (exit === null || menu.exit !== exit) return state;
  return { ...state, [id]: CLOSED };
}

// Cancels a menu's exit in flight. A menu that is not leaving is left alone.
export function reopen(state: MenuMap, id: string): MenuMap {
  const menu = menuOf(state, id);
  if (!menu.leaving) return state;
  return { ...state, [id]: { open: true, leaving: false, exit: null } };
}

// Opens one menu and closes every other open menu, so only one is open at a time.
export function openMenu(state: MenuMap, id: string): MenuMap {
  let next = reopen(state, id);
  for (const other of Object.keys(next)) {
    if (other !== id) next = closeMenu(next, other);
  }
  const menu = menuOf(next, id);
  if (menu.open && !menu.leaving) return next;
  return { ...next, [id]: { open: true, leaving: false, exit: null } };
}

export function closeAll(state: MenuMap): MenuMap {
  let next = state;
  for (const id of Object.keys(state)) next = closeMenu(next, id);
  return next;
}

// The menu Escape closes: the first open one that is not leaving. A menu mid-exit is still open, so it is skipped.
export function pickOpenMenu(state: MenuMap): string | null {
  for (const id of Object.keys(state)) {
    const menu = state[id];
    if (menu.open && !menu.leaving) return id;
  }
  return null;
}
