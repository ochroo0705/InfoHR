import { describe, expect, it } from "vitest";
import { captureBase, dropBase, effectiveLoaded, keyOf, parseLoaded } from "./loadedBase";

const SNAP = JSON.stringify({ register_no: "УБ1", gender: "F", salary: "1000", "si-salary": "9" });

describe("parseLoaded", () => {
  it("reads a JSON object", () => {
    expect(parseLoaded(SNAP)).toEqual({ register_no: "УБ1", gender: "F", salary: "1000", "si-salary": "9" });
  });

  it("reads a text that is not a JSON object as empty", () => {
    expect(parseLoaded("L1")).toEqual({});
    expect(parseLoaded("[1,2]")).toEqual({});
    expect(parseLoaded("")).toEqual({});
  });
});

describe("keyOf", () => {
  it("strips the prefix only from a name that starts with it", () => {
    expect(keyOf("si-salary", "si-")).toBe("salary");
    expect(keyOf("register_no", "si-")).toBe("register_no");
  });

  it("never strips a plain name, and with no prefix the name is its own key", () => {
    expect(keyOf("si-salary")).toBe("si-salary");
    expect(keyOf("register_no")).toBe("register_no");
  });
});

describe("captureBase", () => {
  it("records the snapshot's value for a name", () => {
    expect(captureBase({}, "register_no", SNAP)).toEqual({ register_no: "УБ1" });
  });

  it("keeps the base already recorded for a name", () => {
    const base = { register_no: "old" };
    expect(captureBase(base, "register_no", SNAP)).toBe(base);
  });

  it("records nothing when the snapshot has no key for the name, or is not JSON", () => {
    const base = {};
    expect(captureBase(base, "missing", SNAP)).toBe(base);
    expect(captureBase(base, "register_no", "L1")).toBe(base);
  });

  it("uses the unprefixed key for a name with the given prefix", () => {
    expect(captureBase({}, "si-salary", SNAP, "si-")).toEqual({ salary: "1000" });
  });

  it("a plain name whose key looks prefixed is recorded under its own key", () => {
    expect(captureBase({}, "si-salary", SNAP)).toEqual({ "si-salary": "9" });
  });

  it("records a key that a plain object would answer for through its prototype only when it is an own key", () => {
    const json = JSON.stringify({ toString: "own" });
    expect(captureBase({}, "toString", json)).toEqual({ toString: "own" });
    expect(captureBase({}, "constructor", json)).toEqual({});
  });
});

describe("dropBase", () => {
  it("removes the base of a name", () => {
    expect(dropBase({ register_no: "УБ1", gender: "F" }, "register_no")).toEqual({ gender: "F" });
  });

  it("removes the base of a prefixed name by its key", () => {
    expect(dropBase({ salary: "1000" }, "si-salary", "si-")).toEqual({});
  });

  it("returns the same object when there is no base", () => {
    const base = { gender: "F" };
    expect(dropBase(base, "register_no")).toBe(base);
  });
});

describe("effectiveLoaded", () => {
  const current = JSON.stringify({ register_no: "УБ9", gender: "M" });

  it("substitutes the base for an edited name and keeps the current value for the others", () => {
    expect(JSON.parse(effectiveLoaded(current, { register_no: "УБ1" }, ["register_no"]))).toEqual({
      register_no: "УБ1",
      gender: "M",
    });
  });

  it("returns the current text unchanged when no edited name has a base", () => {
    expect(effectiveLoaded(current, {}, ["register_no"])).toBe(current);
    expect(effectiveLoaded(current, { register_no: "УБ1" }, ["gender"])).toBe(current);
  });

  it("returns the current text unchanged when it is not a JSON object", () => {
    expect(effectiveLoaded("L2", { register_no: "УБ1" }, ["register_no"])).toBe("L2");
  });

  it("removes a prefix from the edited name before the key lookup", () => {
    const salary = JSON.stringify({ salary: "2000" });
    expect(JSON.parse(effectiveLoaded(salary, { salary: "1000" }, ["si-salary"], "si-"))).toEqual({ salary: "1000" });
  });

  it("does not strip the prefix from a plain name, so a plain edit never reads the si- key", () => {
    const withSi = JSON.stringify({ "si-salary": "2000" });
    expect(effectiveLoaded(withSi, { salary: "1000" }, ["si-salary"])).toBe(withSi);
  });
});
