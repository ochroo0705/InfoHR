import { describe, expect, it } from "vitest";
import { parseCalendarParams, toSearch } from "./calendarParams";

describe("parseCalendarParams", () => {
  it("reads a month and a department from the address", () => {
    expect(parseCalendarParams(new URLSearchParams("month=2026-03&department=4"))).toEqual({
      month: "2026-03",
      department: "4",
    });
  });

  it("gives empty values when the address has neither", () => {
    expect(parseCalendarParams(new URLSearchParams(""))).toEqual({ month: "", department: "" });
  });

  it("drops a junk month, so the server falls back to the current month", () => {
    expect(parseCalendarParams(new URLSearchParams("month=garbage")).month).toBe("");
    expect(parseCalendarParams(new URLSearchParams("month=2026-13")).month).toBe("");
    expect(parseCalendarParams(new URLSearchParams("month=2026-3")).month).toBe("");
  });

  it("drops a junk department, so the list shows everyone as with no filter", () => {
    expect(parseCalendarParams(new URLSearchParams("department=abc")).department).toBe("");
  });
});

describe("toSearch", () => {
  it("writes month and department and leaves out the empty ones", () => {
    expect(toSearch({ month: "2026-03", department: "" }).toString()).toBe("month=2026-03");
    expect(toSearch({ month: "", department: "4" }).toString()).toBe("department=4");
    expect(toSearch({ month: "", department: "" }).toString()).toBe("");
  });

  it("round trips a valid address", () => {
    const search = new URLSearchParams("month=2026-03&department=4");
    expect(toSearch(parseCalendarParams(search)).toString()).toBe("month=2026-03&department=4");
  });
});
