import { describe, expect, it } from "vitest";
import { parseRequestParams, toSearch } from "./requestParams";

describe("requestParams", () => {
  it("a missing address reads as the mine tab with no status filter", () => {
    expect(parseRequestParams(new URLSearchParams(""))).toEqual({ tab: "mine", status: "" });
  });

  it("tab=all is the all tab", () => {
    expect(parseRequestParams(new URLSearchParams("tab=all")).tab).toBe("all");
  });

  it("a junk tab shows the mine tab (Django's default)", () => {
    expect(parseRequestParams(new URLSearchParams("tab=junk")).tab).toBe("mine");
    expect(parseRequestParams(new URLSearchParams("tab=ALL")).tab).toBe("mine");
    expect(parseRequestParams(new URLSearchParams("tab=")).tab).toBe("mine");
  });

  it("the status is kept as typed (the server decides what an unknown value matches)", () => {
    expect(parseRequestParams(new URLSearchParams("tab=all&status=rejected")).status).toBe("rejected");
    expect(parseRequestParams(new URLSearchParams("status=garbage")).status).toBe("garbage");
  });

  it("the mine tab is left out of the address, and an empty status too", () => {
    expect(toSearch({ tab: "mine", status: "" }).toString()).toBe("");
  });

  it("the all tab and a status stay in the address", () => {
    expect(toSearch({ tab: "all", status: "" }).toString()).toBe("tab=all");
    expect(toSearch({ tab: "all", status: "rejected" }).toString()).toBe("tab=all&status=rejected");
  });

  it("round trip: parse of an address built by toSearch gives the same params", () => {
    const params = { tab: "all" as const, status: "waiting" };
    expect(parseRequestParams(toSearch(params))).toEqual(params);
    const mine = { tab: "mine" as const, status: "" };
    expect(parseRequestParams(toSearch(mine))).toEqual(mine);
  });
});
