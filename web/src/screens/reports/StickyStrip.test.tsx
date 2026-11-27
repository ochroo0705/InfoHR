import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../api/schema";
import { StickyStrip } from "./StickyStrip";
import { ReportPopUp, ToolRibbon, type OpenPopUp } from "./ToolRibbon";

type ReportHeadOut = components["schemas"]["ReportHeadOut"];

// The pop-ups are stubbed (their own tests cover them): the stub names the pop-up, the query it got, and a close button.
vi.mock("./popups/ColumnsModal", async () => {
  const { createElement } = await import("react");
  return {
    ColumnsModal: (props: { query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "columns", "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/RulesModal", async () => {
  const { createElement } = await import("react");
  return {
    RulesModal: (props: { query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "rules", "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/FormatModal", async () => {
  const { createElement } = await import("react");
  return {
    FormatModal: (props: { query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "format", "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/SavedViewModal", async () => {
  const { createElement } = await import("react");
  return {
    SavedViewModal: (props: { onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "saved" },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});

const TOOLS = { columns: true, rules: true, format: true };

// A DOM rect with only the fields the strip reads.
function rect(top: number, bottom: number): DOMRect {
  return { top, bottom, left: 0, right: 500, width: 500, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
}

// The filter panel as the page draws it (the parent of #report-filters). It is mounted by hand, before the strip, so its
// position can be set first. Its bottom edge is the number the strip reads.
let panel: HTMLElement | null = null;
let panelRect: ReturnType<typeof vi.spyOn>;

function mountPanel(html: string, bottom: number) {
  panel = document.createElement("div");
  panel.innerHTML = html;
  document.body.appendChild(panel);
  panelRect = vi.spyOn(panel, "getBoundingClientRect").mockReturnValue(rect(bottom - 80, bottom));
}

const FILTERS = `
  <form id="report-filters">
    <div data-applied><select><option value="">Бүгд</option><option value="6" selected>Дархан</option></select></div>
    <input name="q" value="тест" data-applied>
  </form>
`;

// requestAnimationFrame is replaced by a queue that the test runs by hand.
let frames: FrameRequestCallback[] = [];
function flushFrames() {
  act(() => {
    const pending = frames;
    frames = [];
    pending.forEach((callback) => callback(0));
  });
}

beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  panel?.remove();
  panel = null;
});

function headFixture(tools: ReportHeadOut["tools"]): ReportHeadOut {
  return {
    excel_url: "",
    layouts: [],
    print_url: "",
    saved: null,
    selectable: false,
    selection_urls: {},
    selection_max: 500,
    staff_actions: false,
    title: "Тест тайлан",
    tools,
  } as ReportHeadOut;
}

describe("StickyStrip", () => {
  it("strip_hidden_until_scrolled_then_shown", () => {
    mountPanel(FILTERS, 300);
    const { container } = render(<StickyStrip tools={TOOLS} />);
    const bar = container.querySelector<HTMLElement>("[data-sticky-strip-bar]")!;
    expect(bar.hidden).toBe(true);

    // The filter panel scrolls under the top bar (its bottom edge goes above the 56px line).
    panelRect.mockReturnValue(rect(-60, 40));
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(bar.hidden).toBe(false);

    // Back up the page: hidden again.
    panelRect.mockReturnValue(rect(100, 300));
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(bar.hidden).toBe(true);
  });

  it("strip_chips_show_applied_filters_and_rules_text", () => {
    mountPanel(
      FILTERS.replace(
        "</form>",
        '<div data-applied><input type="date" value="2026-01-01"><input type="date" value="2026-02-01"></div></form>',
      ) + '<p><span data-rules-text>Төрөл: А</span></p>',
      300,
    );
    const { container, rerender } = render(<StickyStrip tools={TOOLS} />);
    const chips = () => Array.from(container.querySelectorAll("[data-sticky-strip-chips] span")).map((c) => c.textContent);
    expect(chips()).toEqual(["Дархан", "Хайлт: тест", "2026-01-01 – 2026-02-01", "Төрөл: А"]);

    // A change of the filter bar is drawn on the next render of the strip.
    (document.querySelector('input[name="q"]') as HTMLInputElement).value = "";
    rerender(<StickyStrip tools={TOOLS} />);
    expect(chips()).toEqual(["Дархан", "2026-01-01 – 2026-02-01", "Төрөл: А"]);
  });

  it("strip_tool_click_opens_the_same_modal", () => {
    mountPanel(FILTERS, 300);
    // The page's pop-up state, as ReportPage holds it: the ribbon asks, the pop-up shows.
    function Host() {
      const [open, setOpen] = useState<OpenPopUp>(null);
      return (
        <>
          <StickyStrip tools={TOOLS} />
          <ToolRibbon reportKey="staff" head={headFixture(TOOLS)} clearUrl="/reports/staff/?view=plain" onOpen={setOpen} />
          <ReportPopUp
            reportKey="staff"
            open={open}
            query="q=a"
            savedQuery="q=a"
            editPk={null}
            onClose={() => setOpen(null)}
          />
        </>
      );
    }
    const { container } = render(
      <MemoryRouter initialEntries={["/reports/staff/?q=a&offset=40"]}>
        <Host />
      </MemoryRouter>,
    );
    const ribbonRules = container.querySelector<HTMLButtonElement>('button[data-tool="rules"]');
    expect(ribbonRules).not.toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();

    // The strip's button clicks the ribbon's button, so the same pop-up opens, with the same address.
    fireEvent.click(container.querySelector('[data-strip-tool="rules"]')!);
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.getAttribute("data-pop")).toBe("rules");
    expect(dialog?.getAttribute("data-query")).toBe("q=a");

    fireEvent.click(screen.getByText("stub-close"));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("strip_top_scrolls_filter_panel_into_view", () => {
    mountPanel(FILTERS, 300);
    const scrollIntoView = vi.fn();
    panel!.scrollIntoView = scrollIntoView;
    const { container } = render(<StickyStrip tools={TOOLS} />);

    fireEvent.click(container.querySelector("[data-strip-top]")!);
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  });

  it("strip_buttons_follow_head_tools", () => {
    mountPanel(FILTERS, 300);
    const { container } = render(<StickyStrip tools={{ columns: true, rules: false, format: true }} />);
    expect(container.querySelector('[data-strip-tool="columns"]')).not.toBeNull();
    expect(container.querySelector('[data-strip-tool="format"]')).not.toBeNull();
    expect(container.querySelector('[data-strip-tool="rules"]')).toBeNull();
    expect(container.querySelector("[data-strip-top]")).not.toBeNull();
  });

  it("strip_listeners_removed_on_unmount", () => {
    mountPanel(FILTERS, 300);
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(<StickyStrip tools={TOOLS} />);
    const added = addSpy.mock.calls.filter(([type]) => type === "scroll" || type === "resize");
    expect(added.length).toBeGreaterThan(0);

    unmount();
    for (const [type, listener] of added) {
      expect(removeSpy.mock.calls.some(([t, l]) => t === type && l === listener)).toBe(true);
    }
  });

  it("strip_shows_in_non_table_layout_from_the_ribbon", () => {
    // No filter bar in this layout: the tool ribbon (data-sticky-anchor) is measured instead.
    const anchor = document.createElement("div");
    anchor.setAttribute("data-sticky-anchor", "");
    document.body.appendChild(anchor);
    panel = anchor;
    const anchorRect = vi.spyOn(anchor, "getBoundingClientRect").mockReturnValue(rect(200, 300));

    const { container } = render(<StickyStrip tools={TOOLS} />);
    const bar = container.querySelector<HTMLElement>("[data-sticky-strip-bar]")!;
    expect(bar.hidden).toBe(true);

    anchorRect.mockReturnValue(rect(-60, 40));
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(bar.hidden).toBe(false);
    expect(container.querySelectorAll("[data-sticky-strip-chips] span").length).toBe(0);
  });
});
