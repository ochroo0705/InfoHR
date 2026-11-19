import type { EmployeeWorkOut } from "../../api/employee";
import type { CorrectionPath } from "../../api/employeeWrites";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ScrollFloat } from "../../widgets/Scrollbar";
import { useCorrectionPopup } from "./CorrectionModal";
import { useEmployeePopups } from "./EmployeePopups";

// Port of the job/changes part of `_tab_work.html`: the «Гарын үсэг хүлээж буй өөрчлөлт» table (waiting rows), then the
// «Ажлын түүх» table (job history). Both headings are included. The setup card, the job and contract facts (WorkFacts),
// the orders block and the leave and checklist blocks are rendered by other parts. Classes, Mongolian text, element
// order and hooks are copied from the templates. React renders only the strings and flags the API sends: `clickable`
// (the row has an order), `order_no_muted` (the grey «—»), `is_cancelled` and `cancellable`. A job row's «Засвар» opens
// the job correction pop-up (CorrectionModal, Task 16a). A row's «Цуцлах» opens the event cancel pop-up (the provider's
// openEventCancel, with the event id from the API). The row click to the order still opens the Django employee page
// (openLegacyEmployee, ruling D2): no fetch.

type Work = EmployeeWorkOut;
type Waiting = Work["waiting"][number];
type Job = Work["jobs"][number];
type Chip = NonNullable<Job["order_chip"]>;

// The «№ N / YYYY» text. The API sends the grey flag for the dash (no order, or an order without a number).
function OrderNo({ text, muted }: { text: string; muted: boolean }) {
  if (muted) return <span className="text-slate-400">{text}</span>;
  return <>{text}</>;
}

// A status chip: the class string comes from Python (`ChipOut.tone`).
function ChipBadge({ chip }: { chip: Chip }) {
  return <span className={chip.tone}>{chip.label}</span>;
}

function rowClass(base: string, clickable: boolean): string {
  return [base, clickable ? "cursor-pointer hover:bg-violet-50" : ""].filter(Boolean).join(" ");
}

function WaitingRow({ row, pk }: { row: Waiting; pk: number }) {
  const { openEventCancel } = useEmployeePopups();
  return (
    <tr
      className={rowClass("", row.clickable)}
      onClick={row.clickable ? () => openLegacyEmployee(pk) : undefined}
    >
      <td>{row.label}</td>
      <td className="whitespace-nowrap">{row.effective}</td>
      <td className="whitespace-nowrap">
        <OrderNo text={row.order_no} muted={row.order_no_muted} />
      </td>
      <td>
        <ChipBadge chip={row.chip} />
      </td>
      <td className="text-right">
        {row.cancellable && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openEventCancel(row.event_pk);
            }}
            className="rounded px-2 py-1 text-red-600 hover:bg-red-50"
          >
            Цуцлах
          </button>
        )}
      </td>
    </tr>
  );
}

function JobRow({
  job,
  pk,
  onCorrect,
}: {
  job: Job;
  pk: number;
  onCorrect: (path: CorrectionPath) => void;
}) {
  const recordId = job.pk;
  const { openEventCancel } = useEmployeePopups();
  return (
    <tr
      className={rowClass(job.is_cancelled ? "text-slate-400 line-through" : "", job.clickable)}
      onClick={job.clickable ? () => openLegacyEmployee(pk) : undefined}
    >
      <td>
        {job.label}
        {job.scheduled && (
          <>
            {" "}
            <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800 no-underline">Төлөвлөсөн</span>
          </>
        )}
      </td>
      <td>{job.position}</td>
      <td>{job.department}</td>
      <td>{job.status}</td>
      <td className="whitespace-nowrap">
        <OrderNo text={job.order_no} muted={job.order_no_muted} />
        {job.cancel_note && (
          <>
            {" "}
            <span className="text-xs no-underline">{job.cancel_note}</span>
          </>
        )}
      </td>
      <td>{job.order_chip && <ChipBadge chip={job.order_chip} />}</td>
      <td className="whitespace-nowrap">
        {job.period_text}
        {job.period_note && (
          <>
            {" "}
            <span className="text-slate-500">{job.period_note}</span>
          </>
        )}
      </td>
      <td className="text-right">
        {!job.is_cancelled && job.cancellable ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (job.event_id !== null) openEventCancel(job.event_id);
            }}
            className="rounded px-2 py-1 text-red-600 hover:bg-red-50"
          >
            Цуцлах
          </button>
        ) : (
          job.correctable && recordId !== null && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onCorrect(`job/${recordId}/correct`);
              }}
              className="text-violet-700 hover:underline"
            >
              Засвар
            </button>
          )
        )}
      </td>
    </tr>
  );
}

export function WorkJobs({ work, pk }: { work: Work; pk: number }) {
  const { openCorrection, correctionModal } = useCorrectionPopup(pk);
  return (
    <>
      {work.waiting.length > 0 && (
        <>
          <h3 className="sec-title mt-10 mb-3">Гарын үсэг хүлээж буй өөрчлөлт</h3>
          <ScrollFloat className="ptable">
            <table>
              <thead>
                <tr>
                  <th>Өөрчлөлт</th>
                  <th>Хүчинтэй огноо</th>
                  <th>Тушаал</th>
                  <th>Төлөв</th>
                  <th className="w-px"></th>
                </tr>
              </thead>
              <tbody>
                {work.waiting.map((row) => (
                  <WaitingRow key={row.event_pk} row={row} pk={pk} />
                ))}
              </tbody>
            </table>
          </ScrollFloat>
        </>
      )}
      <h3 className="sec-title mt-10 mb-3">Ажлын түүх</h3>
      <ScrollFloat className="ptable">
        <table>
          <thead>
            <tr>
              <th>Өөрчлөлт</th>
              <th>Албан тушаал</th>
              <th>Хэлтэс</th>
              <th>Төлөв</th>
              <th>Тушаал</th>
              <th>Тушаалын төлөв</th>
              <th>Хугацаа</th>
              <th className="w-px"></th>
            </tr>
          </thead>
          <tbody>
            {work.jobs.map((job, index) => (
              <JobRow key={job.pk ?? `c${index}`} job={job} pk={pk} onCorrect={openCorrection} />
            ))}
          </tbody>
        </table>
      </ScrollFloat>
      {correctionModal}
    </>
  );
}
