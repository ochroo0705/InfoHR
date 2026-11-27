import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  SELECTION_FAIL_ERROR,
  fetchChecklistForm,
  startChecklists,
  type ReportChecklistFormOut,
  type ReportChecklistResultOut,
} from "../../../api/reports";
import type { ApiFailure } from "../../../api/mutate";
import { Modal } from "../../../widgets/Modal";
import { Select, type SelectOption } from "../../../widgets/Select";
import { DatePicker } from "../../../widgets/DatePicker";
import type { ReportSelection } from "../useReportSelection";

// The «Ажлаас гарах жагсаалт эхлүүлэх» pop-up (port of app/reports/templates/reports/_selection_checklist.html and
// _selection_result.html). The form (count, reasons, anchor limits, whether a template is missing) is read on mount; a
// refused read closes the pop-up through onRefused, and the parent shows the message. The form posts the picked people
// (or the whole report) with the reason and the anchor day; a refused start keeps the form open with every form error;
// a started answer switches to the result list. Texts are copied verbatim from the two templates.

type Body = ReturnType<ReportSelection["body"]>;

// onRefused(message) is called once when the form read is refused. A refused read renders nothing (no pop-up), and the
// PARENT must unmount this component on onRefused; it does not call onClose itself.
export interface SelectionChecklistModalProps {
  reportKey: string;
  query: string;
  selection: ReportSelection;
  onClose: () => void;
  onRefused: (message: string) => void;
}

const TEXT = {
  title: "Ажлаас гарах жагсаалт эхлүүлэх",
  resultTitle: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн",
  allPrefix: "Тайлангийн бүх",
  pickedPrefix: "Сонгосон",
  introRest:
    "«Ажлаас гарах» жагсаалт нэмнэ. Ажлаас аль хэдийн гарсан хүнд, эсвэл нээлттэй жагсаалттай хүнд шинээр жагсаалт нэмэгдэхгүй. Хүн бүрт тусад нь шалгана; нэг нь алдаа гарсан ч бусад нь эхэлнэ.",
  templateMissing: "Энэ төрөлд идэвхтэй загвар алга. Жагсаалт эхлэхгүй.",
  reason: "Шалтгаан",
  noReason: "Шалтгаангүй (үндсэн загвар)",
  reasonHelp: "Шалтгаанд тохирох загвар байвал түүнийг, үгүй бол үндсэн загварыг ашиглана.",
  anchor: "Хугацааны эхлэл *",
  anchorHelp: "Ажилд орох бол ажилд орсон өдөр, ажлаас гарах бол сүүлийн ажлын өдөр.",
  cancel: "Болих",
  start: "Эхлүүлэх",
  close: "Хаах",
  noRows: "Хүн алга.",
  dropped: "хүн энэ тайланд харагдахгүй тул орсонгүй.",
} as const;

const SELECT_CLASS = "mt-1 w-full rounded-lg border border-slate-300 bg-surface py-2 pl-3 pr-8 text-sm";
const DATE_CLASS = "mt-1 w-full rounded-lg border border-slate-300 bg-surface py-2 pl-3 pr-9 text-sm";
const BUTTON_CLASS = "rounded-lg border border-slate-300 px-4 py-2 text-sm";
const PRIMARY_CLASS = "rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700 disabled:opacity-50";

// The messages of a refused answer: every form error, or the error's own message when it has none.
function messagesOf(error: unknown): string[] {
  const formErrors = (error as Partial<ApiFailure> | null)?.formErrors ?? [];
  if (formErrors.length > 0) return formErrors;
  const message = (error as Error | null)?.message;
  return [message || SELECTION_FAIL_ERROR];
}

export function SelectionChecklistModal({
  reportKey,
  query,
  selection,
  onClose,
  onRefused,
}: SelectionChecklistModalProps) {
  const queryClient = useQueryClient();
  const body = selection.body(query);
  const [result, setResult] = useState<ReportChecklistResultOut | null>(null);
  // The form is read once per open: stale at once, not kept after the pop-up closes, never refetched on focus. A React
  // StrictMode double mount shares this query, so the read is not sent twice. Once a result is shown the read is
  // disabled: a re-render would otherwise build the query again after its cache entry was removed, and read it again.
  const formQuery = useQuery({
    queryKey: ["reports", reportKey, "checklist-form", body],
    queryFn: () => fetchChecklistForm(queryClient, reportKey, body),
    enabled: result === null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

  // A refused read is reported once, and only while the form is shown: after a started result, a later read cannot
  // take the result away. The parent takes the pop-up away on onRefused; nothing is drawn here.
  const refusal = formQuery.isError ? messagesOf(formQuery.error).join(" ") : null;
  const reported = useRef(false);
  useEffect(() => {
    if (refusal === null || reported.current || result !== null) return;
    reported.current = true;
    onRefused(refusal);
  }, [refusal, result, onRefused]);

  if (result !== null) return <ResultView result={result} onClose={onClose} />;
  if (refusal !== null) return null;
  if (formQuery.data === undefined) {
    return <Modal open onClose={onClose} title={TEXT.title} titleClass="mb-1 text-lg font-semibold" width="max-w-2xl" />;
  }
  return (
    <FormView
      reportKey={reportKey}
      body={body}
      form={formQuery.data}
      onClose={onClose}
      onDone={setResult}
    />
  );
}

interface FormViewProps {
  reportKey: string;
  body: Body;
  form: ReportChecklistFormOut;
  onClose: () => void;
  onDone: (result: ReportChecklistResultOut) => void;
}

function FormView({ reportKey, body, form, onClose, onDone }: FormViewProps) {
  const queryClient = useQueryClient();
  const reasonId = useId();
  const dateId = useId();
  const [reason, setReason] = useState("");
  const [anchorDay, setAnchorDay] = useState(form.today);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const inFlight = useRef(false);

  const reasonOptions: SelectOption[] = [
    { value: "", label: TEXT.noReason },
    ...form.reasons.map((item) => ({ value: item.value, label: item.label })),
  ];
  const intro = `${form.all ? TEXT.allPrefix : TEXT.pickedPrefix} ${form.count} хүнд ${TEXT.introRest}`;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    let done = false;
    try {
      const outcome = await startChecklists(queryClient, reportKey, { ...body, reason, anchor_day: anchorDay });
      done = true;
      // The form read is no longer needed: drop it first, so the refresh below does not read it again (a refused
      // re-read would not be shown, but it must not be sent). The checklists changed: every report query is stale.
      queryClient.removeQueries({ queryKey: ["reports", reportKey, "checklist-form"] });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      onDone(outcome);
    } catch (error) {
      setFormErrors(messagesOf(error));
    } finally {
      if (!done) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      serverErrors={{ form_errors: formErrors }}
      title={TEXT.title}
      titleClass="mb-1 text-lg font-semibold"
      width="max-w-2xl"
    >
      <form noValidate className="space-y-3" onSubmit={submit}>
        <p className="mb-4 text-sm text-slate-500">{intro}</p>
        {formErrors.length > 0 ? (
          <div role="alert" className="space-y-1 rounded bg-red-50 p-2 text-sm text-red-700">
            {formErrors.map((message, index) => (
              <p key={index}>{message}</p>
            ))}
          </div>
        ) : null}
        {form.template_missing ? (
          <p role="status" className="rounded bg-amber-50 p-2 text-sm text-amber-800">
            {TEXT.templateMissing}
          </p>
        ) : null}
        <div>
          <label htmlFor={reasonId} className="block text-sm">
            {TEXT.reason}
          </label>
          <Select
            id={reasonId}
            name="reason"
            value={reason}
            onChange={setReason}
            options={reasonOptions}
            search={false}
            className={SELECT_CLASS}
          />
          <span className="mt-1 block text-xs text-slate-500">{TEXT.reasonHelp}</span>
        </div>
        <div>
          <label htmlFor={dateId} className="block text-sm">
            {TEXT.anchor}
          </label>
          <DatePicker
            id={dateId}
            name="anchor_day"
            value={anchorDay}
            onChange={setAnchorDay}
            min={form.anchor_min}
            max={form.anchor_max}
            required
            className={DATE_CLASS}
          />
          <span className="mt-1 block text-xs text-slate-500">{TEXT.anchorHelp}</span>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className={BUTTON_CLASS}>
            {TEXT.cancel}
          </button>
          <button type="submit" disabled={pending} className={PRIMARY_CLASS}>
            {TEXT.start}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ResultViewProps {
  result: ReportChecklistResultOut;
  onClose: () => void;
}

function ResultView({ result, onClose }: ResultViewProps) {
  const counts = result.counts;
  const n = (key: string): number => counts[key] ?? 0;
  // The counts line as the template draws it: the first three always, the other three only when non-zero.
  const parts = [
    `Эхэлсэн ${n("started")}`,
    `Нээлттэй байсан ${n("already_open")}`,
    `Загвар алга ${n("no_template")}`,
  ];
  if (n("not_allowed")) parts.push(`Харах эрх алга ${n("not_allowed")}`);
  if (n("left")) parts.push(`Ажлаас гарсан ${n("left")}`);
  if (n("error")) parts.push(`Алдаа гарлаа ${n("error")}`);

  return (
    <Modal open onClose={onClose} title={TEXT.resultTitle} titleClass="mb-2 text-lg font-semibold" width="max-w-2xl">
      <p aria-live="polite" className="mb-3 text-sm text-slate-700">
        {parts.join(" · ")}
      </p>
      {result.dropped > 0 ? (
        <p className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">{`${result.dropped} ${TEXT.dropped}`}</p>
      ) : null}
      <ul className="divide-y divide-slate-100 text-sm">
        {result.rows.map((row, index) => (
          <li
            key={`${row.code}-${index}`}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2"
          >
            <span className="min-w-0 break-words">{`${row.code} ${row.name}`}</span>
            <span className="shrink-0 text-slate-600">{row.outcome}</span>
          </li>
        ))}
        {result.rows.length === 0 ? <li className="py-2 text-sm text-slate-500">{TEXT.noRows}</li> : null}
      </ul>
      <div className="flex justify-end pt-4">
        <button type="button" onClick={onClose} className={PRIMARY_CLASS}>
          {TEXT.close}
        </button>
      </div>
    </Modal>
  );
}
