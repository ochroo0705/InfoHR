import { Fragment } from "react";
import type { LogChangeOut } from "../../api/logs";

// The changes of a log entry (_employee_rows.html and system.html): one row per change, the old value struck through and
// an arrow to the new one. An empty new value reads «(хоосон)». Nothing is drawn for an entry without changes.
export function ChangeList({ changes }: { changes: LogChangeOut[] }) {
  if (changes.length === 0) return null;
  return (
    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {changes.map((change, index) => (
        <Fragment key={`${change.field}-${index}`}>
          <dt className="text-slate-500">{change.field}</dt>
          <dd className="text-slate-800">
            {change.old && (
              <>
                <s className="text-slate-400">{change.old}</s>
                {" → "}
              </>
            )}
            {change.new || "(хоосон)"}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
