import { describe, expect, it } from "vitest";
import { portedManifest } from "../../vite-plugin-ported";
import { isPorted, PORTED } from "./ported";

describe("portedManifest", () => {
  it("returns the regex sources as strings", () => {
    expect(portedManifest([/^\/a\/$/, /^\/b\/\d+\/$/])).toEqual(["^\\/a\\/$", "^\\/b\\/\\d+\\/$"]);
  });

  it("throws for a regex with flags", () => {
    expect(() => portedManifest([/x/i])).toThrow(Error);
  });

  it("throws for a named group, which Python reads differently", () => {
    expect(() => portedManifest([/(?<id>\d+)/])).toThrow(Error);
  });

  it("serves /welcome from the React app", () => {
    expect(isPorted("/welcome")).toBe(true);
    expect(isPorted("/welcome/")).toBe(true);
  });

  it("serves the three lists pages but not the Django quick-add address", () => {
    expect(isPorted("/lists/")).toBe(true);
    expect(isPorted("/lists/meaning/")).toBe(true);
    expect(isPorted("/lists/bank/")).toBe(true);
    expect(isPorted("/lists/bank/quick/")).toBe(false);
  });

  it("serves /checklists/mine/ from the React app but not a checklist task action", () => {
    expect(isPorted("/checklists/mine/")).toBe(true);
    expect(isPorted("/checklists/task/1/tick/")).toBe(false);
  });

  it("maps the real PORTED list one to one", () => {
    expect(portedManifest(PORTED).length).toBe(PORTED.length);
  });
});
