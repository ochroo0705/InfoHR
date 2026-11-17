import { describe, expect, it } from "vitest";
import { caretAfter, format } from "./money";

describe("format (port of money.js format)", () => {
  it("groups the whole part in threes", () => {
    expect(format("2500000")).toBe("2,500,000");
  });

  it("drops leading zeros and keeps two decimals", () => {
    expect(format("0012.345")).toBe("12.34");
  });

  it("writes a leading zero before a lone decimal point", () => {
    expect(format(".5")).toBe("0.5");
  });

  it("removes letters and extra dots", () => {
    expect(format("1a2.3.4")).toBe("12.34");
  });

  it("keeps a trailing dot so the user can keep typing decimals", () => {
    expect(format("12.")).toBe("12.");
  });

  it("returns an empty string for empty input", () => {
    expect(format("")).toBe("");
  });
});

describe("caretAfter (caret rule from money.js reformat)", () => {
  it("keeps the caret after the same digit when typing in the middle", () => {
    // "2,500,000": caret after "2,5", user types "1" there. Raw text "2,5100,000" with caret 4 (after the "1").
    const raw = "2,5100,000";
    const next = format(raw); // "25,100,000"
    expect(next).toBe("25,100,000");
    // Three digits (2, 5, 1) are before the caret, so it goes after the third digit: "25,1" -> index 4.
    expect(caretAfter(raw, 4, next)).toBe(4);
  });

  it("stays at the end when typing at the end", () => {
    const raw = "2500000";
    expect(caretAfter(raw, raw.length, format(raw))).toBe("2,500,000".length);
  });

  it("moves past a comma that was inserted before the caret", () => {
    // Typed "1000" then "0" makes "10000" -> "10,000"; caret was at 5 in raw and must end at 6.
    expect(caretAfter("10000", 5, format("10000"))).toBe(6);
  });
});
