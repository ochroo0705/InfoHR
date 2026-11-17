import { describe, expect, it } from "vitest";
import * as stories from "./confirm.stories";

describe("Confirm stories", () => {
  it("exports the template states", () => {
    const named = Object.keys(stories).filter((key) => key !== "default").sort();
    expect(named).toEqual(["CustomLabels", "Dark", "Default", "LongMongolian"]);
  });
});
