import type { ReactNode } from "react";
import "./mock.css";

// A window frame around a product mockup: a thin chrome bar with three dots and a title, then the screen.
// The frame is one image to assistive technology; its label names it, and the mockup inside is decorative.
export function DeviceFrame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="mock-frame" role="img" aria-label={label}>
      <div className="mock-frame-chrome" aria-hidden="true">
        <span className="mock-dot" />
        <span className="mock-dot" />
        <span className="mock-dot" />
        <span className="mock-frame-title">{label}</span>
      </div>
      <div className="mock-frame-body">{children}</div>
    </div>
  );
}
