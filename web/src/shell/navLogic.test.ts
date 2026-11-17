import { describe, expect, it } from "vitest";
import {
  closeAll,
  closeMenu,
  finishClose,
  menuOf,
  openMenu,
  pickOpenMenu,
  reopen,
  type MenuMap,
} from "./navLogic";

// The ten cases of web/legacy-specs/nav.test.ts, against the React-shaped state.

const OPEN: MenuMap = { a: { open: true, leaving: false, exit: null } };

describe("navLogic (port of nav.js)", () => {
  it("an open menu leaves once, and finishing the exit closes it", () => {
    const left = closeMenu(OPEN, "a");
    expect(menuOf(left, "a").leaving).toBe(true);
    expect(menuOf(left, "a").open).toBe(true);
    const token = menuOf(left, "a").exit;

    const done = finishClose(left, "a", token);
    expect(menuOf(done, "a")).toEqual({ open: false, leaving: false, exit: null });
  });

  it("a closed menu does nothing", () => {
    const state: MenuMap = {};
    expect(closeMenu(state, "a")).toBe(state);
  });

  it("a second close while the menu is leaving changes nothing", () => {
    const left = closeMenu(OPEN, "a");
    const again = closeMenu(left, "a");
    expect(again).toBe(left);
    expect(menuOf(again, "a").exit).toBe(menuOf(left, "a").exit);
  });

  it("with animate off the menu closes at once", () => {
    const closed = closeMenu(OPEN, "a", { animate: false });
    expect(menuOf(closed, "a")).toEqual({ open: false, leaving: false, exit: null });
  });

  it("a menu with no panel closes at once (animate off)", () => {
    const closed = closeMenu({ b: { open: true, leaving: false, exit: null } }, "b", { animate: false });
    expect(menuOf(closed, "b").open).toBe(false);
  });

  it("close, reopen, then the pending finish leaves the menu open", () => {
    const left = closeMenu(OPEN, "a");
    const token = menuOf(left, "a").exit;
    const back = reopen(left, "a");
    expect(menuOf(back, "a")).toEqual({ open: true, leaving: false, exit: null });
    const after = finishClose(back, "a", token);
    expect(menuOf(after, "a").open).toBe(true);
  });

  it("reopen on a menu that is not leaving is a no-op", () => {
    expect(reopen(OPEN, "a")).toBe(OPEN);
  });

  it("a stale finish from an older exit does not close a menu in a newer exit", () => {
    const first = closeMenu(OPEN, "a");
    const staleToken = menuOf(first, "a").exit;
    const reopened = reopen(first, "a");
    const second = closeMenu(reopened, "a");
    const freshToken = menuOf(second, "a").exit;
    expect(freshToken).not.toBe(staleToken);

    const afterStale = finishClose(second, "a", staleToken);
    expect(menuOf(afterStale, "a").leaving).toBe(true);

    const afterFresh = finishClose(second, "a", freshToken);
    expect(menuOf(afterFresh, "a").open).toBe(false);
  });

  it("pickOpenMenu skips a leaving menu and returns the really open one", () => {
    const state: MenuMap = {
      a: { open: true, leaving: true, exit: 1 },
      b: { open: true, leaving: false, exit: null },
    };
    expect(pickOpenMenu(state)).toBe("b");
  });

  it("pickOpenMenu returns null when every open menu is leaving or closed", () => {
    const state: MenuMap = {
      a: { open: true, leaving: true, exit: 1 },
      b: { open: false, leaving: false, exit: null },
    };
    expect(pickOpenMenu(state)).toBeNull();
  });

  it("openMenu closes the other open menu", () => {
    const state = openMenu(OPEN, "b");
    expect(menuOf(state, "b").open).toBe(true);
    expect(menuOf(state, "a").leaving).toBe(true);
  });

  it("closeAll starts the exit of every open menu", () => {
    const state = closeAll({ a: { open: true, leaving: false, exit: null }, b: { open: false, leaving: false, exit: null } });
    expect(menuOf(state, "a").leaving).toBe(true);
    expect(menuOf(state, "b").open).toBe(false);
  });
});
