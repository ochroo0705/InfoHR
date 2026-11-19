import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";
import { PageScrollbar, ScrollFloat, ScrollHost } from "./Scrollbar";

// jsdom has no layout, so the sizes the rails read are stubbed on each element instance.
function stubSizes(
  el: HTMLElement,
  sizes: Partial<Record<"clientWidth" | "clientHeight" | "scrollWidth" | "scrollHeight", number>>,
) {
  for (const [key, value] of Object.entries(sizes)) {
    Object.defineProperty(el, key, { configurable: true, value });
  }
  Object.defineProperty(el, "scrollTop", { configurable: true, writable: true, value: 0 });
  Object.defineProperty(el, "scrollLeft", { configurable: true, writable: true, value: 0 });
}

// A getBoundingClientRect stub that puts the element at the top left corner.
function rectOf(width: number, height: number) {
  return () => ({ left: 0, top: 0, right: width, bottom: height, width, height, x: 0, y: 0, toJSON: () => ({}) });
}

function thumbOf(rail: Element): HTMLElement {
  const thumb = rail.querySelector<HTMLElement>(".sbar-thumb");
  if (!thumb) throw new Error("rail has no thumb");
  return thumb;
}

// A pointer event for jsdom, which has no PointerEvent constructor in every version.
function pointer(type: string, clientY: number): Event {
  const ev = new MouseEvent(type, { bubbles: true, clientY });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  return ev;
}

describe("Scrollbar rails", () => {
  // Vitest here has no globals, so Testing Library does not clean up by itself.
  afterEach(() => {
    cleanup();
    document.body.style.overflowY = "";
    document.documentElement.classList.remove("sbar-page-on");
  });

  it("host: the thumb length is the share in view (clientHeight / scrollHeight of the track)", async () => {
    const { container } = render(
      <ScrollHost className="ptable-fit">
        <div>rows</div>
      </ScrollHost>,
    );
    const box = container.querySelector<HTMLElement>(".ptable-fit");
    const rail = container.querySelector<HTMLElement>(".sbar-y");
    if (!box || !rail) throw new Error("host did not render its box and rail");
    stubSizes(box, { clientWidth: 300, clientHeight: 100, scrollWidth: 300, scrollHeight: 400 });
    stubSizes(rail, { clientHeight: 200 });

    window.dispatchEvent(new Event("resize"));

    // track 200px x 100 / 400 = 50px; the rail is not shown until its thumb is painted.
    await waitFor(() => expect(thumbOf(rail).style.height).toBe("50px"));
    expect(rail.classList.contains("is-on")).toBe(true);
  });

  it("host: a scroll event moves the thumb along the track", async () => {
    const { container } = render(
      <ScrollHost className="ptable-fit">
        <div>rows</div>
      </ScrollHost>,
    );
    const box = container.querySelector<HTMLElement>(".ptable-fit");
    const rail = container.querySelector<HTMLElement>(".sbar-y");
    if (!box || !rail) throw new Error("host did not render its box and rail");
    stubSizes(box, { clientWidth: 300, clientHeight: 100, scrollWidth: 300, scrollHeight: 400 });
    stubSizes(rail, { clientHeight: 200 });
    window.dispatchEvent(new Event("resize"));
    await waitFor(() => expect(thumbOf(rail).style.height).toBe("50px"));

    // halfway: 50 + (200 - 50) x 0.5 = 125px
    box.scrollTop = 150;
    box.dispatchEvent(new Event("scroll"));

    await waitFor(() => expect(thumbOf(rail).style.height).toBe("125px"));
  });

  it("host: replacing the box's first child repaints the rails", async () => {
    const { container } = render(
      <ScrollHost className="ptable-fit">
        <div>rows</div>
      </ScrollHost>,
    );
    const box = container.querySelector<HTMLElement>(".ptable-fit");
    const rail = container.querySelector<HTMLElement>(".sbar-y");
    if (!box || !rail) throw new Error("host did not render its box and rail");
    stubSizes(box, { clientWidth: 300, clientHeight: 100, scrollWidth: 300, scrollHeight: 400 });
    stubSizes(rail, { clientHeight: 200 });
    window.dispatchEvent(new Event("resize"));
    await waitFor(() => expect(thumbOf(rail).style.height).toBe("50px"));

    // the table body is swapped in place and the box now holds twice the height: no resize or scroll event
    stubSizes(box, { clientWidth: 300, clientHeight: 100, scrollWidth: 300, scrollHeight: 200 });
    box.replaceChildren(document.createElement("table"));

    // track 200px x 100 / 200 = 100px
    await waitFor(() => expect(thumbOf(rail).style.height).toBe("100px"));
  });

  it("host: opt-out (off) renders no rails and leaves the native bars", () => {
    const { container } = render(
      <ScrollHost className="ptable-fit" off>
        <div>rows</div>
      </ScrollHost>,
    );
    expect(container.querySelector(".sbar-rail")).toBeNull();
    expect(container.querySelector(".sbar-on")).toBeNull();
    expect(container.querySelector("[data-sbar='off']")).not.toBeNull();
  });

  it("float: rails sit in body, and a press-and-drag on the rail scrolls the box", async () => {
    // Pointer capture is not in jsdom: record the calls, restore the prototype afterwards.
    const proto = HTMLElement.prototype;
    const savedSet = proto.setPointerCapture;
    const savedRelease = proto.releasePointerCapture;
    const setCapture = vi.fn();
    proto.setPointerCapture = setCapture;
    proto.releasePointerCapture = vi.fn();
    try {
      const { container } = render(
        <ScrollFloat className="max-h-60 overflow-y-auto">
          <div>items</div>
        </ScrollFloat>,
      );
      const box = container.querySelector<HTMLElement>(".overflow-y-auto");
      if (!box) throw new Error("float box missing");
      stubSizes(box, { clientWidth: 300, clientHeight: 100, scrollWidth: 300, scrollHeight: 400 });
      box.getBoundingClientRect = rectOf(300, 100);
      if (box.parentElement) box.parentElement.getBoundingClientRect = rectOf(300, 600);
      const rail = document.body.querySelector<HTMLElement>(".sbar-y");
      if (!rail) throw new Error("float rail not in body");
      expect(container.querySelector(".sbar-y")).toBeNull();
      stubSizes(rail, { clientHeight: 200 });
      rail.getBoundingClientRect = rectOf(12, 200);

      // The thumb is 200 x 100/400 = 50px long and starts at 0. A press on the empty track below it (y=100) pages one
      // screen (the box is 100 high) and does not jump the thumb to the pointer.
      rail.dispatchEvent(pointer("pointerdown", 100));
      expect(setCapture).toHaveBeenCalledWith(1);
      expect(box.scrollTop).toBe(100);

      // A track press is not a drag: moving the pointer on does not scroll further.
      rail.dispatchEvent(pointer("pointermove", 172));
      expect(box.scrollTop).toBe(100);
      rail.dispatchEvent(pointer("pointerup", 172));

      // The thumb now spans 50..100. A press on it at y=75 grabs it 25px from its start without moving the box, and
      // dragging to y=172 gives (172 - 25) / 150 x 300 = 294.
      rail.dispatchEvent(pointer("pointerdown", 75));
      expect(box.scrollTop).toBe(100);
      rail.dispatchEvent(pointer("pointermove", 172));
      expect(box.scrollTop).toBeCloseTo(294, 1);

      // Release: a later move no longer scrolls the box.
      rail.dispatchEvent(pointer("pointerup", 172));
      rail.dispatchEvent(pointer("pointermove", 0));
      expect(box.scrollTop).toBeCloseTo(294, 1);
    } finally {
      proto.setPointerCapture = savedSet;
      proto.releasePointerCapture = savedRelease;
    }
  });

  it("page: the rail hides while the body overflow is locked by a Modal", async () => {
    // The lock is the body:has(.fixed.inset-0.z-50) rule in app.css, which jsdom cannot evaluate. The test checks
    // that a rendered Modal makes the overlay element the rule matches, then applies the overflow the rule gives.
    const { container } = render(<PageScrollbar />);
    const docEl = document.documentElement;
    stubSizes(docEl, { clientWidth: 1024, clientHeight: 768, scrollWidth: 1024, scrollHeight: 2000 });
    const rail = document.body.querySelector<HTMLElement>(".sbar-page");
    if (!rail) throw new Error("page rail not in body");
    expect(container.querySelector(".sbar-page")).toBeNull();
    expect(docEl.classList.contains("sbar-page-on")).toBe(true);

    window.dispatchEvent(new Event("resize"));
    await waitFor(() => expect(rail.classList.contains("is-on")).toBe(true));

    const modal = render(
      <Modal open title="Test" onClose={vi.fn()}>
        body
      </Modal>,
    );
    expect(document.querySelector(".fixed.inset-0.z-50")).not.toBeNull();
    document.body.style.overflowY = "hidden";
    window.dispatchEvent(new Event("resize"));

    await waitFor(() => expect(rail.classList.contains("is-on")).toBe(false));
    modal.unmount();
  });
});
