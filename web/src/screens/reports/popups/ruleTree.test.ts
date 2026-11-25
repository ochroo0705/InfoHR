import { beforeEach, describe, expect, it } from "vitest";
import type { ColumnKind, OpOut } from "./conditionLogic";
import {
  addGroup,
  addRule,
  build,
  canAddGroup,
  canAddRule,
  countRules,
  flatten,
  flatAnd,
  fromServer,
  newGroup,
  blankRule,
  removeNode,
  resetUids,
  setColumn,
  setCondition,
  setGroupOp,
  setOperator,
  type GroupNode,
  type TreeNode,
} from "./ruleTree";

const COLUMNS: ColumnKind[] = [
  { key: "name", kind: "text", label: "Нэр" },
  { key: "salary", kind: "number", label: "Цалин" },
  { key: "joined", kind: "date", label: "Элссэн" },
];

const OPS: Record<string, OpOut[]> = {
  text: [
    { code: "contains", label: "агуулсан" },
    { code: "empty", label: "хоосон" },
    { code: "filled", label: "хоосон биш" },
  ],
  number: [
    { code: "eq", label: "тэнцүү" },
    { code: "between", label: "хооронд" },
    { code: "empty", label: "хоосон" },
    { code: "filled", label: "хоосон биш" },
  ],
  date: [
    { code: "next_days", label: "ирэх … хоногт" },
    { code: "between", label: "хооронд" },
    { code: "empty", label: "хоосон" },
    { code: "filled", label: "хоосон биш" },
  ],
};

beforeEach(() => {
  resetUids();
});

function ruleUids(group: GroupNode): number[] {
  return flatten(group).map((r) => r.uid);
}

function firstGroupChild(group: GroupNode): GroupNode {
  const child = group.items.find((item): item is GroupNode => item.kind === "group");
  if (!child) throw new Error("no group child");
  return child;
}

describe("ruleTree", () => {
  it("fromServer_resets_unknown_column_and_operator", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "gone", o: "contains", v: "x" },
        { c: "salary", o: "contains", v: "5" },
        { c: "name", o: "nope", v: "abc" },
      ],
    });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(tree.op).toBe("and");
    const [a, b, c] = tree.items;
    // unknown column → first column; its operator and value are kept because «contains» fits text
    expect(a).toMatchObject({ kind: "rule", c: "name", o: "contains", v: "x" });
    // «contains» is not a number operator → the kind's first operator, value cleared
    expect(b).toMatchObject({ kind: "rule", c: "salary", o: "eq", v: "" });
    // unknown operator → the kind's first operator, value cleared
    expect(c).toMatchObject({ kind: "rule", c: "name", o: "contains", v: "" });
  });

  it("fromServer_empty_or_invalid_text_gives_empty_and_group", () => {
    for (const text of ["", "not json", "null", '{"c":"name","o":"contains","v":"x"}', '{"op":"and"}']) {
      const tree = fromServer(text, COLUMNS, OPS);
      expect(tree).toMatchObject({ kind: "group", op: "and", items: [] });
    }
  });

  it("fromServer_reads_or_group_and_nested_groups", () => {
    const text = JSON.stringify({
      op: "or",
      items: [{ op: "and", items: [{ c: "salary", o: "eq", v: "10" }] }],
    });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(tree.op).toBe("or");
    expect(firstGroupChild(tree).items).toHaveLength(1);
    expect(countRules(tree)).toBe(1);
  });

  it("build_drops_blank_rules_and_empty_groups", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "name", o: "contains", v: "" },
        { c: "name", o: "empty", v: "" },
        { op: "or", items: [{ c: "name", o: "contains", v: "" }] },
        { op: "and", items: [] },
      ],
    });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(build(tree)).toEqual({
      text: '{"op":"and","items":[{"c":"name","o":"empty","v":""}]}',
      tooLong: false,
    });
  });

  it("build_text_is_empty_when_nothing_is_left", () => {
    const tree = fromServer(JSON.stringify({ op: "and", items: [{ c: "name", o: "contains", v: " " }] }), COLUMNS, OPS);
    expect(build(tree)).toEqual({ text: "", tooLong: false });
    expect(build(fromServer("", COLUMNS, OPS))).toEqual({ text: "", tooLong: false });
  });

  it("build_between_needs_one_side", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "salary", o: "between", v: ".." },
        { c: "salary", o: "between", v: "10.." },
        { c: "salary", o: "between", v: "..20" },
      ],
    });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(build(tree).text).toBe(
      '{"op":"and","items":[{"c":"salary","o":"between","v":"10.."},{"c":"salary","o":"between","v":"..20"}]}',
    );
  });

  it("build_flags_value_over_100", () => {
    const long = "a".repeat(101);
    const ok = "a".repeat(100);
    const tooLong = build(fromServer(JSON.stringify({ op: "and", items: [{ c: "name", o: "contains", v: long }] }), COLUMNS, OPS));
    expect(tooLong.tooLong).toBe(true);
    const fine = build(fromServer(JSON.stringify({ op: "and", items: [{ c: "name", o: "contains", v: ok }] }), COLUMNS, OPS));
    expect(fine.tooLong).toBe(false);
  });

  it("build_ignores_long_value_of_empty_operator", () => {
    const text = JSON.stringify({ op: "and", items: [{ c: "name", o: "empty", v: "a".repeat(150) }] });
    expect(build(fromServer(text, COLUMNS, OPS))).toEqual({
      text: '{"op":"and","items":[{"c":"name","o":"empty","v":""}]}',
      tooLong: false,
    });
  });

  it("flatten_collects_nested_rules", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "name", o: "contains", v: "a" },
        { op: "or", items: [{ c: "salary", o: "eq", v: "1" }, { op: "and", items: [{ c: "joined", o: "empty", v: "" }] }] },
        { c: "name", o: "filled", v: "" },
      ],
    });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(flatten(tree).map((r) => r.c + ":" + r.o)).toEqual(["name:contains", "salary:eq", "joined:empty", "name:filled"]);
  });

  it("countRules_counts_nested", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "name", o: "contains", v: "a" },
        { op: "or", items: [{ c: "salary", o: "eq", v: "1" }, { op: "and", items: [{ c: "joined", o: "empty", v: "" }] }] },
      ],
    });
    expect(countRules(fromServer(text, COLUMNS, OPS))).toBe(3);
  });

  it("removeNode_and_addRule_are_immutable", () => {
    const text = JSON.stringify({
      op: "and",
      items: [
        { c: "name", o: "contains", v: "a" },
        { op: "or", items: [{ c: "salary", o: "eq", v: "1" }] },
      ],
    });
    const root = fromServer(text, COLUMNS, OPS);
    const snapshot = JSON.parse(JSON.stringify(root));
    const [firstRule] = root.items;
    const nested = firstGroupChild(root);
    const nestedRuleUid = ruleUids(nested)[0];

    const removed = removeNode(root, firstRule.uid);
    expect(removed).not.toBe(root);
    expect(countRules(removed)).toBe(1);
    expect(JSON.parse(JSON.stringify(root))).toEqual(snapshot);

    const removedNested = removeNode(root, nestedRuleUid);
    expect(countRules(removedNested)).toBe(1);
    expect(JSON.parse(JSON.stringify(root))).toEqual(snapshot);

    const added = addRule(root, root.uid, blankRule(COLUMNS, OPS));
    expect(countRules(added)).toBe(3);
    expect(countRules(root)).toBe(2);
    expect(JSON.parse(JSON.stringify(root))).toEqual(snapshot);

    const addedNested = addRule(root, nested.uid, blankRule(COLUMNS, OPS));
    expect(firstGroupChild(addedNested).items).toHaveLength(2);
    expect(firstGroupChild(root).items).toHaveLength(1);
  });

  it("removeNode_drops_whole_group_and_never_removes_root", () => {
    const root = fromServer(
      JSON.stringify({ op: "and", items: [{ op: "or", items: [{ c: "name", o: "contains", v: "a" }, { c: "name", o: "contains", v: "b" }] }] }),
      COLUMNS,
      OPS,
    );
    const group = firstGroupChild(root);
    const without = removeNode(root, group.uid);
    expect(without.items).toHaveLength(0);
    expect(removeNode(root, root.uid)).toBe(root);
  });

  it("setColumn_resets_operator_and_value", () => {
    const root = fromServer(JSON.stringify({ op: "and", items: [{ c: "name", o: "contains", v: "x" }] }), COLUMNS, OPS);
    const uid = ruleUids(root)[0];
    const changed = setColumn(root, uid, "salary", COLUMNS, OPS);
    expect(flatten(changed)[0]).toMatchObject({ c: "salary", o: "eq", v: "" });
    expect(flatten(root)[0]).toMatchObject({ c: "name", o: "contains", v: "x" });
  });

  it("setOperator_and_setCondition_and_setGroupOp_change_only_their_node", () => {
    const root = fromServer(JSON.stringify({ op: "and", items: [{ c: "salary", o: "eq", v: "1" }] }), COLUMNS, OPS);
    const uid = ruleUids(root)[0];
    expect(flatten(setOperator(root, uid, "between"))[0]).toMatchObject({ o: "between", v: "" });
    expect(flatten(setCondition(root, uid, { v: "5" }))[0]).toMatchObject({ o: "eq", v: "5" });
    expect(setGroupOp(root, root.uid, "or").op).toBe("or");
    expect(root.op).toBe("and");
  });

  it("flatAnd_turns_nested_tree_into_one_and_group", () => {
    const root = fromServer(
      JSON.stringify({ op: "or", items: [{ c: "name", o: "contains", v: "a" }, { op: "and", items: [{ c: "salary", o: "eq", v: "1" }] }] }),
      COLUMNS,
      OPS,
    );
    const flat = flatAnd(root);
    expect(flat.op).toBe("and");
    expect(flat.items.every((item: TreeNode) => item.kind === "rule")).toBe(true);
    expect(flat.items).toHaveLength(2);
  });

  it("canAddRule_stops_at_20_rules", () => {
    const rules = Array.from({ length: 20 }, () => ({ c: "name", o: "contains", v: "a" }));
    const full = fromServer(JSON.stringify({ op: "and", items: rules }), COLUMNS, OPS);
    expect(countRules(full)).toBe(20);
    expect(canAddRule(full)).toBe(false);

    const nineteen = fromServer(JSON.stringify({ op: "and", items: rules.slice(1) }), COLUMNS, OPS);
    expect(canAddRule(nineteen)).toBe(true);
  });

  it("canAddGroup_stops_at_depth_3", () => {
    const text = JSON.stringify({
      op: "and",
      items: [{ op: "or", items: [{ op: "and", items: [{ c: "name", o: "contains", v: "a" }] }] }],
    });
    const root = fromServer(text, COLUMNS, OPS);
    const depth2 = firstGroupChild(root);
    const depth3 = firstGroupChild(depth2);
    expect(canAddGroup(root, root.uid)).toBe(true);
    expect(canAddGroup(root, depth2.uid)).toBe(true);
    expect(canAddGroup(root, depth3.uid)).toBe(false);
    expect(canAddGroup(root, 999999)).toBe(false);
  });

  it("canAddGroup_is_false_at_20_rules", () => {
    const rules = Array.from({ length: 20 }, () => ({ c: "name", o: "contains", v: "a" }));
    const root = fromServer(JSON.stringify({ op: "and", items: rules }), COLUMNS, OPS);
    expect(canAddGroup(root, root.uid)).toBe(false);
  });

  it("newGroup_and_addGroup_add_a_blank_nested_group", () => {
    const root = fromServer("", COLUMNS, OPS);
    const group = newGroup(COLUMNS, OPS);
    const next = addGroup(root, root.uid, group);
    expect(next.items).toHaveLength(1);
    expect(firstGroupChild(next).items).toHaveLength(1);
    expect(countRules(next)).toBe(1);
    expect(build(next).text).toBe("");
  });

  it("flatAnd_leaves_old_tree_unchanged", () => {
    const text = JSON.stringify({
      op: "or",
      items: [{ c: "name", o: "contains", v: "a" }, { op: "and", items: [{ c: "salary", o: "eq", v: "1" }] }],
    });
    const root = fromServer(text, COLUMNS, OPS);
    const snapshot = JSON.parse(JSON.stringify(root));
    const flat = flatAnd(root);
    expect(flat).not.toBe(root);
    expect(JSON.parse(JSON.stringify(root))).toEqual(snapshot);
    expect(root.op).toBe("or");
  });

  it("fromServer_skips_non_object_children", () => {
    const text = JSON.stringify({ op: "and", items: [null, 5, "x", { c: "name", o: "contains", v: "a" }] });
    const tree = fromServer(text, COLUMNS, OPS);
    expect(tree.items).toHaveLength(1);
    expect(countRules(tree)).toBe(1);
    expect(flatten(tree)[0]).toMatchObject({ c: "name", o: "contains", v: "a" });
  });

  it("blankRule_with_empty_columns_gives_empty_column", () => {
    const rule = blankRule([], OPS);
    expect(rule).toMatchObject({ kind: "rule", c: "", o: "contains", v: "" });
  });
});
