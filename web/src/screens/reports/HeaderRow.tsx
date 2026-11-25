import type { ReportHeadCellOut } from "../../api/reports";
import { useTransitionNavigate, TLink } from "../../lib/viewTransition";
import { inlineStyle } from "./ReportCell";

// The head row of a report table (_table.html <tr> in <thead>). Labels, sort addresses, arrows, classes and the pinned
// offset all come from the API. A plain click sorts in place (TLink to head.href). A Shift click goes to head.append_href
// instead, as report_sort_width.js and the template's onclick did (the template did a full load; this navigates in-app,
// as every sort link of this page does).

// The selection column's placeholder (step 5d draws the checkbox in it). Blank here: no input, no control.
export interface CheckColumn {
  css: string;
  style: string;
}

export function HeaderRow({ heads, check = null }: { heads: ReportHeadCellOut[]; check?: CheckColumn | null }) {
  const go = useTransitionNavigate();
  return (
    <tr>
      {check ? <th className={check.css || undefined} style={inlineStyle(check.style)} /> : null}
      {heads.map((head, index) => (
        <th key={index} className={head.css || undefined} style={inlineStyle(head.sticky_left)}>
          <TLink
            to={head.href}
            data-append={head.append_href}
            title="Shift+товшилт: нэмэлт эрэмбэ"
            className="hover:text-violet-700"
            onClick={(event) => {
              if (!event.shiftKey || event.button !== 0) return;
              event.preventDefault();
              go(head.append_href);
            }}
          >
            {head.label}{" "}
            <span
              aria-hidden="true"
              style={{
                display: "inline-block",
                minWidth: "2ch",
                visibility: head.arrow ? undefined : "hidden",
              }}
            >
              {head.arrow || "↑"}
            </span>
          </TLink>
        </th>
      ))}
    </tr>
  );
}
