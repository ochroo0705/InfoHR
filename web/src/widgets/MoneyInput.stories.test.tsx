import { describe, expect, it } from "vitest";
import * as stories from "./MoneyInput.stories";

describe("MoneyInput stories", () => {
  it("exports the four template states", () => {
    const named = Object.keys(stories).filter((key) => key !== "default").sort();
    expect(named).toEqual(["Dark", "Default", "Filled", "Labelled"]);
  });
});
