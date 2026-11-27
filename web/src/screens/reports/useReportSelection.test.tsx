import { act, cleanup, fireEvent, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SelState } from "./selectionState";
import { useReportSelection } from "./useReportSelection";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function setup(initialKey = "/reports/staff/?state=all") {
  return renderHook(({ k }: { k: string }) => useReportSelection(k), { initialProps: { k: initialKey } });
}

describe("useReportSelection", () => {
  it("starts with nothing picked and the mode off", () => {
    const { result } = setup();
    expect(result.current.state.ids.size).toBe(0);
    expect(result.current.state.all).toBe(false);
    expect(result.current.state.held).toBe(false);
  });

  it("resets the selection when resetKey changes", () => {
    const { result, rerender } = setup("/reports/staff/?state=all");
    act(() => {
      result.current.setVisibleIds(["1", "2"]);
      result.current.toggle();
      result.current.pickRow("1", true);
    });
    expect(result.current.state.ids.size).toBe(1);
    expect(result.current.state.held).toBe(true);

    rerender({ k: "/reports/staff/?state=active" });
    expect(result.current.state.ids.size).toBe(0);
    expect(result.current.state.held).toBe(false);
  });

  it("a render with a new key never shows the old picks", () => {
    // Every render of the hook records the state it returned, including renders React discards.
    const seen: SelState[] = [];
    const { result, rerender } = renderHook(
      ({ k }: { k: string }) => {
        const r = useReportSelection(k);
        seen.push(r.state);
        return r;
      },
      { initialProps: { k: "/reports/staff/?state=all" } },
    );
    act(() => {
      result.current.setVisibleIds(["1"]);
      result.current.pickRow("1", true);
    });
    expect(result.current.state.ids.size).toBe(1);

    const before = seen.length;
    rerender({ k: "/reports/staff/?state=active" });
    const afterChange = seen.slice(before);
    expect(afterChange.length).toBeGreaterThan(0);
    for (const s of afterChange) expect(s.ids.size).toBe(0);
    expect(result.current.state.ids.size).toBe(0);
  });

  it("after unmount, Escape neither reaches the hook nor leaves its listener behind", () => {
    const added = vi.spyOn(document, "addEventListener");
    const removed = vi.spyOn(document, "removeEventListener");
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result, unmount } = setup();
    act(() => result.current.pickRow("1", true));

    const keydownAdds = added.mock.calls.filter(([type]) => type === "keydown");
    expect(keydownAdds.length).toBe(1);
    const handler = keydownAdds[0][1];

    unmount();
    const keydownRemoves = removed.mock.calls.filter(([type]) => type === "keydown");
    expect(keydownRemoves.map(([, fn]) => fn)).toContain(handler);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(errors).not.toHaveBeenCalled();
    added.mockRestore();
    removed.mockRestore();
    errors.mockRestore();
  });

  it("keeps the selection when resetKey stays the same", () => {
    const { result, rerender } = setup("/reports/staff/");
    act(() => result.current.pickRow("4", true));
    rerender({ k: "/reports/staff/" });
    expect([...result.current.state.ids]).toEqual(["4"]);
  });

  it("Escape ends the mode and clears the picks", () => {
    const { result } = setup();
    act(() => {
      result.current.setVisibleIds(["1", "2"]);
      result.current.pickRow("1", true);
    });
    expect(result.current.state.ids.size).toBe(1);
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(result.current.state.ids.size).toBe(0);
    expect(result.current.state.held).toBe(false);
    expect(result.current.state.all).toBe(false);
  });

  it("Escape with the mode off changes nothing", () => {
    const { result } = setup();
    const before = result.current.state;
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(result.current.state).toBe(before);
  });

  it("Escape with an open pop-up does nothing", () => {
    const { result } = setup();
    const popup = document.createElement("div");
    popup.className = "fixed inset-0 z-50";
    document.body.appendChild(popup);
    act(() => result.current.pickRow("1", true));
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect([...result.current.state.ids]).toEqual(["1"]);
  });

  it("Escape with a pop-up that is leaving does not count as open", () => {
    const { result } = setup();
    const popup = document.createElement("div");
    popup.className = "fixed inset-0 z-50";
    popup.setAttribute("data-leaving", "");
    document.body.appendChild(popup);
    act(() => result.current.pickRow("1", true));
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(result.current.state.ids.size).toBe(0);
  });

  it("Escape that was already defaultPrevented does nothing", () => {
    // A listener registered before the hook's, as a dropdown or a calendar would be, handles Escape first.
    const earlier = (e: KeyboardEvent) => {
      if (e.key === "Escape") e.preventDefault();
    };
    document.addEventListener("keydown", earlier);
    const { result } = setup();
    act(() => result.current.pickRow("1", true));
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    document.removeEventListener("keydown", earlier);
    expect([...result.current.state.ids]).toEqual(["1"]);
  });

  it("other keys do nothing", () => {
    const { result } = setup();
    act(() => result.current.pickRow("1", true));
    act(() => {
      fireEvent.keyDown(document, { key: "Enter" });
    });
    expect([...result.current.state.ids]).toEqual(["1"]);
  });

  it("unticking in all-mode keeps the visible rows picked minus that one", () => {
    const { result } = setup();
    act(() => {
      result.current.setVisibleIds(["1", "2", "3"]);
      result.current.pickAll();
    });
    expect(result.current.state.all).toBe(true);
    act(() => result.current.pickRow("2", false));
    expect(result.current.state.all).toBe(false);
    expect([...result.current.state.ids].sort()).toEqual(["1", "3"]);
  });

  it("the header box picks and clears the rows on screen", () => {
    const { result } = setup();
    act(() => {
      result.current.setVisibleIds(["5", "x", "6"]);
      result.current.pickVisible(true);
    });
    expect([...result.current.state.ids]).toEqual(["5", "6"]);
    act(() => result.current.pickVisible(false));
    expect(result.current.state.ids.size).toBe(0);
    expect(result.current.state.held).toBe(false);
  });

  it("cancel ends the mode", () => {
    const { result } = setup();
    act(() => {
      result.current.toggle();
      result.current.pickRow("9", true);
    });
    act(() => result.current.cancel());
    expect(result.current.state.held).toBe(false);
    expect(result.current.state.ids.size).toBe(0);
  });

  it("body sends all and no ids in all-mode", () => {
    const { result } = setup();
    act(() => {
      result.current.setVisibleIds(["1", "2"]);
      result.current.pickRow("1", true);
      result.current.pickAll();
    });
    expect(result.current.body("state=all")).toEqual({ query: "state=all", ids: [], all: true });
  });

  it("body sends the picked person ids otherwise", () => {
    const { result } = setup();
    act(() => {
      result.current.setVisibleIds(["1", "2"]);
      result.current.pickRow("2", true);
      result.current.pickRow("1", true);
    });
    expect(result.current.body("state=all")).toEqual({ query: "state=all", ids: ["2", "1"], all: false });
  });
});
