import type { ReactNode } from "react";
import { DatePicker } from "../../../widgets/DatePicker";
import { Select, type SelectOption } from "../../../widgets/Select";
import { MAX_VALUE, inputKind, isDays, kindOf, opText, opsFor, type ColumnKind, type OpOut } from "./conditionLogic";
import { INPUT, REMOVE, SELECT } from "./popupStyles";
import { RULES_TEXT } from "./popupTexts";
import type { RuleNode } from "./ruleTree";

// One condition row of the rules pop-up (the row markup of _rules_modal.html): column, operator, the value box or the
// two «between» boxes, the «хоног» word after a days operator, and the × button. The focus tags (data-role, data-id)
// sit on the column and operator wrappers and on the ×, so RulesModal can give focus back after a redraw.

export interface RuleRowProps {
  rule: RuleNode;
  columns: ColumnKind[];
  ops: Record<string, OpOut[]>;
  onColumn: (key: string) => void;
  onOperator: (op: string) => void;
  // The whole value text («a..b» for «между»).
  onValue: (value: string) => void;
  onRemove: () => void;
  // Optional, drawn after the value boxes and before the ×: the «Хэлбэр» pop-up's colour select and swatch.
  trailing?: ReactNode;
  // The × button's aria-label. Unset: «Нөхцөл устгах» (the rules pop-up's text).
  removeLabel?: string;
}

export function RuleRow({
  rule,
  columns,
  ops,
  onColumn,
  onOperator,
  onValue,
  onRemove,
  trailing,
  removeLabel = RULES_TEXT.removeRule,
}: RuleRowProps) {
  const kind = kindOf(columns, rule.c);
  const colOptions: SelectOption[] = columns.map((column) => ({ value: column.key, label: column.label }));
  const opOptions: SelectOption[] = opsFor(ops, kind).map((op) => ({ value: op.code, label: opText(op.label) }));
  const valueless = rule.o === "empty" || rule.o === "filled";
  const between = rule.o === "between";
  const days = isDays(rule.o);
  const parts = rule.v.split("..");

  // Changes one side of a «между» value and keeps the other side.
  const setSide = (side: 0 | 1, text: string) => {
    const sides = [parts[0] ?? "", parts[1] ?? ""];
    sides[side] = text;
    onValue(`${sides[0]}..${sides[1]}`);
  };

  // A value box: a date box for a date column (DatePicker, not <input type="date">), otherwise a number, text or days box.
  const valueBox = (label: string, value: string, change: (text: string) => void) => {
    if (!days && inputKind(kind) === "date") {
      return <DatePicker name="rule-value" value={value} onChange={change} ariaLabel={label} className={INPUT} />;
    }
    const type = days ? "number" : inputKind(kind);
    return (
      <input
        type={type}
        aria-label={label}
        value={value}
        onChange={(e) => change(e.target.value)}
        className={days ? `${INPUT} w-28` : INPUT}
        min={days ? 0 : undefined}
        step={days ? 1 : type === "number" ? "any" : undefined}
        maxLength={type === "text" ? MAX_VALUE : undefined}
      />
    );
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div data-role="col" data-id={rule.uid}>
        <Select
          name="rule-col"
          value={rule.c}
          onChange={onColumn}
          options={colOptions}
          className={SELECT}
          ariaLabel={RULES_TEXT.column}
        />
      </div>
      <div data-role="op" data-id={rule.uid}>
        <Select
          name="rule-op"
          value={rule.o}
          onChange={onOperator}
          options={opOptions}
          className={SELECT}
          ariaLabel={RULES_TEXT.operator}
        />
      </div>
      {between ? (
        <>
          {valueBox(RULES_TEXT.from, parts[0] ?? "", (text) => setSide(0, text))}
          <span className="text-slate-500">–</span>
          {valueBox(RULES_TEXT.to, parts[1] ?? "", (text) => setSide(1, text))}
        </>
      ) : valueless ? null : (
        valueBox(RULES_TEXT.value, rule.v, onValue)
      )}
      {!valueless && !between && days ? <span className="text-slate-500">{RULES_TEXT.days}</span> : null}
      {trailing}
      <button
        type="button"
        data-role="remove"
        data-id={rule.uid}
        aria-label={removeLabel}
        className={REMOVE}
        onClick={onRemove}
      >
        ×
      </button>
    </div>
  );
}
