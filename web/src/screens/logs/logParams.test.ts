import { describe, expect, it } from "vitest";
import type { EmployeeLogParams, SystemLogParams } from "../../api/logs";
import {
  employeeParamsFromSearch,
  searchFromEmployeeParams,
  searchFromSystemParams,
  systemParamsFromSearch,
} from "./logParams";

const EMPTY_EMPLOYEE: EmployeeLogParams = {
  q: "",
  emp: "",
  employee: "",
  by: "",
  kind: [],
  area: "",
  field: "",
  from: "",
  to: "",
  system: "",
  oldest: "",
};

const EMPTY_SYSTEM: SystemLogParams = {
  q: "",
  by: "",
  target: "",
  ip: "",
  category: [],
  action: "",
  from: "",
  to: "",
  oldest: "",
};

describe("logParams", () => {
  it("employee params keep repeated kinds in order", () => {
    const params = employeeParamsFromSearch(new URLSearchParams("kind=hire&kind=leave&kind=transfer&q=Бат"));
    expect(params.kind).toEqual(["hire", "leave", "transfer"]);
    expect(params.q).toBe("Бат");
  });

  it("search omits empty values", () => {
    expect(searchFromEmployeeParams(EMPTY_EMPLOYEE).toString()).toBe("");
    expect(searchFromSystemParams(EMPTY_SYSTEM).toString()).toBe("");
    expect(
      searchFromEmployeeParams({ ...EMPTY_EMPLOYEE, q: "", kind: ["", "hire"], from: "2025-01-01" }).toString(),
    ).toBe("kind=hire&from=2025-01-01");
    expect(searchFromSystemParams({ ...EMPTY_SYSTEM, category: ["", "auth"], ip: "" }).toString()).toBe(
      "category=auth",
    );
  });

  it("key order matches the Django address", () => {
    const employee = searchFromEmployeeParams({
      oldest: "1",
      system: "1",
      to: "2025-12-31",
      from: "2025-01-01",
      field: "salary",
      area: "org",
      kind: ["hire", "leave"],
      by: "5",
      employee: "12",
      emp: "E-7",
      q: "Бат",
    });
    expect([...employee.keys()]).toEqual([
      "q",
      "emp",
      "employee",
      "by",
      "kind",
      "kind",
      "area",
      "field",
      "from",
      "to",
      "system",
      "oldest",
    ]);

    const system = searchFromSystemParams({
      oldest: "1",
      to: "2025-12-31",
      from: "2025-01-01",
      ip: "10.0.0.1",
      target: "7",
      by: "5",
      action: "delete",
      category: ["auth", "data"],
      q: "login",
    });
    expect([...system.keys()]).toEqual([
      "q",
      "category",
      "category",
      "action",
      "by",
      "target",
      "ip",
      "from",
      "to",
      "oldest",
    ]);
  });

  it("system params round trip", () => {
    const search = new URLSearchParams("q=login&category=auth&category=data&action=delete&ip=10.0.0.1&from=2025-01-01&oldest=1");
    const params = systemParamsFromSearch(search);
    expect(params).toEqual({
      q: "login",
      by: "",
      target: "",
      ip: "10.0.0.1",
      category: ["auth", "data"],
      action: "delete",
      from: "2025-01-01",
      to: "",
      oldest: "1",
    });
    expect(searchFromSystemParams(params).toString()).toBe(
      "q=login&category=auth&category=data&action=delete&ip=10.0.0.1&from=2025-01-01&oldest=1",
    );
  });

  it("a junk value is kept as typed", () => {
    const params = employeeParamsFromSearch(new URLSearchParams("employee=abc&kind=zzz&from=not-a-date&system=yes"));
    expect(params.employee).toBe("abc");
    expect(params.kind).toEqual(["zzz"]);
    expect(params.from).toBe("not-a-date");
    expect(params.system).toBe("yes");

    const system = systemParamsFromSearch(new URLSearchParams("ip=%20x%20&category=bogus"));
    expect(system.ip).toBe(" x ");
    expect(system.category).toEqual(["bogus"]);
  });
});
