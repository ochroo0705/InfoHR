import type { EmployeeWorkOut } from "../../api/employee";
import { legacyOrigin, openLegacyEmployee } from "../../lib/AppLink";
import { RowMenu } from "../../widgets/RowMenu";
import { ScrollHost } from "../../widgets/Scrollbar";

// Port of `_orders.html` («Бусад тушаал»): the one-shot warning, then our orders with their state chip and the
// «Үйлдэл ▾» menu, then the MACS command rows (read-only). Classes, Mongolian text, element order and ids are copied
// from the template. React renders only the strings and flags the API sends (number_muted, cancel segments, hire_note,
// the link URLs, can_edit, can_upload). Every write or pop-up (row click, «Түүх», «Файл хавсаргах», cancel links)
// opens the Django employee page (openLegacyEmployee, ruling D2): no fetch. Files and documents are Django downloads,
// so their URLs go through legacyOrigin().

type Work = EmployeeWorkOut;
type Order = Work["orders"][number];
type Chip = Order["chip"];

// A status chip: the class string comes from Python (`ChipOut.tone`).
function ChipBadge({ chip }: { chip: Chip }) {
  return <span className={chip.tone}>{chip.label}</span>;
}

// A link that opens a legacy pop-up. Stops the click so the row's own click does not also fire.
function LegacyLink({ pk, className, children }: { pk: number; className: string; children: string }) {
  return (
    <a
      href="#"
      className={className}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        openLegacyEmployee(pk);
      }}
    >
      {children}
    </a>
  );
}

// «Үйлдэл ▾» (`_orders.html` line 13-24): the shared row menu (widgets/RowMenu). The items are the template's.
function ActionsMenu({ row, pk }: { row: Order; pk: number }) {
  return (
    <td className="text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
      <RowMenu>
        {row.scan_url && (
          <a
            href={legacyOrigin() + row.scan_url}
            target="_blank"
            rel="noopener"
            className="block px-3 py-2 text-sm hover:bg-slate-50"
          >
            Файл харах
          </a>
        )}
        {row.can_upload && (
          <button
            type="button"
            onClick={() => openLegacyEmployee(pk)}
            className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
          >
            Файл хавсаргах
          </button>
        )}
        {row.word_url && (
          <a href={legacyOrigin() + row.word_url} className="block px-3 py-2 text-sm hover:bg-slate-50">
            Word татах
          </a>
        )}
        {row.pdf_url && (
          <a href={legacyOrigin() + row.pdf_url} className="block px-3 py-2 text-sm hover:bg-slate-50">
            PDF татах
          </a>
        )}
        <button
          type="button"
          onClick={() => openLegacyEmployee(pk)}
          className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50"
        >
          Түүх
        </button>
      </RowMenu>
    </td>
  );
}

// One of our orders (`{% if o %}` branch of the template).
function OwnOrderRow({ row, pk }: { row: Order; pk: number }) {
  const rowClass = row.cancelled ? "text-slate-400 line-through" : row.can_edit ? "cursor-pointer hover:bg-violet-50" : "";
  return (
    <tr
      id={row.order_pk !== null ? `order-${row.order_pk}` : undefined}
      className={rowClass}
      onClick={row.can_edit ? () => openLegacyEmployee(pk) : undefined}
    >
      <td className="whitespace-nowrap">
        {row.number_muted ? <span className="text-slate-400">{row.number}</span> : row.number}
      </td>
      <td className="whitespace-nowrap">{row.date}</td>
      <td>
        {row.type_label}
        {row.hire_note && (
          <>
            {" "}
            <span className="text-xs text-slate-500">{row.hire_note}</span>
          </>
        )}
      </td>
      <td>
        {row.summary}
        {row.cancel_prefix && (
          <>
            {" "}
            <span className="text-xs no-underline">
              {row.cancel_prefix}
              {row.cancelled_by_pk !== null ? (
                <LegacyLink pk={pk} className="text-violet-700 hover:underline">
                  {row.cancel_number}
                </LegacyLink>
              ) : (
                row.cancel_number
              )}
              {row.cancel_suffix}
            </span>
          </>
        )}
        {row.cancels.map((c) => (
          <span key={c.order_pk}>
            {" "}
            <span className="text-xs text-slate-500">
              {c.text_prefix}
              <LegacyLink pk={pk} className="text-violet-700 hover:underline">
                {c.link_text}
              </LegacyLink>
              {c.suffix}
            </span>
          </span>
        ))}
      </td>
      <td>
        <ChipBadge chip={row.chip} />
      </td>
      <ActionsMenu row={row} pk={pk} />
    </tr>
  );
}

// A MACS command row (`{% else %}` branch): read-only, no menu.
function LegacyOrderRow({ row }: { row: Order }) {
  return (
    <tr>
      <td className="whitespace-nowrap">{row.number}</td>
      <td className="whitespace-nowrap">{row.date}</td>
      <td className="text-slate-400">{row.type_label}</td>
      <td>{row.summary}</td>
      <td>
        <ChipBadge chip={row.chip} />
      </td>
      <td></td>
    </tr>
  );
}

// `warning` is the page's latched one-shot warning (WorkSection); without it the query's own value is used.
export function WorkOrders({ work, pk, warning }: { work: Work; pk: number; warning?: string }) {
  const orderWarning = warning ?? work.order_warning;
  return (
    <>
      {orderWarning && <p className="mt-8 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{orderWarning}</p>}
      {work.orders_count > 0 && (
        <>
          <h3 className="sec-title mt-10 mb-3 flex items-baseline gap-2">
            Бусад тушаал <span className="text-xs font-normal text-slate-500">{work.orders_count}</span>
          </h3>
          <ScrollHost className="ptable ptable-fit">
            <table>
              <thead>
                <tr>
                  <th>Дугаар</th>
                  <th>Огноо</th>
                  <th>Төрөл</th>
                  <th>Агуулга</th>
                  <th>Төлөв</th>
                  <th className="w-px"></th>
                </tr>
              </thead>
              <tbody>
                {work.orders.map((row, index) =>
                  row.legacy ? (
                    <LegacyOrderRow key={`m${index}`} row={row} />
                  ) : (
                    <OwnOrderRow key={row.order_pk} row={row} pk={pk} />
                  ),
                )}
              </tbody>
            </table>
          </ScrollHost>
        </>
      )}
    </>
  );
}
