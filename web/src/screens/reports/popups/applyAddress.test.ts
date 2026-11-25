import { describe, expect, it } from "vitest";
import { applyAddress } from "./applyAddress";

describe("applyAddress", () => {
  it("applyAddress_omits_empty_own_and_orders_keep_first", () => {
    expect(applyAddress("emp", [["add", "x"]], [["cols", "name"], ["group", ""]])).toBe(
      "/reports/emp/?add=x&cols=name",
    );
    expect(applyAddress("emp", [], [["group", ""]])).toBe("/reports/emp/");
    expect(applyAddress("emp", [["add", "x"]], [["group", "dept"]])).toBe("/reports/emp/?add=x&group=dept");
  });

  it("applyAddress_repeats_cols", () => {
    expect(applyAddress("emp", [], [["cols", "name"], ["cols", "salary"], ["cols", "joined"]])).toBe(
      "/reports/emp/?cols=name&cols=salary&cols=joined",
    );
  });

  it("percent-encodes names and values, keeping the keep order", () => {
    expect(applyAddress("emp", [["q", "a b&c"]], [["cols", "n+m"]])).toBe("/reports/emp/?q=a%20b%26c&cols=n%2Bm");
  });
});
