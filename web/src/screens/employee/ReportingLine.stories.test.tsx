import { describe, expect, it } from "vitest";
import * as stories from "./ReportingLine.stories";

describe("ReportingLine stories", () => {
  it("exports the seven states", () => {
    const named = Object.keys(stories).filter((key) => key !== "default").sort();
    expect(named).toEqual(["Dark", "Default", "Empty", "Error", "Loading", "LongChain", "LongMongolian"]);
  });
});
