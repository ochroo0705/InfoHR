import { describe, expect, it } from "vitest";
import type { EventFormOut } from "../../api/events";
import type { FormField } from "../../widgets/FormFields";
import {
  mergeFormAfterRefresh,
  prevEffectiveBase,
  refreshKindFor,
  valuesToSend,
} from "./eventModalLogic";

function field(name: string, extra: Partial<FormField> = {}): FormField {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    kind: "text",
    label: name,
    max_length: null,
    name,
    placeholder: "",
    required: false,
    value: "",
    ...extra,
  };
}

function form(fields: FormField[], orderFields: FormField[] = [], prevEffective = ""): EventFormOut {
  return {
    death_unset: false,
    errors: {},
    fields,
    form_errors: [],
    kinds: [],
    order_errors: [],
    order_fields: orderFields,
    order_note: "",
    prev_effective: prevEffective,
    reload: false,
    summary: "",
    title: "",
    when: "",
  };
}

describe("valuesToSend", () => {
  it("drops kind", () => {
    const out = valuesToSend([{ name: "kind" }, { name: "reason" }], { kind: "transfer", reason: "x" });
    expect(out).toEqual({ reason: "x" });
  });

  it("drops csrfmiddlewaretoken even when it is listed as a field", () => {
    const out = valuesToSend([{ name: "csrfmiddlewaretoken" }, { name: "reason" }], {
      csrfmiddlewaretoken: "t",
      reason: "x",
    });
    expect(out).toEqual({ reason: "x" });
  });

  it("drops names that are not in fields", () => {
    const out = valuesToSend([{ name: "reason" }], { reason: "x", stray: "y" });
    expect(out).toEqual({ reason: "x" });
  });

  it("keeps order-block names carried in fields", () => {
    const out = valuesToSend([{ name: "reason" }, { name: "order-number" }], {
      reason: "x",
      "order-number": "12",
    });
    expect(out).toEqual({ reason: "x", "order-number": "12" });
  });
});

describe("refreshKindFor", () => {
  it("reloads the whole form for the effective date", () => {
    expect(refreshKindFor("effective")).toBe("form");
  });

  it("refreshes the summary for every other event box", () => {
    expect(refreshKindFor("reason")).toBe("summary");
  });

  it("refreshes the summary for an order box", () => {
    expect(refreshKindFor("order-number")).toBe("summary");
  });

  it("returns null for kind, prev_effective and the csrf token", () => {
    expect(refreshKindFor("kind")).toBeNull();
    expect(refreshKindFor("prev_effective")).toBeNull();
    expect(refreshKindFor("csrfmiddlewaretoken")).toBeNull();
  });
});

describe("mergeFormAfterRefresh", () => {
  it("keeps a typed reason value from the server and takes a new position from the server", () => {
    const held = { reason: "typed", position: "old" };
    const next = form([field("reason", { value: "typed" }), field("position", { value: "new" })]);
    expect(mergeFormAfterRefresh(held, next)).toEqual({ reason: "typed", position: "new" });
  });

  it("takes the server value for order boxes", () => {
    const held = { "order-number": "1" };
    const next = form([], [field("order-number", { value: "2" })]);
    expect(mergeFormAfterRefresh(held, next)).toEqual({ "order-number": "2" });
  });

  it("keeps the held value for names listed in keepNames", () => {
    const held = { reason: "typed by user", position: "old" };
    const next = form([field("reason", { value: "server" }), field("position", { value: "new" })]);
    const out = mergeFormAfterRefresh(held, next, new Set(["reason"]));
    expect(out).toEqual({ reason: "typed by user", position: "new" });
  });

  it("drops a box that is no longer in the form", () => {
    const held = { reason: "x", removed: "gone" };
    const next = form([field("reason", { value: "x" })]);
    expect(mergeFormAfterRefresh(held, next)).toEqual({ reason: "x" });
  });

  it("represents a checked checkbox as on and an unchecked one as empty", () => {
    const next = form([
      field("transfer", { kind: "checkbox", checked: true }),
      field("probation", { kind: "checkbox", checked: false }),
    ]);
    expect(mergeFormAfterRefresh({}, next)).toEqual({ transfer: "on", probation: "" });
  });

  it("returns a new record and does not change held", () => {
    const held = { reason: "x" };
    const out = mergeFormAfterRefresh(held, form([field("reason", { value: "y" })]));
    expect(out).not.toBe(held);
    expect(held).toEqual({ reason: "x" });
  });
});

describe("prevEffectiveBase", () => {
  it("returns the server's prev_effective", () => {
    expect(prevEffectiveBase(form([], [], "2026-11-01"))).toBe("2026-11-01");
  });

  it("returns an empty string when the server sends none", () => {
    expect(prevEffectiveBase(form([]))).toBe("");
  });
});
