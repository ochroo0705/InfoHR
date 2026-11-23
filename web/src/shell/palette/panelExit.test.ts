// Port of the exit-state cases of app/static/js/palette_panel.test.mjs against panelExit.ts. Case names are kept. The two
// workspaceFormPlan cases are not ported here: that form belongs to step 6.
import { describe, expect, it } from "vitest";
import { cancelExit, isPanelOpen, startExit, type ExitElement, type LeaveFn } from "./panelExit";

// A plain-object panel with the attribute set the original test uses.
function makePanel(hidden: boolean): ExitElement {
  const attrs = new Set<string>();
  return {
    hidden,
    inert: false,
    hasAttribute: (name: string) => attrs.has(name),
    setAttribute: (name: string) => {
      attrs.add(name);
    },
    removeAttribute: (name: string) => {
      attrs.delete(name);
    },
  };
}

// The fake hrLeave does what the real one does to the element (data-leaving + inert) and records each call. It calls done
// only when the test says the exit has ended.
function fakeLeave() {
  const calls: { el: ExitElement; opts: { done: () => void } }[] = [];
  const fn: LeaveFn = (el, opts) => {
    calls.push({ el, opts });
    if (el.hasAttribute("data-leaving")) return;
    el.setAttribute("data-leaving");
    el.inert = true;
  };
  return { fn, calls };
}

describe("panelExit", () => {
  it("a visible panel that is not leaving is open; hidden or leaving is not", () => {
    const panel = makePanel(false);
    expect(isPanelOpen(panel)).toBe(true);
    panel.setAttribute("data-leaving");
    expect(isPanelOpen(panel)).toBe(false); // a leaving panel is not open from the moment its exit starts
    expect(isPanelOpen(makePanel(true))).toBe(false);
  });

  it("closing starts the exit: the panel is no longer open but stays visible until the exit ends", () => {
    const panel = makePanel(false);
    const { fn, calls } = fakeLeave();
    let hides = 0;
    startExit(panel, fn, () => {
      hides += 1;
      panel.hidden = true;
    });
    expect(calls.length).toBe(1);
    expect(calls[0].el).toBe(panel);
    expect(isPanelOpen(panel)).toBe(false);
    expect(panel.hidden).toBe(false); // hidden is delayed until the slide-out ends
    expect(hides).toBe(0);
    calls[0].opts.done();
    expect(hides).toBe(1);
    expect(panel.hidden).toBe(true);
    expect(panel.hasAttribute("data-leaving")).toBe(false);
    expect(panel.inert).toBe(false);
  });

  it("open, close, open quickly: the panel ends visible, not leaving, and open", () => {
    const panel = makePanel(false);
    const { fn, calls } = fakeLeave();
    startExit(panel, fn, () => {
      panel.hidden = true;
    }); // close
    cancelExit(panel); // open again before the exit ends
    expect(isPanelOpen(panel)).toBe(true);
    calls[0].opts.done(); // the exit that was cancelled ends now
    expect(panel.hidden).toBe(false); // the stale done must not hide the reopened panel
    expect(panel.hasAttribute("data-leaving")).toBe(false);
    expect(panel.inert).toBe(false);
    expect(isPanelOpen(panel)).toBe(true);
  });

  it("close, reopen, close again: only the newest exit hides the panel", () => {
    const panel = makePanel(false);
    const { fn, calls } = fakeLeave();
    const hide = () => {
      panel.hidden = true;
    };
    startExit(panel, fn, hide); // exit 1
    cancelExit(panel); // reopened
    startExit(panel, fn, hide); // exit 2, in flight
    calls[0].opts.done(); // stale done of exit 1
    expect(panel.hidden).toBe(false); // exit 2 is still in flight
    expect(panel.hasAttribute("data-leaving")).toBe(true);
    calls[1].opts.done(); // exit 2 ends
    expect(panel.hidden).toBe(true);
    expect(panel.hasAttribute("data-leaving")).toBe(false);
  });

  it("without hrLeave the panel is hidden at once", () => {
    const panel = makePanel(false);
    let hides = 0;
    startExit(panel, undefined, () => {
      hides += 1;
      panel.hidden = true;
    });
    expect(hides).toBe(1);
    expect(panel.hidden).toBe(true);
    expect(panel.hasAttribute("data-leaving")).toBe(false);
  });
});
