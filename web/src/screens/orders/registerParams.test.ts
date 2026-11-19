import { describe, expect, it } from "vitest";
import type { RegisterParams } from "../../api/orderRegister";
import { paramsFromSearch, printHref, searchFromParams } from "./registerParams";

const EMPTY: RegisterParams = {
  q: "",
  sort: "-date",
  year: "",
  order_type: "",
  department: "",
  state: "",
};

describe("registerParams", () => {
  it("searchFromParams omits empty values and the default sort", () => {
    expect(searchFromParams(EMPTY).toString()).toBe("");
    expect(searchFromParams({ ...EMPTY, sort: "name" }).toString()).toBe("sort=name");
    expect(searchFromParams({ ...EMPTY, year: "2025", state: "signed" }).toString()).toBe(
      "year=2025&state=signed",
    );
  });

  it("searchFromParams keeps the backend parameter order: q, sort, year, order_type, department, state", () => {
    const search = searchFromParams({
      state: "signed",
      department: "4",
      order_type: "2",
      year: "2025",
      sort: "name",
      q: "Бат",
    });
    expect([...search.keys()]).toEqual(["q", "sort", "year", "order_type", "department", "state"]);
  });

  it("paramsFromSearch keeps unknown values as typed (the server cleans them)", () => {
    const params = paramsFromSearch(new URLSearchParams("year=abc&state=zzz&q=%20Бат%20"));
    expect(params).toEqual({
      q: " Бат ",
      sort: "-date",
      year: "abc",
      order_type: "",
      department: "",
      state: "zzz",
    });
  });

  it("printHref carries the filters", () => {
    expect(printHref(EMPTY)).toBe("/employees/orders/print/");
    expect(printHref({ ...EMPTY, q: "Бат", year: "2025", department: "4" })).toBe(
      "/employees/orders/print/?" + new URLSearchParams({ q: "Бат", year: "2025", department: "4" }).toString(),
    );
    expect(printHref({ ...EMPTY, sort: "name" })).toBe("/employees/orders/print/?sort=name");
  });
});
