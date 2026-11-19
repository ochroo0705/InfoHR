// Pure helpers of the signature pad (SignaturePad.tsx). Port of the constants and canvasPoint() in
// app/static/js/signature_pad.js; the values must stay as they are there, so the drawing matches the Django pop-up.

export const INK = "#1a3a8a";
export const LINE_WIDTH = 2.5;
export const ARIA_LABEL = "Гарын үсэг зурах талбар";

export interface Point {
  x: number;
  y: number;
}

// Client (CSS pixel) point to canvas pixel. The canvas may be scaled by CSS, so the ratio of its pixel size to its
// on-screen box is applied. A zero-size box is taken as 1:1.
export function canvasPoint(
  rect: { left: number; top: number; width: number; height: number },
  canvasSize: { width: number; height: number },
  clientX: number,
  clientY: number,
): Point {
  const sx = rect.width ? canvasSize.width / rect.width : 1;
  const sy = rect.height ? canvasSize.height / rect.height : 1;
  return { x: (clientX - rect.left) * sx, y: (clientY - rect.top) * sy };
}
