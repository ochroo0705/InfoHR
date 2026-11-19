import { Fragment, useEffect } from "react";
import { useLocation } from "react-router";
import { useOrderPrint } from "../../api/orderRegister";
import { paramsFromSearch } from "./registerParams";
import "./ordersPrint.css";

const TITLE = "Хүний нөөцийн тушаалууд";

const HEADINGS = [
  "№",
  "Огноо",
  "Ажилтан",
  "Албан тушаал",
  "Тушаал №",
  "Тушаалын утга",
  "Тушаал гаргасан албан тушаалтан",
  "Регистр №",
  "Хүйс",
  "Нас",
];

// The register's print page (Django's orders_print.html). It is a route outside AppShell, like the Django page is
// standalone. The filters come from the address, the same as the register's. The rows are one query: the API writes
// one export log line per request, so the query is never refetched by itself (see useOrderPrint).
export function OrdersPrintPage() {
  const { search } = useLocation();
  const { data, isPending, isError } = useOrderPrint(paramsFromSearch(new URLSearchParams(search)));

  useEffect(() => {
    const previous = document.title;
    document.title = TITLE;
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <div className="orders-print">
      <div className="noprint">
        {/* No print before the rows are here: the print would be empty. */}
        <button type="button" disabled={!data} onClick={() => window.print()}>
          Хэвлэх
        </button>
      </div>
      {data ? (
        <div className="top">
          <div>{data.company}</div>
          <div>{data.today}</div>
        </div>
      ) : null}
      <h1>{TITLE}</h1>
      {isError ? <p>Мэдээлэл ачаалж чадсангүй.</p> : null}
      {isPending || isError ? null : (
        <table>
          <thead>
            <tr>
              {HEADINGS.map((heading) => (
                <th key={heading}>{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.groups.map((group) => (
              <Fragment key={group.department}>
                <tr>
                  <td className="group" colSpan={10}>
                    Хэлтэс: {group.department}
                  </td>
                </tr>
                {group.rows.map((row, index) => (
                  <tr key={`${group.department}-${index}`}>
                    <td>{row.n}</td>
                    <td>{row.date}</td>
                    <td>{row.employee_name}</td>
                    <td>{row.position}</td>
                    <td>{row.number}</td>
                    <td>{row.summary}</td>
                    <td>{row.issued_by}</td>
                    <td>{row.register_no}</td>
                    <td>{row.gender}</td>
                    <td>{row.age}</td>
                  </tr>
                ))}
              </Fragment>
            ))}
            {data.empty ? (
              <tr>
                <td colSpan={10}>Тушаал олдсонгүй</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      )}
      {isPending || isError ? null : <p className="sign">Хүний нөөцийн мэргэжилтэн: ........ / /</p>}
    </div>
  );
}
