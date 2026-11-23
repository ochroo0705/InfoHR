import { useEffect, useState } from "react";
import { copy } from "./copy";
import { canAnimate } from "./motion";

// How far down the page the visitor must be before the button appears, in pixels.
const SHOW_AFTER = 600;

// A round button fixed to the bottom-right corner that scrolls back to the top. It appears only after the visitor
// has scrolled down, and scrolls smoothly only when motion is allowed.
export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const update = () => setVisible(window.scrollY > SHOW_AFTER);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  if (!visible) {
    return null;
  }
  return (
    <button
      type="button"
      className="w-top"
      aria-label={copy.backToTop}
      title={copy.backToTop}
      onClick={() => window.scrollTo({ top: 0, behavior: canAnimate() ? "smooth" : "auto" })}
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
        <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
