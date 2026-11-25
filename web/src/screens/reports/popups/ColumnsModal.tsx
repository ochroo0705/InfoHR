import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useColumnsModel, type ReportColumnsModelOut } from "../../../api/reports";
import { Modal } from "../../../widgets/Modal";
import { Select, type SelectOption } from "../../../widgets/Select";
import { applyAddress } from "./applyAddress";
import { COLUMNS_TEXT } from "./popupTexts";

// The «Багана сонгох» pop-up (port of app/reports/templates/reports/_columns_modal.html). The model (the columns the
// user may see, the current picks and grouping, and `keep`) comes from the API; this pop-up writes nothing. Apply
// navigates to the report address with the viewer's `keep` pairs, then cols (one per ticked column, in the order the
// pop-up draws them) and group (absent when «Бүлэглэхгүй»). Classes and texts are copied from the template.

export interface ColumnsModalProps {
  reportKey: string;
  // The address query of the report page (with or without its leading "?").
  query: string;
  onClose: () => void;
}

// The `keep` pairs of the model as [name, value] tuples.
function keepPairs(keep: string[][]): [string, string][] {
  return keep.map(([name = "", value = ""]) => [name, value]);
}

export function ColumnsModal({ reportKey, query, onClose }: ColumnsModalProps) {
  const model = useColumnsModel(reportKey, query, true);
  return (
    <Modal open onClose={onClose} title={COLUMNS_TEXT.title}>
      {model.data !== undefined ? (
        <ColumnsForm reportKey={reportKey} model={model.data} onClose={onClose} />
      ) : model.isError ? (
        <p role="alert" className="text-sm text-red-600">
          {COLUMNS_TEXT.loadFailed}
        </p>
      ) : null}
    </Modal>
  );
}

interface ColumnsFormProps {
  reportKey: string;
  model: ReportColumnsModelOut;
  onClose: () => void;
}

function ColumnsForm({ reportKey, model, onClose }: ColumnsFormProps) {
  const navigate = useNavigate();
  const groupId = useId();
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(model.groups.flatMap((group) => group.picks).filter((pick) => pick.checked).map((pick) => pick.key)),
  );
  const [group, setGroup] = useState(model.group);

  // The current group is listed first when it has a text (as the template does). group_text is set only for a comma
  // group (a multi-key grouping), which is never one of the single-key choices.
  const groupOptions: SelectOption[] = [
    { value: "", label: COLUMNS_TEXT.noGroup },
    ...(model.group_text ? [{ value: model.group, label: model.group_text }] : []),
    ...model.group_choices.map((choice) => ({ value: choice.key, label: choice.label })),
  ];

  const toggle = (key: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    // The columns in the order the pop-up draws them, as the form's checkboxes submit.
    const cols: [string, string][] = model.groups
      .flatMap((g) => g.picks)
      .filter((pick) => checked.has(pick.key))
      .map((pick) => ["cols", pick.key]);
    navigate(applyAddress(reportKey, keepPairs(model.keep), [...cols, ["group", group]]));
    onClose();
  };

  return (
    <form noValidate className="space-y-4" onSubmit={onSubmit}>
      <div className="grid gap-4 md:grid-cols-2">
        {model.groups.map((section) => (
          <fieldset key={section.title} className="text-sm">
            <legend className="mb-1 border-b border-slate-200 pb-1 font-semibold text-slate-800">{section.title}</legend>
            {section.picks.map((pick) => (
              <label key={pick.key} className="flex items-center gap-2 py-0.5">
                <input
                  type="checkbox"
                  name="cols"
                  value={pick.key}
                  checked={checked.has(pick.key)}
                  onChange={() => toggle(pick.key)}
                  // The global checkbox accent of input.css (input[type="checkbox"]), which Django's boxes take.
                  className="rounded border-slate-300 accent-[var(--color-pick-edge)]"
                />
                {pick.label}
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      <div className="block text-sm">
        <label htmlFor={groupId}>{COLUMNS_TEXT.group}</label>
        <Select
          id={groupId}
          name="group"
          value={group}
          onChange={setGroup}
          options={groupOptions}
          className="mt-1 w-full rounded-lg border border-slate-300 py-2 pl-3 pr-8 text-sm"
        />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
        >
          {COLUMNS_TEXT.cancel}
        </button>
        <button type="submit" className="rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700">
          {COLUMNS_TEXT.apply}
        </button>
      </div>
    </form>
  );
}
