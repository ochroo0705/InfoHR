import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { isDisabled, monthGrid, MONTHS_MN, normalise, normaliseMonth, WEEKDAYS_MN } from "./dateLogic";

// npm test runs from web/, so process.cwd() is the web/ folder. The labels are read from the source, as the tokens test does.
const source = readFileSync(resolve(process.cwd(), "../app/static/js/datepicker.js"), "utf8");

function literalArray(name: string): string[] {
  const m = new RegExp(String.raw`var ${name} = \[([\s\S]*?)\];`).exec(source);
  if (!m) throw new Error(`no ${name} in datepicker.js`);
  return [...m[1].matchAll(/"([^"]*)"/g)].map((x) => x[1]);
}

describe("normalise", () => {
  it("turns the three typed forms into YYYY-MM-DD", () => {
    expect(normalise("20261014")).toBe("2026-10-14");
    expect(normalise("2026.10.14")).toBe("2026-10-14");
    expect(normalise("2026/10/14")).toBe("2026-10-14");
  });

  it("keeps an already valid ISO date", () => {
    expect(normalise("2026-10-14")).toBe("2026-10-14");
  });

  it("gives null for an invalid month or day", () => {
    expect(normalise("2026-13-01")).toBeNull();
    expect(normalise("20261340")).toBeNull();
    expect(normalise("2026-02-30")).toBeNull();
  });

  it("gives null for text that is not a date", () => {
    expect(normalise("abc")).toBeNull();
    expect(normalise("")).toBeNull();
  });
});

describe("normaliseMonth", () => {
  it("turns 202610, 2026.10 and 2026/10 into YYYY-MM", () => {
    expect(normaliseMonth("202610")).toBe("2026-10");
    expect(normaliseMonth("2026.10")).toBe("2026-10");
    expect(normaliseMonth("2026/10")).toBe("2026-10");
  });

  it("gives null for a month outside 1 to 12", () => {
    expect(normaliseMonth("2026-13")).toBeNull();
    expect(normaliseMonth("202613")).toBeNull();
  });
});

describe("monthGrid", () => {
  it("has 42 cells for 2026-11 and starts on a Monday", () => {
    const grid = monthGrid(2026, 10);
    expect(grid).toHaveLength(42);
    expect(new Date(`${grid[0].iso}T00:00:00`).getDay()).toBe(1);
    expect(grid[0].iso).toBe("2026-10-26");
  });

  it("marks the days of the month and only those", () => {
    const grid = monthGrid(2026, 10);
    const inMonth = grid.filter((c) => c.inMonth).map((c) => c.iso);
    expect(inMonth).toHaveLength(30);
    expect(inMonth[0]).toBe("2026-11-01");
    expect(inMonth[29]).toBe("2026-11-30");
  });

  it("skips a sixth row that is all next month (datepicker.js: i === 35)", () => {
    // February 2026 starts on a Sunday and its last cell in a 42-cell grid would fall in March.
    const grid = monthGrid(2026, 1);
    expect(grid).toHaveLength(35);
    expect(grid[34]).toEqual({ iso: "2026-03-01", inMonth: false });
  });
});

describe("labels", () => {
  it("MONTHS_MN matches datepicker.js exactly", () => {
    expect(MONTHS_MN).toEqual(literalArray("MONTHS"));
    expect(MONTHS_MN).toHaveLength(12);
  });

  it("WEEKDAYS_MN matches datepicker.js exactly", () => {
    expect(WEEKDAYS_MN).toEqual(literalArray("DAYS"));
    expect(WEEKDAYS_MN).toHaveLength(7);
  });
});

describe("isDisabled", () => {
  it("is false with no limits", () => {
    expect(isDisabled("2026-11-17")).toBe(false);
  });

  it("is true before min and after max, and false on the limits", () => {
    expect(isDisabled("2026-11-09", "2026-11-10", "2026-11-20")).toBe(true);
    expect(isDisabled("2026-11-21", "2026-11-10", "2026-11-20")).toBe(true);
    expect(isDisabled("2026-11-10", "2026-11-10", "2026-11-20")).toBe(false);
    expect(isDisabled("2026-11-20", "2026-11-10", "2026-11-20")).toBe(false);
  });
});
