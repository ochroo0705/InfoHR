import { useEffect, useState } from "react";
import type { EmployeeHeadOut } from "../../api/employee";
import { useEmployeeWork } from "../../api/employee";
import { ChecklistPanels } from "./ChecklistPanels";
import { LeaveBlock } from "./LeaveBlock";
import { ReportingLine } from "./ReportingLine";
import { SetupCard } from "./SetupCard";
import { WorkFacts } from "./WorkFacts";
import { WorkJobs } from "./WorkJobs";
import { WorkOrders } from "./WorkOrders";

// Port of `employees/_tab_work.html`: the Work tab body, in the order: the setup card (from the header, passed in as
// `setup`), the job and contract facts, the reporting line (the manager chain), the job rows, the waiting and history
// tables, the other orders, the leave block, and the checklist panels. Nothing draws before the Work data arrives (the page's loading bar is the only feedback). A failed
// request shows the section's error line, as the other step-2 screens do.
export function WorkSection({ pk, setup }: { pk: number; setup: EmployeeHeadOut["setup"] }) {
  const query = useEmployeeWork(pk);
  const work = query.data;
  // The order warning is one-shot on the server (GET /work pops it), so a refetch returns "". The first non-empty value
  // is kept for this employee; it is dropped only when the pk changes.
  const incoming = work?.order_warning ?? "";
  const [latch, setLatch] = useState<{ pk: number; text: string }>({ pk, text: "" });
  useEffect(() => {
    if (incoming && (latch.pk !== pk || !latch.text)) setLatch({ pk, text: incoming });
  }, [incoming, pk, latch]);
  const warning = latch.pk === pk && latch.text ? latch.text : incoming;
  return (
    <>
      {query.error ? <p className="mb-3 text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p> : null}
      {work ? (
        <>
          <SetupCard setup={setup} pk={pk} />
          <WorkFacts work={work} />
          <ReportingLine key={pk} pk={pk} />
          <WorkJobs work={work} pk={pk} />
          <WorkOrders work={work} pk={pk} warning={warning} />
          <LeaveBlock work={work} pk={pk} />
          <ChecklistPanels work={work} pk={pk} />
        </>
      ) : null}
    </>
  );
}
