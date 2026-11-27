import { describe, expect, it } from "vitest";
import { RL_TEXT, orDash, showLabel, staggerMs, untilLabel } from "./reportingText";

describe("RL_TEXT", () => {
  it("holds the Mongolian strings verbatim", () => {
    expect(RL_TEXT).toEqual({
      heading: "Удирдлагын шат",
      none: "Удирдлага байхгүй",
      hide: "Нуух",
      date: "Огноо",
      phone: "Утас",
      email: "И-мэйл",
      department: "Хэлтэс",
      loadError: "Удирдлагын шатыг ачаалж чадсангүй.",
    });
  });
});

describe("showLabel", () => {
  it("names the hidden count of levels", () => {
    expect(showLabel(3)).toBe("Бүх шатыг харуулах · 3");
  });
});

describe("untilLabel", () => {
  it("appends the Mongolian 'until' word to a date", () => {
    expect(untilLabel("2026-12-31")).toBe("2026-12-31 хүртэл");
  });

  it("returns an empty string for an empty date", () => {
    expect(untilLabel("")).toBe("");
  });
});

describe("staggerMs", () => {
  it("is zero for the nearest level", () => {
    expect(staggerMs(0)).toBe(0);
  });

  it("is 70 ms per level", () => {
    expect(staggerMs(1)).toBe(70);
    expect(staggerMs(3)).toBe(210);
  });

  it("caps at the sixth step", () => {
    expect(staggerMs(6)).toBe(420);
    expect(staggerMs(20)).toBe(420);
  });
});

describe("orDash", () => {
  it("returns the value when it is not blank", () => {
    expect(orDash("Санхүү")).toBe("Санхүү");
  });

  it("returns an em dash when the value is blank", () => {
    expect(orDash("")).toBe("—");
    expect(orDash("  ")).toBe("—");
  });
});
