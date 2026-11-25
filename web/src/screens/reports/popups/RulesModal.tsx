import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useRulesModel, type ReportRulesModelOut } from "../../../api/reports";
import { confirm } from "../../../widgets/confirm";
import { Modal } from "../../../widgets/Modal";
import { applyAddress } from "./applyAddress";
import { MAX_DEPTH, MAX_TEXT } from "./conditionLogic";
import { COLUMNS_TEXT, RULES_TEXT } from "./popupTexts";
import { BUTTON, REMOVE, SELECT } from "./popupStyles";
import { RuleRow } from "./RuleRow";
import {
  addGroup,
  addRule,
  blankRule,
  build,
  canAddRule,
  countRules,
  findParent,
  flatAnd,
  fromServer,
  isFlat,
  newGroup,
  removeNode,
  setColumn,
  setCondition,
  setGroupOp,
  setOperator,
  type GroupNode,
} from "./ruleTree";

// The «Шүүлтүүр» pop-up (port of app/reports/templates/reports/_rules_modal.html and its inline script). The model (the
// columns, the operators, the current rules text and `keep`) comes from the API; this pop-up writes nothing. Apply
// navigates to the report address with the viewer's `keep` pairs, then rules (absent when there are no rules).

export interface RulesModalProps {
  reportKey: string;
  // The address query of the report page (with or without its leading "?").
  query: string;
  onClose: () => void;
}

export function RulesModal({ reportKey, query, onClose }: RulesModalProps) {
  const model = useRulesModel(reportKey, query, true);
  return (
    <Modal open onClose={onClose} title={RULES_TEXT.title} titleClass="mb-1 text-lg font-semibold">
      {model.data !== undefined ? (
        <RulesForm reportKey={reportKey} model={model.data} onClose={onClose} />
      ) : model.isError ? (
        <p role="alert" className="text-sm text-red-600">
          {COLUMNS_TEXT.loadFailed}
        </p>
      ) : null}
    </Modal>
  );
}

// The `keep` pairs of the model as [name, value] tuples.
function keepPairs(keep: string[][]): [string, string][] {
  return keep.map(([name = "", value = ""]) => [name, value]);
}

// Where focus goes after a redraw: the control with this role on the node with this uid.
interface Focus {
  role: string;
  id: number;
}


// The first tree: the saved rules, cleaned. An empty flat tree gets one blank rule. «Нарийвчилсан» starts on when the
// tree is nested.
function initialTree(model: ReportRulesModelOut): { root: GroupNode; advanced: boolean } {
  let root = fromServer(model.rules, model.columns, model.ops);
  if (isFlat(root) && root.items.length === 0) root = addRule(root, root.uid, blankRule(model.columns, model.ops));
  return { root, advanced: !isFlat(root) };
}

interface RulesFormProps {
  reportKey: string;
  model: ReportRulesModelOut;
  onClose: () => void;
}

function RulesForm({ reportKey, model, onClose }: RulesFormProps) {
  const navigate = useNavigate();
  const [init] = useState(() => initialTree(model));
  const [root, setRoot] = useState<GroupNode>(init.root);
  const [advanced, setAdvanced] = useState(init.advanced);
  const [error, setError] = useState<string | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);
  // The focus to give after the next redraw (null: the focused control keeps its focus).
  const wanted = useRef<Focus | null>(null);
  const { columns, ops } = model;

  // Focus after the redraw. A rule row's control is found by its role and uid; a wrapper gives its first input or select.
  useEffect(() => {
    const focus = wanted.current;
    if (!focus) return;
    wanted.current = null;
    const node = treeRef.current?.querySelector<HTMLElement>(`[data-role="${focus.role}"][data-id="${focus.id}"]`);
    if (!node) return;
    const control = node.matches("button, select, input")
      ? node
      : (node.querySelector<HTMLElement>("input") ?? node.querySelector<HTMLElement>("select, button"));
    control?.focus();
  });

  // Every edit clears the error line and may ask for a focus after the redraw.
  const commit = (next: GroupNode, focus?: Focus) => {
    wanted.current = focus ?? null;
    setRoot(next);
    setError(null);
  };

  const onAdvanced = async (checked: boolean) => {
    setError(null);
    if (checked) {
      setAdvanced(true);
      return;
    }
    if (isFlat(root)) {
      setAdvanced(false);
      return;
    }
    // Cancelled: the checkbox stays on (it is controlled, so React puts it back).
    const ok = await confirm(RULES_TEXT.advancedOffConfirm, { ok: RULES_TEXT.advancedOffOk });
    if (!ok) return;
    setAdvanced(false);
    setRoot((prev) => flatAnd(prev));
  };

  const dropGroup = async (group: GroupNode) => {
    const parent = findParent(root, group.uid);
    if (!parent) return;
    // The whole subtree counts: a group holding one subgroup of many rules is asked about too.
    if (countRules(group) >= 2) {
      const ok = await confirm(RULES_TEXT.dropGroupConfirm, { ok: RULES_TEXT.dropGroupOk });
      if (!ok) return;
    }
    wanted.current = { role: "add-rule", id: parent.uid };
    setRoot((prev) => removeNode(prev, group.uid));
    setError(null);
  };

  const removeRule = (group: GroupNode, index: number) => {
    const rule = group.items[index];
    if (!rule) return;
    // Focus moves to the × of the row above, or to the group's add-rule button when this was the first item.
    const above = index > 0 ? group.items[index - 1] : undefined;
    const target: Focus =
      above && above.kind === "rule" ? { role: "remove", id: above.uid } : { role: "add-rule", id: group.uid };
    commit(removeNode(root, rule.uid), target);
  };

  const onApply = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const built = build(root);
    if (built.tooLong) {
      setError(RULES_TEXT.tooLong);
      return;
    }
    if (built.text.length > MAX_TEXT) {
      setError(RULES_TEXT.ruleTooLong);
      return;
    }
    const keep = keepPairs(model.keep);
    navigate(applyAddress(reportKey, keep, built.text ? [["rules", built.text]] : []));
    onClose();
  };

  const groupOp = (group: GroupNode): ReactNode => (
    <select
      data-role="group-op"
      data-id={group.uid}
      aria-label={RULES_TEXT.groupOpAria}
      className={SELECT}
      value={group.op}
      onChange={(e) => commit(setGroupOp(root, group.uid, e.target.value === "or" ? "or" : "and"), { role: "group-op", id: group.uid })}
    >
      <option value="and">{RULES_TEXT.groupOpAll}</option>
      <option value="or">{RULES_TEXT.groupOpAny}</option>
    </select>
  );

  // One group box: its head (nested or root, in advanced mode), its items, and its add buttons. depth: the root is 1.
  const renderGroup = (group: GroupNode, depth: number, isRoot: boolean): ReactNode => {
    const ruleOk = canAddRule(root);
    const addGroupOk = depth < MAX_DEPTH;
    return (
      <div
        key={group.uid}
        className={isRoot ? "space-y-2" : "space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3"}
      >
        {advanced && !isRoot ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-500">{RULES_TEXT.groupLabel}</span>
            {groupOp(group)}
            <button
              type="button"
              data-role="group-drop"
              data-id={group.uid}
              className={REMOVE}
              onClick={() => void dropGroup(group)}
            >
              {RULES_TEXT.dropGroup}
            </button>
          </div>
        ) : advanced && isRoot ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-500">{RULES_TEXT.rootLabel}</span>
            {groupOp(group)}
          </div>
        ) : null}
        {group.items.map((item, index) =>
          item.kind === "rule" ? (
            <RuleRow
              key={item.uid}
              rule={item}
              columns={columns}
              ops={ops}
              onColumn={(key) => commit(setColumn(root, item.uid, key, columns, ops), { role: "col", id: item.uid })}
              onOperator={(op) => commit(setOperator(root, item.uid, op), { role: "op", id: item.uid })}
              onValue={(value) => commit(setCondition(root, item.uid, { v: value }))}
              onRemove={() => removeRule(group, index)}
            />
          ) : (
            renderGroup(item, depth + 1, false)
          ),
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-role="add-rule"
            data-id={group.uid}
            disabled={!ruleOk}
            className={ruleOk ? BUTTON : `${BUTTON} opacity-50`}
            onClick={() => {
              const created = blankRule(columns, ops);
              commit(addRule(root, group.uid, created), { role: "col", id: created.uid });
            }}
          >
            {RULES_TEXT.addRule}
          </button>
          {advanced && addGroupOk ? (
            <button
              type="button"
              data-role="add-group"
              data-id={group.uid}
              disabled={!ruleOk}
              className={ruleOk ? BUTTON : `${BUTTON} opacity-50`}
              onClick={() => {
                const created = newGroup(columns, ops);
                commit(addGroup(root, group.uid, created), { role: "col", id: created.items[0]?.uid ?? created.uid });
              }}
            >
              {RULES_TEXT.addGroup}
            </button>
          ) : null}
        </div>
      </div>
    );
  };

  return (
    <form noValidate className="space-y-4" onSubmit={onApply}>
      <p className="text-sm text-slate-500">{RULES_TEXT.intro}</p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={advanced}
          onChange={(e) => void onAdvanced(e.target.checked)}
          className="rounded border-slate-300"
        />
        {RULES_TEXT.advanced}
      </label>
      <div ref={treeRef} className="space-y-3 text-sm">
        {renderGroup(root, 1, true)}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
          {RULES_TEXT.cancel}
        </button>
        <button type="submit" className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700">
          {RULES_TEXT.apply}
        </button>
      </div>
    </form>
  );
}
