import type { components } from "../../../api/schema";
import { TLink } from "../../../lib/viewTransition";

// The pivot (app/reports/templates/reports/layouts/pivot.html, _pivot_grid.html, UI_RULES §4b): one table per grid, rows by
// the first grouping and columns by the second, with «Дүн» totals. Classes and Mongolian text are copied from the
// templates. Every figure is finished text from the API, so nothing is formatted here. A second grid (a second value)
// is a second table. Links are in-app addresses (AppLink), as in the other layouts.

type PivotOut = components["schemas"]["ReportPivotOut"];
type GridOut = components["schemas"]["ReportPivotGridOut"];

export interface PivotLayoutProps {
  pivot: PivotOut;
}

const LINK_CLASS = "text-violet-700 hover:underline";
const LINK_TITLE = "Эдгээр мөрийг хүснэгтээр харах";

export function PivotLayout({ pivot }: PivotLayoutProps) {
  return (
    <>
      {pivot.grids.map((grid, index) => (
        <PivotGrid key={index} grid={grid} />
      ))}
    </>
  );
}

function PivotGrid({ grid }: { grid: GridOut }) {
  if (grid.empty) {
    return (
      <p className="mt-4 py-6 text-center text-sm text-slate-400">
        Өгөгдөл олдсонгүй
      </p>
    );
  }
  return (
    <>
      <div className="ptable ptable-fit mt-4">
        <table>
          <caption className="caption-top pb-2 text-left text-sm text-slate-600">
            {grid.caption}
          </caption>
          <thead>
            <tr>
              <th scope="col">{grid.corner_label}</th>
              {grid.col_heads.map((head, index) => (
                <th key={index} scope="col" className="text-right">
                  {head.href ? (
                    <TLink
                      to={head.href}
                      className={LINK_CLASS}
                      title={LINK_TITLE}
                    >
                      {head.label}
                    </TLink>
                  ) : (
                    head.label
                  )}
                </th>
              ))}
              <th scope="col" className="text-right">
                Дүн
              </th>
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <th scope="row">
                  {row.href ? (
                    <TLink
                      to={row.href}
                      className={LINK_CLASS}
                      title={LINK_TITLE}
                    >
                      {row.label}
                    </TLink>
                  ) : (
                    row.label
                  )}
                </th>
                {row.cells.map((cell, cellIndex) => (
                  <td key={cellIndex} className="text-right">
                    {cell.href ? (
                      <TLink
                        to={cell.href}
                        className={LINK_CLASS}
                        title={LINK_TITLE}
                      >
                        {cell.text}
                      </TLink>
                    ) : (
                      cell.text
                    )}
                  </td>
                ))}
                <td className="text-right font-semibold">{row.total}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-slate-300 font-semibold">
              <th scope="row">Дүн</th>
              {grid.col_totals.map((total, index) => (
                <td key={index} className="text-right">
                  {total}
                </td>
              ))}
              <td className="text-right">{grid.grand}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {grid.masked ? (
        <p className="mt-2 text-sm text-slate-500">{grid.note}</p>
      ) : null}
    </>
  );
}
