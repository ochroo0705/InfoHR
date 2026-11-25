// Vitest port of app/static/js/report_memory.test.mjs: the pure helpers, every case of the Node spec.
import { afterEach, describe, expect, it, vi } from "vitest";
import { isResetLink, rememberable, restoreTarget, storageKey } from "./reportMemory";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("reportMemory helpers", () => {
  it("the key carries the user id and the report key", () => {
    expect(storageKey("7", "/reports/orders/")).toBe("hr.reportQuery.u7.orders");
  });

  it("no key without a user id, or outside a report's plain address", () => {
    expect(storageKey("", "/reports/orders/")).toBe(null);
    expect(storageKey("7", "/reports/")).toBe(null);
    expect(storageKey("7", "/reports/orders/print/")).toBe(null);
  });

  it("rememberable drops the day and month parameters and keeps the rest in order", () => {
    expect(rememberable("?state=all&as_of=2026-10-31&sort=name")).toBe("?state=all&sort=name");
    expect(rememberable("?layout=calendar&lmonth=2025-02&lby=hired")).toBe("?layout=calendar&lby=hired");
  });

  it("rememberable drops the calendar week, a fixed date, and keeps the year window and grouping", () => {
    expect(rememberable("?layout=calendar&lweek=2026-11-02")).toBe("?layout=calendar");
    expect(rememberable("?layout=timeline&lyear=2026&lgroup=dept&lweek=2026-11-02")).toBe(
      "?layout=timeline&lyear=2026&lgroup=dept",
    );
  });

  it("rememberable returns nothing when only the day or month was set, or the search is empty", () => {
    expect(rememberable("?as_of=2026-10-31")).toBe("");
    expect(rememberable("")).toBe("");
  });

  it("rememberable drops the search and keeps the other parameters", () => {
    expect(rememberable("?state=all&q=Батын&sort=name")).toBe("?state=all&sort=name");
    expect(rememberable("?q=Батын")).toBe("");
    expect(rememberable("?q=%D0%B1&layout=cards")).toBe("?layout=cards");
  });

  it("a percent-encoded search name is dropped too", () => {
    expect(rememberable("?%71=abc&state=all")).toBe("?state=all");
  });

  it("rememberable keeps the other parameters exactly as encoded", () => {
    expect(rememberable("?rules=%7B%22op%22%3A%22and%22%7D")).toBe("?rules=%7B%22op%22%3A%22and%22%7D");
    expect(rememberable("?sort=a%20b+c&as_of=2026-10-31")).toBe("?sort=a%20b+c");
  });

  it("rememberable removes every occurrence of the day and month parameters", () => {
    expect(rememberable("?as_of=2026-01-01&state=all&as_of=2026-02-02")).toBe("?state=all");
  });

  it("a plain navigation with a saved setup goes to the setup", () => {
    expect(restoreTarget("navigate", "/reports/orders/", "", "?order_type=1")).toBe("/reports/orders/?order_type=1");
  });

  it("no restore on reload or back/forward", () => {
    expect(restoreTarget("reload", "/reports/orders/", "", "?order_type=1")).toBe(null);
    expect(restoreTarget("back_forward", "/reports/orders/", "", "?order_type=1")).toBe(null);
  });

  it("no restore when the address already has a query", () => {
    expect(restoreTarget("navigate", "/reports/orders/", "?state=all", "?order_type=1")).toBe(null);
  });

  it("no restore when nothing usable is saved", () => {
    expect(restoreTarget("navigate", "/reports/orders/", "", null)).toBe(null);
    expect(restoreTarget("navigate", "/reports/orders/", "", "x=1")).toBe(null);
  });

  it("no restore for a saved value that is only the question mark (corrupt storage would reload forever)", () => {
    expect(restoreTarget("navigate", "/reports/orders/", "", "?")).toBe(null);
    expect(restoreTarget("navigate", "/reports/orders/", "", "")).toBe(null);
  });

  it("a percent-encoded day or month parameter name is dropped too", () => {
    expect(rememberable("?%61s_of=2026-01-01&state=all")).toBe("?state=all");
    expect(rememberable("?%6Cmonth=2026-01&state=all")).toBe("?state=all");
  });

  it("a parameter name that cannot be decoded is not remembered", () => {
    expect(rememberable("?%E0%A4%A=1&state=all")).toBe("?state=all");
  });

  it("a reset link is one with data-reset-all, itself or above", () => {
    expect(isResetLink({ closest: (s: string) => (s === "[data-reset-all]" ? {} : null) } as unknown as Element)).toBe(
      true,
    );
    expect(isResetLink({ closest: () => null } as unknown as Element)).toBe(false);
    expect(isResetLink(null)).toBe(false);
  });
});
