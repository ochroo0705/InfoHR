import { cn } from "../../lib/utils";

// The status and stage chips of the recruitment pages (app/recruitment/templates/recruitment/_vacancy_status.html and
// _stage_chip.html). The colours are copied from the templates; the labels come from the API. Chips never wrap.

const CHIP = "whitespace-nowrap rounded-full px-2 py-0.5 text-xs";

export interface VacancyStatusChipProps {
  status: string;
  label: string;
}

// open is emerald, filled is sky, every other status (closed) is slate.
export function VacancyStatusChip({ status, label }: VacancyStatusChipProps) {
  const tone =
    status === "open" ? "bg-emerald-100 text-emerald-800" : status === "filled" ? "bg-sky-100 text-sky-800" : "bg-slate-200 text-slate-700";
  return <span className={cn(CHIP, tone)}>{label}</span>;
}

export interface StageChipProps {
  stage: string;
  label: string;
}

// hired emerald, rejected red, withdrawn slate, new sky, every other stage violet.
export function StageChip({ stage, label }: StageChipProps) {
  const tone =
    stage === "hired"
      ? "bg-emerald-100 text-emerald-800"
      : stage === "rejected"
        ? "bg-red-100 text-red-800"
        : stage === "withdrawn"
          ? "bg-slate-200 text-slate-700"
          : stage === "new"
            ? "bg-sky-100 text-sky-800"
            : "bg-violet-100 text-violet-800";
  return <span className={cn(CHIP, tone)}>{label}</span>;
}
