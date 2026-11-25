import type { components } from "../../api/schema";
import { cn } from "../../lib/utils";
import { TLink } from "../../lib/viewTransition";

// The header of a report page (app/reports/templates/reports/report.html and _switcher.html): the title, then the view
// switcher. The switcher is drawn only when the report offers two or more layouts (as the template). Each segment is an
// in-app link to that layout's address of the same report.

type ReportLayoutOut = components["schemas"]["ReportLayoutOut"];

export interface ReportHeaderProps {
  title: string;
  layouts: ReportLayoutOut[];
}

export function ReportHeader({ title, layouts }: ReportHeaderProps) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
      <h1 className="text-xl font-semibold">{title}</h1>
      {layouts.length > 1 ? (
        <div className="max-w-full overflow-x-auto">
          <div
            role="group"
            aria-label="Харагдац"
            className="inline-flex shrink-0 divide-x divide-slate-300 overflow-hidden rounded-lg border border-slate-300 bg-surface text-sm [&>*]:px-4 [&>*]:py-2 [&>*:hover]:bg-slate-50"
          >
            {layouts.map((option) => (
              <TLink
                key={option.name}
                to={option.url}
                className={cn("whitespace-nowrap", option.current && "is-picked font-semibold")}
                aria-current={option.current ? "page" : undefined}
              >
                {option.label}
              </TLink>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
