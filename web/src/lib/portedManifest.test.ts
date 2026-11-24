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

  it("serves the leave list (with its filters) from the React app but not the leave pop-ups and other leave pages", () => {
    expect(isPorted("/leave/")).toBe(true);
    expect(isPorted("/leave/?status=all")).toBe(true);
    expect(isPorted("/leave/new/")).toBe(false);
    expect(isPorted("/leave/1/edit/")).toBe(false);
  });

  it("serves the leave balances, calendar, holidays and settings pages, with or without a query", () => {
    for (const path of ["/leave/balances/", "/leave/calendar/", "/leave/holidays/", "/leave/settings/"]) {
      expect(isPorted(path)).toBe(true);
      expect(isPorted(`${path}?year=2026`)).toBe(true);
    }
  });

  it("does not serve the leave settings type pop-ups, which stay Django-only", () => {
    expect(isPorted("/leave/settings/type/")).toBe(false);
    expect(isPorted("/leave/settings/type/5/")).toBe(false);
    expect(isPorted("/leave/settings/type/5/delete/")).toBe(false);
  });

  it("serves the leave requests list from the React app, with or without its filters, but not the request sub-pages", () => {
    expect(isPorted("/leave/requests/")).toBe(true);
    expect(isPorted("/leave/requests/?tab=all")).toBe(true);
    expect(isPorted("/leave/requests/new/")).toBe(false);
    expect(isPorted("/leave/requests/5/")).toBe(false);
    expect(isPorted("/leave/requests/check/")).toBe(false);
  });

  it("maps the real PORTED list one to one", () => {
    expect(portedManifest(PORTED).length).toBe(PORTED.length);
  });
});
