import {
  MAX_DEPTH,
  MAX_RULES,
  MAX_VALUE,
  firstOpFor,
  kindOf,
  ruleReady,
  sanitizeCondition,
  type ColumnKind,
  type Condition,
  type OpOut,
} from "./conditionLogic";

// The rules pop-up's condition tree (ported from the inline script of _rules_modal.html). Pure: nothing here touches the
// DOM. Every edit helper returns a new tree and leaves the old one unchanged, so React state can hold the tree.

export type RuleNode = { kind: "rule"; uid: number } & Condition;
export type GroupNode = { kind: "group"; uid: number; op: "and" | "or"; items: TreeNode[] };
export type TreeNode = RuleNode | GroupNode;

type Ops = Record<string, OpOut[]>;

// The uid counter. Each node made here gets the next number. resetUids() restarts it (tests use it for determinism).
let uidSeq = 0;

function nextUid(): number {
  uidSeq += 1;
  return uidSeq;
}

export function resetUids(): void {
  uidSeq = 0;
}

// A new rule on the first column with that column's first operator and an empty value (the script's blankRule).
export function blankRule(columns: ColumnKind[], ops: Ops): RuleNode {
  const c = columns.length ? columns[0].key : "";
  return { kind: "rule", uid: nextUid(), c, o: firstOpFor(ops, kindOf(columns, c)), v: "" };
}

// A new «and» group holding one blank rule (the script's «+ Бүлэг нэмэх»).
export function newGroup(columns: ColumnKind[], ops: Ops): GroupNode {
  const uid = nextUid();
  return { kind: "group", uid, op: "and", items: [blankRule(columns, ops)] };
}

function emptyRoot(): GroupNode {
  return { kind: "group", uid: nextUid(), op: "and", items: [] };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

// A loaded rule is cleaned the way sanitizeCondition cleans it (an unknown column or operator is reset).
function parseRule(raw: Record<string, unknown>, columns: ColumnKind[], ops: Ops): RuleNode {
  const uid = nextUid();
  const cond = sanitizeCondition(
    {
      c: raw.c === undefined || raw.c === null ? "" : String(raw.c),
      o: raw.o === undefined || raw.o === null ? "" : String(raw.o),
      v: raw.v === undefined || raw.v === null ? "" : String(raw.v),
    },
    columns,
    ops,
  );
  return { kind: "rule", uid, ...cond };
}

function parseGroup(raw: Record<string, unknown>, columns: ColumnKind[], ops: Ops): GroupNode {
  const uid = nextUid();
  const op = raw.op === "or" ? "or" : "and";
  const items: TreeNode[] = [];
  for (const child of raw.items as unknown[]) {
    if (!isObject(child)) continue;
    items.push(Array.isArray(child.items) ? parseGroup(child, columns, ops) : parseRule(child, columns, ops));
  }
  return { kind: "group", uid, op, items };
}

// The model's `rules` text (a JSON string) as a cleaned tree. Empty, invalid or non-group text gives an empty «and»
// group. Unknown columns and operators are reset here.
export function fromServer(text: string, columns: ColumnKind[], ops: Ops): GroupNode {
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  if (!isObject(parsed) || !Array.isArray(parsed.items)) return emptyRoot();
  return parseGroup(parsed, columns, ops);
}

// True when the tree is one «and» group of plain rules (the simple view; the «Нарийвчилсан» box is off).
export function isFlat(group: GroupNode): boolean {
  return group.op === "and" && group.items.every((item) => item.kind === "rule");
}

// The number of rules at any depth.
export function countRules(group: GroupNode): number {
  return group.items.reduce((n, item) => n + (item.kind === "rule" ? 1 : countRules(item)), 0);
}

// Every rule at any depth, in order.
export function flatten(group: GroupNode): RuleNode[] {
  const out: RuleNode[] = [];
  for (const item of group.items) {
    if (item.kind === "rule") out.push(item);
    else out.push(...flatten(item));
  }
  return out;
}

// The whole tree as one «and» group of its rules (what turning «Нарийвчилсан» off does after the user confirms).
export function flatAnd(group: GroupNode): GroupNode {
  return { kind: "group", uid: group.uid, op: "and", items: flatten(group) };
}

// The group that holds the node with this uid, or null (the root has no parent).
export function findParent(group: GroupNode, uid: number): GroupNode | null {
  for (const item of group.items) {
    if (item.uid === uid) return group;
    if (item.kind === "group") {
      const found = findParent(item, uid);
      if (found) return found;
    }
  }
  return null;
}

// The depth of the group with this uid (the root is depth 1), or 0 when it is not in the tree.
export function depthOf(group: GroupNode, uid: number): number {
  if (group.uid === uid) return 1;
  for (const item of group.items) {
    if (item.kind === "group") {
      const d = depthOf(item, uid);
      if (d > 0) return d + 1;
    }
  }
  return 0;
}

// A rule may be added while the tree holds fewer than 20 rules.
export function canAddRule(root: GroupNode): boolean {
  return countRules(root) < MAX_RULES;
}

// A group may be added inside the group with this uid when the tree has room for a rule, and that group sits above the
// depth limit (a group at depth 3 gets no «+ Бүлэг нэмэх», as the script).
export function canAddGroup(root: GroupNode, groupUid: number): boolean {
  const depth = depthOf(root, groupUid);
  return depth > 0 && depth < MAX_DEPTH && canAddRule(root);
}

// Replaces the group with this uid by edit(group). Untouched branches are shared, not copied. Returns the same tree
// when the uid is not a group in it.
function editGroup(group: GroupNode, uid: number, edit: (g: GroupNode) => GroupNode): GroupNode {
  if (group.uid === uid) return edit(group);
  let changed = false;
  const items = group.items.map((item) => {
    if (item.kind === "rule") return item;
    const next = editGroup(item, uid, edit);
    if (next !== item) changed = true;
    return next;
  });
  return changed ? { ...group, items } : group;
}

// Replaces the rule with this uid by edit(rule). Returns the same tree when the uid is not a rule in it.
function editRule(group: GroupNode, uid: number, edit: (r: RuleNode) => RuleNode): GroupNode {
  let changed = false;
  const items = group.items.map((item) => {
    const next = item.kind === "rule" ? (item.uid === uid ? edit(item) : item) : editRule(item, uid, edit);
    if (next !== item) changed = true;
    return next;
  });
  return changed ? { ...group, items } : group;
}

// Appends a rule to the group with groupUid.
export function addRule(root: GroupNode, groupUid: number, rule: RuleNode): GroupNode {
  return editGroup(root, groupUid, (g) => ({ ...g, items: [...g.items, rule] }));
}

// Appends a group to the group with parentUid.
export function addGroup(root: GroupNode, parentUid: number, group: GroupNode): GroupNode {
  return editGroup(root, parentUid, (g) => ({ ...g, items: [...g.items, group] }));
}

// Removes the rule or group with this uid, with everything inside a group. The root cannot be removed.
export function removeNode(root: GroupNode, uid: number): GroupNode {
  if (root.uid === uid) return root;
  let changed = false;
  const items: TreeNode[] = [];
  for (const item of root.items) {
    if (item.uid === uid) {
      changed = true;
      continue;
    }
    if (item.kind === "group") {
      const next = removeNode(item, uid);
      if (next !== item) changed = true;
      items.push(next);
    } else {
      items.push(item);
    }
  }
  return changed ? { ...root, items } : root;
}

// Changes the value and/or operator parts of one rule (a value edit).
export function setCondition(root: GroupNode, ruleUid: number, patch: Partial<Condition>): GroupNode {
  return editRule(root, ruleUid, (r) => ({ ...r, ...patch }));
}

// A column change: the operator becomes the new column's first operator and the value is cleared (as the script).
export function setColumn(
  root: GroupNode,
  ruleUid: number,
  key: string,
  columns: ColumnKind[],
  ops: Ops,
): GroupNode {
  return editRule(root, ruleUid, (r) => ({ ...r, c: key, o: firstOpFor(ops, kindOf(columns, key)), v: "" }));
}

// An operator change: the value is cleared (as the script).
export function setOperator(root: GroupNode, ruleUid: number, op: string): GroupNode {
  return editRule(root, ruleUid, (r) => ({ ...r, o: op, v: "" }));
}

// The «И» / «Аль нэг нь» choice of a group.
export function setGroupOp(root: GroupNode, groupUid: number, op: "and" | "or"): GroupNode {
  return editGroup(root, groupUid, (g) => ({ ...g, op }));
}

// Output of build(): blank rules and empty groups are left out.
type OutRule = { c: string; o: string; v: string };
type OutGroup = { op: "and" | "or"; items: Array<OutRule | OutGroup> };

// The tree the server reads, as the text of the `rules` parameter. text is "" when nothing is left. tooLong is set when
// a ready rule's value is over 100 characters. The caller checks the 2000-character text limit on text.
export function build(group: GroupNode): { text: string; tooLong: boolean } {
  let tooLong = false;
  const walk = (g: GroupNode): OutGroup | null => {
    const items: Array<OutRule | OutGroup> = [];
    for (const item of g.items) {
      if (item.kind === "rule") {
        if (!ruleReady(item)) continue;
        const value = item.o === "empty" || item.o === "filled" ? "" : item.v;
        if (value.length > MAX_VALUE) tooLong = true;
        items.push({ c: item.c, o: item.o, v: value });
      } else {
        const sub = walk(item);
        if (sub) items.push(sub);
      }
    }
    return items.length ? { op: g.op, items } : null;
  };
  const built = walk(group);
  return { text: built ? JSON.stringify(built) : "", tooLong };
}
