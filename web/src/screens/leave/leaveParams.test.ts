import { describe, expect, it } from "vitest";
import { parseLeaveParams, toSearch } from "./leaveParams";

describe("leaveParams", () => {
  it("a missing address reads as the default: status recorded, the rest empty", () => {
    expect(parseLeaveParams(new URLSearchParams(""))).toEqual({
      q: "",
      employee: "",
      status: "recorded",
      type: "",
      from: "",
      to: "",
    });
  });

  it("an empty status falls back to the default", () => {
    expect(parseLeaveParams(new URLSearchParams("status=")).status).toBe("recorded");
  });

  it("garbage values are kept as typed (the server decides what they mean)", () => {
    const params = parseLeaveParams(new URLSearchParams("status=garbage&from=2026-13-45&employee=abc"));
    expect(params.status).toBe("garbage");
    expect(params.from).toBe("2026-13-45");
    expect(params.employee).toBe("abc");
  });

  it("the default status and empty values are left out of the address", () => {
    expect(toSearch(parseLeaveParams(new URLSearchParams(""))).toString()).toBe("");
    expect(toSearch({ status: "recorded", q: "", type: "" }).toString()).toBe("");
  });

  it("a non-default status stays in the address", () => {
    expect(toSearch({ status: "all" }).toString()).toBe("status=all");
  });

  it("the address keeps the fixed order", () => {
    const search = toSearch({
      to: "2026-12-31",
      from: "2026-01-01",
      type: "3",
      status: "rejected",
      employee: "7",
      q: "Бат",
    });
    expect(search.toString()).toBe("q=%D0%91%D0%B0%D1%82&employee=7&status=rejected&type=3&from=2026-01-01&to=2026-12-31");
  });

  it("round trip: parse of an address built by toSearch gives the same params", () => {
    const params = { q: "Болд", employee: "", status: "mistake", type: "2", from: "2026-02-01", to: "" };
    const again = parseLeaveParams(toSearch(params));
    expect(again).toEqual({ ...params, employee: "", to: "" });
  });
});
