import { Fragment } from "react";
import type { ReportGroupOut } from "../../api/reports";
import { inlineStyle, ReportCell } from "./ReportCell";
import type { CheckColumn } from "./HeaderRow";

// The body rows of a report table (_rows.html, and the heading row of _table.html for a grouped table). A grouped table
// draws a heading «label · count» over its rows; an ungrouped one draws its rows only. Both come from the API's groups.

export function ReportRows({
  groups,
  grouped,
  tableSpan,
  check = null,
}: {
  groups: ReportGroupOut[];
  grouped: boolean;
  tableSpan: number;
  check?: CheckColumn | null;
}) {
  return (
    <>
      {groups.map((group, groupIndex) => (
        <Fragment key={groupIndex}>
          {grouped ? (
            <tr>
              <td colSpan={tableSpan} className="font-semibold text-slate-900">
                {group.label} · {group.count}
              </td>
            </tr>
          ) : null}
          {group.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {check ? <td className={check.css || undefined} style={inlineStyle(check.style)} /> : null}
              {row.map((cell, cellIndex) => (
                <ReportCell key={cellIndex} cell={cell} />
              ))}
            </tr>
          ))}
        </Fragment>
      ))}
    </>
  );
}
