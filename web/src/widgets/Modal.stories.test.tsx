import { describe, expect, it } from "vitest";
import * as stories from "./Modal.stories";

describe("Modal stories", () => {
  it("exports the five template states", () => {
    const named = Object.keys(stories).filter((key) => key !== "default").sort();
    expect(named).toEqual(["Dark", "Default", "Dirty", "LongMongolian", "ServerError"]);
  });
});
