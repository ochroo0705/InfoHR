import { cleanup, fireEvent, render } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SignaturePad, type SignaturePadHandle } from "./SignaturePad";

const PNG = "data:image/png;base64,AAAA";

// jsdom has no canvas: a recording 2D context and a fixed toDataURL stand in for it.
let calls: Array<[string, ...unknown[]]>;
let ctx: Record<string, unknown>;

beforeEach(() => {
  calls = [];
  ctx = {
    strokeStyle: null,
    fillStyle: null,
    lineWidth: null,
    lineCap: null,
    lineJoin: null,
    beginPath: () => calls.push(["beginPath"]),
    moveTo: (x: number, y: number) => calls.push(["moveTo", x, y]),
    lineTo: (x: number, y: number) => calls.push(["lineTo", x, y]),
    stroke: () => calls.push(["stroke"]),
    fill: () => calls.push(["fill"]),
    arc: (...args: unknown[]) => calls.push(["arc", ...args]),
    clearRect: (...args: unknown[]) => calls.push(["clearRect", ...args]),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => ctx as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(() => PNG);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup() {
  const onChange = vi.fn();
  const ref = createRef<SignaturePadHandle>();
  const { container } = render(<SignaturePad ref={ref} onChange={onChange} />);
  const canvas = container.querySelector("canvas") as HTMLCanvasElement;
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();
  return { onChange, ref, canvas, container };
}

function pointer(type: string, canvas: HTMLElement, init: Record<string, unknown> = {}) {
  const { pointerId = 1, button = 0, clientX = 0, clientY = 0 } = init;
  fireEvent(canvas, new PointerEvent(type, { bubbles: true, cancelable: true, button, clientX, clientY, pointerId } as PointerEventInit));
}

describe("SignaturePad markup", () => {
  it("renders a 600x200 transparent canvas with the legacy size, class and label", () => {
    const { canvas } = setup();
    expect(canvas.width).toBe(600);
    expect(canvas.height).toBe(200);
    expect(canvas.className).toBe("block w-full touch-none");
    expect(canvas.style.aspectRatio).toBe("3 / 1");
    expect(canvas.style.height).toBe("auto");
    expect(canvas.getAttribute("aria-label")).toBe("Гарын үсэг зурах талбар");
    expect(canvas.getAttribute("role")).toBe("img");
  });

  it("wraps the canvas in the bordered white box", () => {
    const { canvas } = setup();
    expect(canvas.parentElement?.className).toBe("rounded-lg border border-slate-300 bg-white");
  });
});

describe("SignaturePad strokes", () => {
  it("calls onChange once with the PNG data URL after a finished stroke", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 10, clientY: 10 });
    pointer("pointermove", canvas, { clientX: 50, clientY: 40 });
    pointer("pointermove", canvas, { clientX: 90, clientY: 20 });
    expect(onChange).not.toHaveBeenCalled();
    pointer("pointerup", canvas, { clientX: 90, clientY: 20 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(PNG);
  });

  it("uses the ink colour, line width and round caps, and captures the pointer", () => {
    const { canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 10, clientY: 10 });
    pointer("pointermove", canvas, { clientX: 50, clientY: 40 });
    pointer("pointerup", canvas, { clientX: 50, clientY: 40 });
    expect(ctx.strokeStyle).toBe("#1a3a8a");
    expect(ctx.lineWidth).toBe(2.5);
    expect(ctx.lineCap).toBe("round");
    expect(ctx.lineJoin).toBe("round");
    expect(canvas.setPointerCapture).toHaveBeenCalledWith(1);
    expect(canvas.releasePointerCapture).toHaveBeenCalledWith(1);
    expect(calls.some((c) => c[0] === "stroke")).toBe(true);
  });

  it("a click without movement still counts as a dot", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 30, clientY: 30 });
    pointer("pointerup", canvas, { clientX: 30, clientY: 30 });
    expect(calls.some((c) => c[0] === "arc")).toBe(true);
    expect(calls.some((c) => c[0] === "fill")).toBe(true);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(PNG);
  });

  it("a pointer move without a pointer down draws nothing and calls nothing", () => {
    const { onChange, canvas } = setup();
    pointer("pointermove", canvas, { clientX: 20, clientY: 20 });
    pointer("pointerup", canvas, { clientX: 20, clientY: 20 });
    expect(calls).toEqual([]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a right-button press does not start a stroke", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { button: 2, clientX: 5, clientY: 5 });
    pointer("pointerup", canvas, { button: 2, clientX: 5, clientY: 5 });
    expect(calls).toEqual([]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a second pointer does not take over the stroke in progress", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { pointerId: 1, clientX: 10, clientY: 10 });
    pointer("pointerdown", canvas, { pointerId: 2, clientX: 200, clientY: 100 });
    expect(canvas.setPointerCapture).toHaveBeenCalledTimes(1);
    pointer("pointerup", canvas, { pointerId: 2, clientX: 200, clientY: 100 });
    expect(onChange).not.toHaveBeenCalled();
    pointer("pointerup", canvas, { pointerId: 1, clientX: 50, clientY: 40 });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("pointercancel ends the stroke and writes the signature like pointerup", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 5, clientY: 5 });
    pointer("pointercancel", canvas, { clientX: 5, clientY: 5 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(PNG);
  });

  it("a lost pointer capture ends the stroke", () => {
    const { onChange, canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 10, clientY: 10 });
    pointer("lostpointercapture", canvas, { clientX: 10, clientY: 10 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(PNG);
  });
});

describe("SignaturePad clear", () => {
  it("clear() blanks the canvas and calls onChange with an empty string", () => {
    const { onChange, ref, canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 10, clientY: 10 });
    pointer("pointerup", canvas, { clientX: 10, clientY: 10 });
    onChange.mockClear();
    ref.current?.clear();
    expect(calls.some((c) => c[0] === "clearRect" && c[3] === 600 && c[4] === 200)).toBe(true);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("the canvas is never filled with a background, so it stays transparent", () => {
    const { canvas } = setup();
    pointer("pointerdown", canvas, { clientX: 10, clientY: 10 });
    pointer("pointermove", canvas, { clientX: 50, clientY: 40 });
    pointer("pointerup", canvas, { clientX: 50, clientY: 40 });
    expect(calls.some((c) => c[0] === "fillRect")).toBe(false);
  });
});
