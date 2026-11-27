import { Fragment, useEffect } from "react";
import { useLocation, useParams } from "react-router";
import { useReportPrint, type ReportCellOut, type ReportPrintOut } from "../../api/reports";
import { inlineStyle, moneyText } from "./ReportCell";
import "./reportPrint.css";

type PrintSummary = NonNullable<ReportPrintOut["summary"]>;

// The printable report (Django's reports/print.html). It is a route outside AppShell, like the Django page is standalone.
// The address is the report's own (filters, sort, and the picked-people ticket «sel» when the selection bar printed it),
// sent as given: the page is one query, so it is never refetched by itself (see useReportPrint).
// The fallback when the answer has no form error: the same words the selection screens use.
const FAILED = "Татаж чадсангүй. Дахин оролдоно уу.";
const EMPTY = "Өгөгдөл олдсонгүй";

// The text of a failed answer: the first form error the API sent (a bad ticket says why), else the short message.
function failureText(error: unknown): string {
  const forms = (error as { formErrors?: unknown } | null)?.formErrors;
  return Array.isArray(forms) && typeof forms[0] === "string" && forms[0] !== "" ? forms[0] : FAILED;
}

// One cell as _cell.html draws it: money from its raw value, every other cell its text; a link when there is an href.
function PrintCell({ cell }: { cell: ReportCellOut }) {
  const text = cell.money ? (cell.value === null ? "" : moneyText(cell.value)) : cell.text;
  return (
    <td className={cell.css || undefined} style={inlineStyle(cell.style)}>
      {cell.href ? <a href={cell.href}>{text}</a> : text}
    </td>
  );
}

function Summary({ summary, minGroup }: { summary: PrintSummary; minGroup: number }) {
  return (
    <>
      <h2 className="summary-title">{summary.title}</h2>
      <table className="summary">
        <thead>
          <tr>
            {summary.head.map((label, index) => (
              <th key={index} className={index > 0 ? "text-right" : undefined}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {summary.lines.map((line, rowIndex) => (
            <tr key={rowIndex}>
              {line.map((value, index) => (
                <td key={index} className={index > 0 ? "text-right" : undefined}>
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {summary.foot ? (
          <tfoot>
            <tr>
              {summary.foot.map((value, index) => (
                <td key={index} className={index > 0 ? "text-right" : undefined}>
                  {value}
                </td>
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
      {summary.masked ? (
        <p className="note">{`${minGroup}-ээс цөөн мөртэй бүлгийн мөнгөн дүнг нуусан («—»).`}</p>
      ) : null}
    </>
  );
}

function PrintBody({ data }: { data: ReportPrintOut }) {
  return (
    <>
      <div className="top">
        <div>{data.company}</div>
        <div>{`${data.today} · ${data.printed_by}`}</div>
      </div>
      <h1>{data.title}</h1>
      <div className="filters">
        {data.lines.map((line, index) => (
          <div key={index}>{line}</div>
        ))}
      </div>
      {data.note ? <p className="note">{data.note}</p> : null}
      {data.summary ? <Summary summary={data.summary} minGroup={data.min_group} /> : null}
      <table>
        <thead>
          <tr>
            {data.heads.map((head, index) => (
              <th key={index} className={head.css || undefined}>
                {head.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.count === 0 ? (
            <tr>
              <td colSpan={data.heads.length}>{EMPTY}</td>
            </tr>
          ) : (
            data.groups.map((group, groupIndex) => (
              <Fragment key={groupIndex}>
                {data.grouped ? (
                  <tr>
                    <td colSpan={data.heads.length} className="group">
                      {`${group.label} · ${group.rows.length}`}
                    </td>
                  </tr>
                ) : null}
                {group.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, index) => (
                      <PrintCell key={index} cell={cell} />
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))
          )}
        </tbody>
        {data.footer && data.footer.length > 0 ? (
          <tfoot>
            <tr>
              {data.footer.map((cell, index) => (
                <PrintCell key={index} cell={cell} />
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
      {data.shows_count ? <p className="total">{`Нийт: ${data.count}`}</p> : null}
    </>
  );
}

export function ReportPrintPage() {
  const { key = "" } = useParams();
  const { search } = useLocation();
  const { data, error, isError } = useReportPrint(key, search);

  // The report's title is the document title while the page is open; the previous one comes back when it goes.
  const title = data?.title;
  useEffect(() => {
    if (title === undefined) return;
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);

  return (
    <div className="report-print">
      {/* The @page size depends on the report (landscape or portrait), so it is written here, not in the stylesheet. */}
      <style>{`@page { size: A4 ${data?.landscape ? "landscape" : "portrait"}; margin: 12mm; }`}</style>
      <div className="noprint">
        {/* No print before the rows are here: the print would be empty. */}
        <button type="button" disabled={!data} onClick={() => window.print()}>
          Хэвлэх
        </button>
      </div>
      {isError ? <p role="alert">{failureText(error)}</p> : null}
      {data ? <PrintBody data={data} /> : null}
    </div>
  );
}
