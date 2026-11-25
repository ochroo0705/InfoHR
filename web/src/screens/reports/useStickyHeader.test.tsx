import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRef } from "react";
import { MemoryRouter, useLocation } from "react-router";
import type { ReportHeadCellOut } from "../../api/reports";
import { HeaderRow } from "./HeaderRow";
import { useStickyHeader } from "./useStickyHeader";

// A table in a .ptable box, as ReportTable draws it: the real header is HeaderRow (so its links and Shift handling are the
// real ones). The geometry is set by hand (jsdom has no layout).
const HEADS: ReportHeadCellOut[] = [
  {
    label: "Нэр",
    href: "/reports/staff/?sort=name",
    append_href: "/reports/staff/?sort=name,-number",
    arrow: "",
    css: "",
    sticky_left: "",
  },
  {
    label: "Тоо",
    href: "/reports/staff/?sort=number",
    append_href: "/reports/staff/?sort=number,-name",
    arrow: "",
    css: "",
    sticky_left: "",
  },
];

function Harness({ resetKey, disabled = false }: { resetKey: string; disabled?: boolean }) {
  const ref = useRef<HTMLTableElement>(null);
  useStickyHeader(ref, resetKey, disabled);
  return (
    <div className="ptable">
      <table ref={ref}>
        <thead>
          <HeaderRow heads={HEADS} />
        </thead>
        <tbody>
          <tr>
            <td>Бат</td>
            <td>1</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// Shows the router's address, so a test can read where a click went.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function rect(top: number, bottom: number, left = 0, width = 500): DOMRect {
  return { top, bottom, left, right: left + width, width, height: bottom - top, x: left, y: top, toJSON: () => ({}) } as DOMRect;
}

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
  document.querySelectorAll("[data-sticky-head]").forEach((node) => node.remove());
});

// Mounts the harness and sets the geometry: the box runs from `boxTop` to `boxBottom`, the header is 40px high.
// `before` runs after mount and before the first measurement (for widths set on the real header cells).
function mountTable(
  boxTop: number,
  boxBottom: number,
  options: { before?: (container: HTMLElement) => void; disabled?: boolean; resetKey?: string } = {},
) {
  const view = render(
    <MemoryRouter initialEntries={["/reports/staff/"]}>
      <Harness resetKey={options.resetKey ?? "a"} disabled={options.disabled ?? false} />
      <Probe />
    </MemoryRouter>,
  );
  const box = view.container.querySelector<HTMLElement>(".ptable")!;
  const head = view.container.querySelector<HTMLElement>("thead")!;
  options.before?.(view.container);
  const boxRect = vi.spyOn(box, "getBoundingClientRect").mockReturnValue(rect(boxTop, boxBottom));
  vi.spyOn(head, "getBoundingClientRect").mockReturnValue(rect(boxTop, boxTop + 40));
  flushFrames();
  return { ...view, box, boxRect };
}

const where = () => document.querySelector('[data-testid="loc"]')?.textContent ?? "";

describe("useStickyHeader", () => {
  it("sticky_header_clone_shown_when_header_above_line_and_dropped_when_not", () => {
    const { boxRect } = mountTable(-200, 800);
    const clone = document.querySelector<HTMLElement>("[data-sticky-head]");
    expect(clone).not.toBeNull();
    expect(clone!.style.top).toBe("56px");
    expect(clone!.style.position).toBe("fixed");
    expect(clone!.textContent).toContain("Нэр");

    // The header is back under the top bar's line: the copy goes.
    boxRect.mockReturnValue(rect(100, 800));
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(document.querySelector("[data-sticky-head]")).toBeNull();

    // The header is above the line but the table has no body rows under it: no copy.
    boxRect.mockReturnValue(rect(-200, 80));
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(document.querySelector("[data-sticky-head]")).toBeNull();
  });

  it("sticky_header_clone_removed_on_unmount", () => {
    const { unmount } = mountTable(-200, 800);
    expect(document.querySelector("[data-sticky-head]")).not.toBeNull();

    unmount();
    expect(document.querySelector("[data-sticky-head]")).toBeNull();
  });

  it("sticky_header_copy_plain_click_reaches_sort_path", () => {
    mountTable(-200, 800);
    const copyLink = document.querySelector<HTMLAnchorElement>("[data-sticky-head] a")!;
    fireEvent.click(copyLink);
    expect(where()).toBe("/reports/staff/?sort=name");
  });

  it("sticky_header_copy_shift_click_reaches_append_path", () => {
    mountTable(-200, 800);
    const copyLink = document.querySelector<HTMLAnchorElement>("[data-sticky-head] a")!;
    fireEvent.click(copyLink, { shiftKey: true });
    expect(where()).toBe("/reports/staff/?sort=name,-number");
  });

  it("sticky_header_copy_follows_sideways_scroll", () => {
    const { box } = mountTable(-200, 800);
    const clone = document.querySelector<HTMLElement>("[data-sticky-head]")!;
    Object.defineProperty(box, "scrollLeft", { value: 40, configurable: true });
    fireEvent.scroll(box);
    expect(clone.scrollLeft).toBe(40);
  });

  it("sticky_header_copy_resize_drops_and_remeasures", () => {
    const { boxRect } = mountTable(-200, 800);
    const first = document.querySelector("[data-sticky-head]");
    expect(first).not.toBeNull();

    // Still above the line after a resize: the copy is measured again (a new node).
    window.dispatchEvent(new Event("resize"));
    flushFrames();
    const second = document.querySelector("[data-sticky-head]");
    expect(second).not.toBeNull();
    expect(second).not.toBe(first);

    // Out of view by the time the resize is measured: no copy.
    boxRect.mockReturnValue(rect(100, 800));
    window.dispatchEvent(new Event("resize"));
    flushFrames();
    expect(document.querySelector("[data-sticky-head]")).toBeNull();
  });

  it("sticky_header_copy_takes_the_real_cell_widths", () => {
    mountTable(-200, 800, {
      before: (container) => {
        const cells = container.querySelectorAll("thead th");
        vi.spyOn(cells[0], "getBoundingClientRect").mockReturnValue(rect(0, 40, 0, 120));
        vi.spyOn(cells[1], "getBoundingClientRect").mockReturnValue(rect(0, 40, 120, 80));
      },
    });
    const cells = document.querySelectorAll<HTMLElement>("[data-sticky-head] th");
    expect(cells[0].style.width).toBe("120px");
    expect(cells[1].style.width).toBe("80px");
  });

  it("sticky_header_copy_not_drawn_while_disabled", () => {
    const { rerender } = mountTable(-200, 800);
    expect(document.querySelector("[data-sticky-head]")).not.toBeNull();

    // The table turns inert (a new address loads): the copy goes and is not drawn again.
    rerender(
      <MemoryRouter initialEntries={["/reports/staff/"]}>
        <Harness resetKey="a" disabled />
        <Probe />
      </MemoryRouter>,
    );
    expect(document.querySelector("[data-sticky-head]")).toBeNull();
    window.dispatchEvent(new Event("scroll"));
    flushFrames();
    expect(document.querySelector("[data-sticky-head]")).toBeNull();
  });
});
