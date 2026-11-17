import { describe, expect, it } from "vitest";
import { placement } from "./rowMenuLogic";

const SCREEN = { width: 1280, height: 800 };
const PANEL = { width: 192, height: 120 };

describe("placement", () => {
  it("aligns the panel's right edge with the button when there is room on the right", () => {
    const button = { top: 100, bottom: 130, left: 500, right: 600 };
    expect(placement(button, PANEL, SCREEN)).toEqual({ left: "auto", right: "680px", top: "134px", bottom: "auto" });
  });

  it("aligns the left edge with the button on a narrow screen", () => {
    const button = { top: 100, bottom: 130, left: 10, right: 60 };
    expect(placement(button, PANEL, SCREEN)).toEqual({ left: "10px", right: "auto", top: "134px", bottom: "auto" });
  });

  it("keeps the left edge 8 px from the screen edge", () => {
    const button = { top: 100, bottom: 130, left: 2, right: 40 };
    expect(placement(button, PANEL, SCREEN).left).toBe("8px");
  });

  it("keeps a button at the far right aligned to the right edge, 8 px in", () => {
    const button = { top: 100, bottom: 130, left: 1270, right: 1275 };
    expect(placement(button, PANEL, SCREEN)).toMatchObject({ left: "auto", right: "8px" });
  });

  it("opens upward when there is no room below and more room above", () => {
    const button = { top: 700, bottom: 730, left: 500, right: 600 };
    expect(placement(button, PANEL, SCREEN)).toEqual({ left: "auto", right: "680px", top: "auto", bottom: "104px" });
  });

  it("opens downward when the panel fits below, even near the bottom", () => {
    const button = { top: 600, bottom: 630, left: 500, right: 600 };
    expect(placement(button, PANEL, SCREEN).bottom).toBe("auto");
  });
});
