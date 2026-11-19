import { describe, expect, it } from "vitest";
import { ARIA_LABEL, INK, LINE_WIDTH, canvasPoint } from "./signaturePadLogic";

describe("signature pad constants", () => {
  it("keeps the legacy ink, line width and Mongolian aria-label", () => {
    expect(INK).toBe("#1a3a8a");
    expect(LINE_WIDTH).toBe(2.5);
    expect(ARIA_LABEL).toBe("Гарын үсэг зурах талбар");
  });
});

describe("canvasPoint", () => {
  it("maps client coordinates to canvas pixels on a scaled canvas", () => {
    // The canvas is 600x200 pixels but drawn 300x100 CSS pixels at (100, 50).
    const rect = { left: 100, top: 50, width: 300, height: 100 };
    const size = { width: 600, height: 200 };
    expect(canvasPoint(rect, size, 250, 100)).toEqual({ x: 300, y: 100 });
    expect(canvasPoint(rect, size, 100, 50)).toEqual({ x: 0, y: 0 });
    expect(canvasPoint(rect, size, 400, 150)).toEqual({ x: 600, y: 200 });
  });

  it("keeps a 1:1 canvas unchanged apart from the offset", () => {
    const rect = { left: 10, top: 20, width: 600, height: 200 };
    expect(canvasPoint(rect, { width: 600, height: 200 }, 35, 45)).toEqual({ x: 25, y: 25 });
  });

  it("uses a scale of 1 when the rect has zero size", () => {
    const rect = { left: 10, top: 20, width: 0, height: 0 };
    expect(canvasPoint(rect, { width: 600, height: 200 }, 35, 45)).toEqual({ x: 25, y: 25 });
  });
});
