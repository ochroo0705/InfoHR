// activateRow: what a chosen palette row does. Every dependency is a spy, so the order of the close, the navigation and
// the pop-up open is checked by the call order.
import { describe, expect, it, vi } from "vitest";
import type { PaletteOpenOut, PaletteRowOut } from "../../api/palette";
import { activateRow, type ActivateDeps } from "./activate";

function rowWith(open: PaletteOpenOut | null): PaletteRowOut {
  return {
    code: [],
    day: "",
    initials: "",
    kind: "page",
    key: "k",
    left: false,
    lines: [],
    open,
    ref: null,
    title: [{ text: "Мөр", hit: false }],
  };
}

function pageOpen(path: string): PaletteOpenOut {
  return { employee: null, event_type: null, kind: "page", order: null, path, popup: null, year: null };
}

function makeDeps() {
  const calls: string[] = [];
  const deps: ActivateDeps = {
    closePanel: vi.fn((restoreFocus: boolean) => calls.push(`close(${restoreFocus})`)),
    goPorted: vi.fn((to: string) => calls.push(`goPorted(${to})`)),
    legacy: vi.fn((path: string) => calls.push(`legacy(${path})`)),
    popups: { open: vi.fn((target: PaletteOpenOut) => calls.push(`popup(${target.popup})`)) },
  };
  return { deps, calls };
}

describe("activateRow", () => {
  it("a ported page row closes the panel without restoring focus, then navigates client-side", () => {
    const { deps, calls } = makeDeps();
    activateRow(rowWith(pageOpen("/employees/today/")), deps);
    expect(calls).toEqual(["close(false)", "goPorted(/employees/today/)"]);
    expect(deps.legacy).not.toHaveBeenCalled();
  });

  it("a page row that the Django site still serves is a full page load", () => {
    const { deps, calls } = makeDeps();
    activateRow(rowWith(pageOpen("/employees/leave/")), deps);
    expect(calls).toEqual(["close(false)", "legacy(/employees/leave/)"]);
    expect(deps.goPorted).not.toHaveBeenCalled();
  });

  it("a page row with a path that is not a same-site path only closes the panel", () => {
    const { deps, calls } = makeDeps();
    activateRow(rowWith(pageOpen("https://example.com/")), deps);
    expect(calls).toEqual(["close(false)"]);
  });

  it("a pop-up row closes the panel with focus restored, then opens its pop-up with the row's target", () => {
    const { deps, calls } = makeDeps();
    const open: PaletteOpenOut = {
      employee: 3,
      event_type: null,
      kind: "popup",
      order: 7,
      path: "/employees/3/",
      popup: "order_detail",
      year: null,
    };
    activateRow(rowWith(open), deps);
    expect(calls).toEqual(["close(true)", "popup(order_detail)"]);
    expect(deps.popups.open).toHaveBeenCalledWith(open);
    expect(deps.goPorted).not.toHaveBeenCalled();
    expect(deps.legacy).not.toHaveBeenCalled();
  });

  it("a row with no open target does nothing at all, not even closing the panel", () => {
    const { deps, calls } = makeDeps();
    activateRow(rowWith(null), deps);
    expect(calls).toEqual([]);
    expect(deps.closePanel).not.toHaveBeenCalled();
    expect(deps.legacy).not.toHaveBeenCalled();
    expect(deps.goPorted).not.toHaveBeenCalled();
  });

  it("an unknown kind closes the panel and nothing else", () => {
    const { deps, calls } = makeDeps();
    const open = { ...pageOpen("/employees/today/"), kind: "mystery" } as unknown as PaletteOpenOut;
    activateRow(rowWith(open), deps);
    expect(calls).toEqual(["close(false)"]);
    expect(deps.popups.open).not.toHaveBeenCalled();
  });

});
