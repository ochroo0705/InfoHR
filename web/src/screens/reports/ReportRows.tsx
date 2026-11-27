import { Fragment, type MouseEvent } from "react";
import type { ReportCellOut, ReportGroupOut } from "../../api/reports";
import { isPorted } from "../../lib/ported";
import { useTransitionNavigate } from "../../lib/viewTransition";
import { inlineStyle, ReportCell } from "./ReportCell";
import type { CheckColumn } from "./HeaderRow";
import { isOn, isPersonId, isPicked, PICKED_CLASS } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";

// The body rows of a report table (_rows.html, and the heading row of _table.html for a grouped table). A grouped table
// draws a heading «label · count» over its rows; an ungrouped one draws its rows only. Both come from the API's groups.
// With `selection`, each row of a person has a checkbox in the selection column, and a click on the row (outside the
// controls) picks it while selection is on, or opens its first link while it is off (report_select.js).

// The person a row is about: its first cell's person (_rows.html's row.0.person). 0 or none means no person, no checkbox.
export function rowPerson(row: ReportCellOut[]): string | null {
  const person = row.length > 0 ? row[0].person : 0;
  if (!person) return null;
  const id = String(person);
  return isPersonId(id) ? id : null;
}

// The controls of a row: a click on them keeps its own action (report_select.js openRowLink).
const CONTROLS = "a, button, input, select, textarea, label";

function within(target: EventTarget, selector: string): boolean {
  return target instanceof Element && target.closest(selector) !== null;
}

// The link the row opens is the first cell's link, as the document handler did (`td a[href]`). Ctrl, Cmd or a middle click
// opens a new tab; a plain click goes to the record (in-app for a ported path, else a full load). A text selection is not a
// click. A click inside a <table data-grid> is left to the grid's cursor (grid_nav.js), as the document handler did.
function openRowLink(event: MouseEvent<HTMLTableRowElement>, go: (to: string) => void) {
  if (event.defaultPrevented) return;
  if (within(event.target, "table[data-grid]") || within(event.target, CONTROLS)) return;
  if (window.getSelection()?.toString()) return;
  const href = event.currentTarget.querySelector("td a[href]")?.getAttribute("href");
  if (!href) return;
  if (event.button === 1 || event.ctrlKey || event.metaKey) {
    window.open(href, "_blank");
  } else if (event.button === 0) {
    if (isPorted(href)) go(href);
    else window.location.href = href;
  }
}

// While selection is on, a click anywhere on a person's row toggles that person and does nothing else (no link, no
// button). A click on the row's own checkbox keeps its native toggle: its change event does the pick.
function pickOnRowClick(event: MouseEvent<HTMLTableRowElement>, selection: ReportSelection, person: string | null) {
  if (!isOn(selection.state) || person === null) return;
  if (within(event.target, "input[data-select-row]")) return;
  event.preventDefault();
  event.stopPropagation();
  selection.pickRow(person, !isPicked(selection.state, person));
}

export function ReportRows({
  groups,
  grouped,
  tableSpan,
  check = null,
  selection = null,
}: {
  groups: ReportGroupOut[];
  grouped: boolean;
  tableSpan: number;
  check?: CheckColumn | null;
  selection?: ReportSelection | null;
}) {
  const go = useTransitionNavigate();
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
          {group.rows.map((row, rowIndex) => {
            const person = rowPerson(row);
            const picked = selection !== null && person !== null && isPicked(selection.state, person);
            const onRowClick = (event: MouseEvent<HTMLTableRowElement>) => {
              if (selection && isOn(selection.state)) return;
              openRowLink(event, go);
            };
            return (
              <tr
                key={rowIndex}
                data-person={selection && person !== null ? person : undefined}
                className={picked ? PICKED_CLASS : undefined}
                aria-selected={selection && person !== null ? picked : undefined}
                onClickCapture={selection ? (event) => pickOnRowClick(event, selection, person) : undefined}
                onClick={onRowClick}
                onAuxClick={onRowClick}
              >
                {check ? (
                  <td className={check.css || undefined} style={inlineStyle(check.style)}>
                    {selection && person !== null ? (
                      <input
                        type="checkbox"
                        data-select-row
                        autoComplete="off"
                        aria-label="Мөр сонгох"
                        checked={picked}
                        onChange={() => selection.pickRow(person, !picked)}
                      />
                    ) : null}
                  </td>
                ) : null}
                {row.map((cell, cellIndex) => (
                  <ReportCell key={cellIndex} cell={cell} />
                ))}
              </tr>
            );
          })}
        </Fragment>
      ))}
    </>
  );
}
