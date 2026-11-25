import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useFormatModel, type ReportFormatModelOut } from "../../../api/reports";
import { Modal } from "../../../widgets/Modal";
import { Select, type SelectOption } from "../../../widgets/Select";
import { applyAddress } from "./applyAddress";
import { MAX_MARKS, MAX_TEXT, columnOf, firstOpFor, kindOf, type ColumnKind } from "./conditionLogic";
import { BUTTON, SELECT } from "./popupStyles";
import { COLUMNS_TEXT, FORMAT_TEXT } from "./popupTexts";
import { blankMark, marksFromServer, marksJson, totalsText, type Mark } from "./marks";
import { RuleRow } from "./RuleRow";

// The «Хэлбэр» pop-up (port of app/reports/templates/reports/_format_modal.html and its inline script). Three sections:
// the totals of the shown columns, the pinned columns (0 to 3) and the colour rules (at most 5). The model comes from the
// API; this pop-up writes nothing. Apply navigates to the report address with the viewer's `keep` pairs, then totals,
// marks and pin, each absent when empty (pin "0" included).

export interface FormatModalProps {
  reportKey: string;
  // The address query of the report page (with or without its leading "?").
  query: string;
  onClose: () => void;
}

export function FormatModal({ reportKey, query, onClose }: FormatModalProps) {
  const model = useFormatModel(reportKey, query, true);
  return (
    <Modal open onClose={onClose} title={FORMAT_TEXT.title} titleClass="mb-1 text-lg font-semibold">
      {model.data !== undefined ? (
        <FormatForm reportKey={reportKey} model={model.data} onClose={onClose} />
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

// The aggregates offered for a column kind, falling back to the text aggregates (as the script does).
function aggsFor(aggs: Record<string, string[]>, kind: string): string[] {
  return aggs[kind] ?? aggs.text ?? [];
}

// The pinned count as the select shows it: 0 to 3, anything else 0.
function pinText(pin: number): string {
  const n = Number.parseInt(String(pin), 10);
  return n >= 0 && n <= 3 ? String(n) : "0";
}

// Where focus goes after a redraw: the control with this role on the node with this id.
interface Focus {
  role: string;
  id: number;
}

interface FormatState {
  totals: Record<string, string>;
  pin: string;
  marks: Mark[];
}

// The first state: the saved totals of the shown columns (an aggregate the column's kind does not offer shows «—»), the
// pin, and the saved colour rules, cleaned.
function initialState(model: ReportFormatModelOut): FormatState {
  const saved: Record<string, string> = {};
  for (const pair of model.totals) {
    if (pair.length === 2 && pair[0] !== undefined) saved[pair[0]] = pair[1] ?? "";
  }
  const totals: Record<string, string> = {};
  for (const key of model.shown) {
    const column = columnOf(model.columns, key);
    if (!column) continue;
    const offered = aggsFor(model.aggs, column.kind);
    const agg = saved[key] ?? "";
    totals[key] = offered.includes(agg) ? agg : "";
  }
  return {
    totals,
    pin: pinText(model.pin),
    marks: marksFromServer(model.marks, model.columns, model.ops, model.colours),
  };
}

interface FormatFormProps {
  reportKey: string;
  model: ReportFormatModelOut;
  onClose: () => void;
}

function FormatForm({ reportKey, model, onClose }: FormatFormProps) {
  const navigate = useNavigate();
  const { columns, ops, colours, aggs, agg_labels: aggLabels, keep } = model;
  const [init] = useState(() => initialState(model));
  const [totals, setTotals] = useState<Record<string, string>>(init.totals);
  const [pin, setPin] = useState(init.pin);
  const [marks, setMarks] = useState<Mark[]>(init.marks);
  const [error, setError] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  // The focus to give after the next redraw (null: the focused control keeps its focus).
  const wanted = useRef<Focus | null>(null);

  // Focus after the redraw. A row's control is found by its role and uid; a wrapper gives its first input or select.
  useEffect(() => {
    const focus = wanted.current;
    if (!focus) return;
    wanted.current = null;
    const node = formRef.current?.querySelector<HTMLElement>(`[data-role="${focus.role}"][data-id="${focus.id}"]`);
    if (!node) return;
    const control = node.matches("button, select, input")
      ? node
      : (node.querySelector<HTMLElement>("input") ?? node.querySelector<HTMLElement>("select, button"));
    control?.focus();
  });

  // Every edit clears the error line and may ask for a focus after the redraw.
  const commitMarks = (next: Mark[], focus?: Focus) => {
    wanted.current = focus ?? null;
    setMarks(next);
    setError(null);
  };

  const patchMark = (uid: number, patch: Partial<Mark>) =>
    marks.map((mark) => (mark.uid === uid ? { ...mark, ...patch } : mark));

  const setTotal = (key: string, agg: string) => {
    setTotals((prev) => ({ ...prev, [key]: agg }));
    setError(null);
  };

  const setPinValue = (value: string) => {
    setPin(value);
    setError(null);
  };

  const addMark = () => {
    if (marks.length >= MAX_MARKS) return;
    const created = blankMark(columns, ops, colours);
    commitMarks([...marks, created], { role: "col", id: created.uid });
  };

  const removeMark = (index: number) => {
    // Focus moves to the × of the row above, or to the add button when this was the first row.
    const above = index > 0 ? marks[index - 1] : undefined;
    const target: Focus = above ? { role: "remove", id: above.uid } : { role: "add", id: 0 };
    commitMarks(
      marks.filter((_, i) => i !== index),
      target,
    );
  };

  const onApply = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const built = marksJson(marks);
    if (built.tooLong) {
      setError(FORMAT_TEXT.tooLong);
      return;
    }
    if (built.text.length > MAX_TEXT) {
      setError(FORMAT_TEXT.marksTooLong);
      return;
    }
    navigate(
      applyAddress(reportKey, keepPairs(keep), [
        ["totals", totalsText(totals)],
        ["marks", built.text],
        ["pin", pin === "0" ? "" : pin],
      ]),
    );
    onClose();
  };

  const shownColumns: ColumnKind[] = model.shown
    .map((key) => columnOf(columns, key))
    .filter((column): column is ColumnKind => column !== null);
  const pinOptions: SelectOption[] = ["0", "1", "2", "3"].map((value) => ({ value, label: value }));
  const colourOptions: SelectOption[] = colours.map((colour) => ({ value: colour.key, label: colour.label }));
  const full = marks.length >= MAX_MARKS;

  // The subtitle sits outside the form (as in _format_modal.html): its own bottom margin is the gap above the sections,
  // and the form's space-y-6 would otherwise override it.
  return (
    <>
      <p className="mb-4 text-sm text-slate-500">{FORMAT_TEXT.intro}</p>
      <form ref={formRef} noValidate className="space-y-6" onSubmit={onApply}>
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">{FORMAT_TEXT.totals}</h3>
          <p className="text-xs text-slate-500">{FORMAT_TEXT.totalsHint}</p>
          <div className="space-y-2 text-sm">
            {shownColumns.length === 0 ? (
              <p className="text-slate-500">{FORMAT_TEXT.noTotalColumns}</p>
            ) : (
              shownColumns.map((column) => {
                const options: SelectOption[] = [
                  { value: "", label: FORMAT_TEXT.noAggregate },
                  ...aggsFor(aggs, column.kind).map((agg) => ({ value: agg, label: aggLabels[agg] || agg })),
                ];
                return (
                  <div key={column.key} className="flex flex-wrap items-center gap-2">
                    <span className="min-w-40 text-slate-700">{column.label}</span>
                    <Select
                      name={`total-${column.key}`}
                      value={totals[column.key] ?? ""}
                      onChange={(agg) => setTotal(column.key, agg)}
                      options={options}
                      className={SELECT}
                      ariaLabel={column.label}
                    />
                  </div>
                );
              })
            )}
          </div>
        </section>
    
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">{FORMAT_TEXT.pin}</h3>
          <p className="text-xs text-slate-500">{FORMAT_TEXT.pinHint}</p>
          <Select
            name="pin"
            value={pin}
            onChange={setPinValue}
            options={pinOptions}
            className={SELECT}
            ariaLabel={FORMAT_TEXT.pin}
          />
        </section>
    
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">{FORMAT_TEXT.marks}</h3>
          <p className="text-xs text-slate-500">{FORMAT_TEXT.marksHint}</p>
          <div className="space-y-2 text-sm">
            {marks.length === 0 ? <p className="text-slate-500">{FORMAT_TEXT.noMarks}</p> : null}
            {marks.map((mark, index) => {
              const colour = colours.find((item) => item.key === mark.k);
              return (
                <RuleRow
                  key={mark.uid}
                  rule={{ kind: "rule", uid: mark.uid, c: mark.c, o: mark.o, v: mark.v }}
                  columns={columns}
                  ops={ops}
                  onColumn={(key) =>
                    commitMarks(
                      patchMark(mark.uid, { c: key, o: firstOpFor(ops, kindOf(columns, key)), v: "" }),
                      { role: "col", id: mark.uid },
                    )
                  }
                  onOperator={(op) => commitMarks(patchMark(mark.uid, { o: op, v: "" }), { role: "op", id: mark.uid })}
                  onValue={(value) => commitMarks(patchMark(mark.uid, { v: value }))}
                  onRemove={() => removeMark(index)}
                  removeLabel={FORMAT_TEXT.removeMark}
                  trailing={
                    <>
                      <div data-role="colour" data-id={mark.uid}>
                        <Select
                          name={`mark-colour-${mark.uid}`}
                          value={mark.k}
                          onChange={(k) => commitMarks(patchMark(mark.uid, { k }), { role: "colour", id: mark.uid })}
                          options={colourOptions}
                          className={SELECT}
                          ariaLabel={FORMAT_TEXT.colour}
                        />
                      </div>
                      <span className={`rounded px-2 py-1 text-xs ${colour?.classes ?? ""}`}>{colour?.label ?? ""}</span>
                    </>
                  }
                />
              );
            })}
          </div>
          <button
            type="button"
            data-role="add"
            data-id="0"
            disabled={full}
            className={full ? `${BUTTON} opacity-50` : BUTTON}
            onClick={addMark}
          >
            {FORMAT_TEXT.addMark}
          </button>
        </section>
    
        {error ? (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
            {FORMAT_TEXT.cancel}
          </button>
          <button type="submit" className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700">
            {FORMAT_TEXT.apply}
          </button>
        </div>
      </form>
    </>
  );
}
