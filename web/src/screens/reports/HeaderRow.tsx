import { useEffect, useRef } from "react";
import type { ReportHeadCellOut } from "../../api/reports";
import { useTransitionNavigate, TLink } from "../../lib/viewTransition";
import { inlineStyle } from "./ReportCell";
import { markClass, TITLE_CORRECT, TITLE_EDIT, type ColumnMark } from "./grid/EditMarks";

// The head row of a report table (_table.html <tr> in <thead>). Labels, sort addresses, arrows, classes and the pinned
// offset all come from the API. A plain click sorts in place (TLink to head.href). A Shift click goes to head.append_href
// instead, as report_sort_width.js and the template's onclick did (the template did a full load; this navigates in-app,
// as every sort link of this page does).

// The selection column's placeholder. Without `select` it stays blank; with it, the header box is drawn in it.
export interface CheckColumn {
  css: string;
  style: string;
}

// The header box (_table.html's data-select-all). `mark` is headerMark over the rows on screen; a click picks every row
// on screen, or clears them (onPick(!mark.checked), as report_select.js's header change handler did).
export interface HeaderSelect {
  mark: { checked: boolean; indeterminate: boolean };
  onPick: (on: boolean) => void;
}

function HeaderBox({ mark, onPick }: HeaderSelect) {
  const ref = useRef<HTMLInputElement>(null);
  // Indeterminate is a DOM property, not an attribute: it is written from the mark on every change.
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = mark.indeterminate;
  }, [mark.checked, mark.indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      data-select-all
      autoComplete="off"
      aria-label="Бүгдийг сонгох"
      checked={mark.checked}
      onChange={() => onPick(!mark.checked)}
    />
  );
}

export function HeaderRow({
  heads,
  check = null,
  select = null,
  marks = null,
}: {
  heads: ReportHeadCellOut[];
  check?: CheckColumn | null;
  select?: HeaderSelect | null;
  // The editable-column mark of each grid column (EditMarks.columnMarks); the header takes its column's mark and title.
  marks?: ReadonlyArray<ColumnMark> | null;
}) {
  const go = useTransitionNavigate();
  const offset = check ? 1 : 0;
  return (
    <tr>
      {check ? (
        <th className={check.css || undefined} style={inlineStyle(check.style)}>
          {select ? <HeaderBox mark={select.mark} onPick={select.onPick} /> : null}
        </th>
      ) : null}
      {heads.map((head, index) => {
        const mark = marks?.[index + offset] ?? "";
        const className = [head.css, markClass(mark)].filter(Boolean).join(" ");
        const title = mark === "edit" ? TITLE_EDIT : mark === "correct" ? TITLE_CORRECT : undefined;
        return (
          <th
            key={index}
            className={className || undefined}
            title={title}
            style={inlineStyle(head.sticky_left)}
          >
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
        );
      })}
    </tr>
  );
}
