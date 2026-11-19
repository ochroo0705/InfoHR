import { forwardRef, useImperativeHandle, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { ARIA_LABEL, INK, LINE_WIDTH, canvasPoint, type Point } from "./signaturePadLogic";

// Port of app/static/js/signature_pad.js for React. Strokes use Pointer Events with pointer capture; the canvas stays
// transparent (the white comes from the box around it). After each finished stroke, onChange gets the canvas as a PNG
// data URL. clear() blanks the canvas and calls onChange(""). Each pad keeps its own stroke state, so a pad removed
// mid-drag cannot block another one.

const WIDTH = 600;
const HEIGHT = 200;

export interface SignaturePadProps {
  onChange: (dataUrl: string) => void;
}

export interface SignaturePadHandle {
  clear: () => void;
}

interface StrokeState {
  pointerId: number;
  last: Point;
}

function styleContext(ctx: CanvasRenderingContext2D): CanvasRenderingContext2D {
  ctx.strokeStyle = INK;
  ctx.fillStyle = INK;
  ctx.lineWidth = LINE_WIDTH;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  return ctx;
}

function pointOf(canvas: HTMLCanvasElement, clientX: number, clientY: number): Point {
  return canvasPoint(
    canvas.getBoundingClientRect(),
    { width: canvas.width, height: canvas.height },
    clientX,
    clientY,
  );
}

export const SignaturePad = forwardRef<SignaturePadHandle, SignaturePadProps>(function SignaturePad({ onChange }, ref) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stroke = useRef<StrokeState | null>(null);

  useImperativeHandle(
    ref,
    () => ({
      clear() {
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext("2d");
        if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        onChange("");
      },
    }),
    [onChange],
  );

  function onPointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    const canvas = e.currentTarget;
    // Only the primary button draws, and a second pointer must not take over the stroke in progress.
    if (e.button > 0 || stroke.current) return;
    e.preventDefault();
    const p = pointOf(canvas, e.clientX, e.clientY);
    stroke.current = { pointerId: e.pointerId, last: p };
    if (canvas.setPointerCapture) {
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch {
        // Capture refused: the stroke still works, it just may stop at the canvas edge.
      }
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    styleContext(ctx);
    // A tap with no movement leaves a dot.
    ctx.beginPath();
    ctx.arc(p.x, p.y, LINE_WIDTH / 2, 0, Math.PI * 2);
    ctx.fill();
  }

  function onPointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    const s = stroke.current;
    if (!s || e.pointerId !== s.pointerId) return;
    const canvas = e.currentTarget;
    const p = pointOf(canvas, e.clientX, e.clientY);
    const ctx = canvas.getContext("2d");
    if (ctx) {
      styleContext(ctx);
      ctx.beginPath();
      ctx.moveTo(s.last.x, s.last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }
    s.last = p;
  }

  function onPointerEnd(e: ReactPointerEvent<HTMLCanvasElement>) {
    const s = stroke.current;
    if (!s || e.pointerId !== s.pointerId) return;
    const canvas = e.currentTarget;
    stroke.current = null;
    if (canvas.releasePointerCapture) {
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        // Already released.
      }
    }
    onChange(canvas.toDataURL("image/png"));
  }

  return (
    <div className="rounded-lg border border-slate-300 bg-white">
      <canvas
        ref={canvasRef}
        width={WIDTH}
        height={HEIGHT}
        role="img"
        aria-label={ARIA_LABEL}
        style={{ aspectRatio: "3 / 1", height: "auto" }}
        className="block w-full touch-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onLostPointerCapture={onPointerEnd}
      />
    </div>
  );
});
