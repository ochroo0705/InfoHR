// Where a row menu's panel goes on screen. Port of app/static/js/row_menu.js place(): the panel is fixed under its
// «Үйлдэл ▾» button with its right edge on the button's right edge; on a narrow screen (no room on the right) its left
// edge goes on the button's left edge instead, kept 8 px from the screen edge. It opens upward when there is no room
// below and more room above. Pure: the caller measures and applies the result.

export type Box = { top: number; bottom: number; left: number; right: number };
export type Size = { width: number; height: number };
export type Placement = { top: string; bottom: string; left: string; right: string };

const EDGE = 8; // the gap kept to the screen edge, px
const GAP = 4; // the gap between the button and the panel, px

export function placement(button: Box, panel: Size, screen: Size): Placement {
  let left: string;
  let right: string;
  if (button.right - panel.width >= EDGE) {
    left = "auto";
    right = `${Math.max(EDGE, screen.width - button.right)}px`;
  } else {
    right = "auto";
    left = `${Math.max(EDGE, Math.min(button.left, screen.width - panel.width - EDGE))}px`;
  }
  const below = screen.height - button.bottom;
  if (below < panel.height + EDGE && button.top > below) {
    return { left, right, top: "auto", bottom: `${screen.height - button.top + GAP}px` };
  }
  return { left, right, bottom: "auto", top: `${button.bottom + GAP}px` };
}
