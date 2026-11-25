import type { CSSProperties } from "react";
import type { ReportCellOut } from "../../api/reports";
import { AppLink } from "../../lib/AppLink";

// One cell of a report table: the <td> of _rows.html / the footer of _table.html, with the text of _cell.html. Every
// class and offset comes from the API (css, style); React only turns the text into what the template draws. The text is
// drawn as text, never as HTML.

// Port of the `mnt` filter (employees/templatetags/hr.py) over `group()` (employees/money.py): "2500000.00" -> "2,500,000₮",
// "800000" -> "800,000₮", "1234.5" -> "1,234.50₮". A whole amount has no ".00" tail. "" is "—" (what mnt gives for an
// empty value). A value that is not a plain number is shown as sent.
export function moneyText(raw: string): string {
  if (raw === "") return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!match) return raw;
  const [, sign, digits, decimals = ""] = match;
  const cents = decimals.length > 2 ? Number(raw).toFixed(2).split(".")[1] : (decimals + "00").slice(0, 2);
  const whole = digits.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const tail = cents === "00" ? "" : "." + cents;
  return `${sign}${whole}${tail}₮`;
}

// The inline style the API sends as text: only the pinned offset of a column ("left: 12rem", "left: 2.5rem"). Anything
// else (another property, a second declaration) gives no style, so the API's text can never set more than the offset.
const PINNED_LEFT = /^left: -?\d+(\.\d+)?rem$/;

export function inlineStyle(text: string): CSSProperties | undefined {
  const match = PINNED_LEFT.exec(text.trim());
  return match ? { left: text.trim().slice("left: ".length) } : undefined;
}

export function ReportCell({ cell }: { cell: ReportCellOut }) {
  // A money cell is formatted from its raw value (a blank value prints nothing); every other cell prints the text sent.
  const text = cell.money ? (cell.value === null ? "" : moneyText(cell.value)) : cell.text;
  return (
    <td className={cell.css || undefined} style={inlineStyle(cell.style)}>
      {cell.href ? (
        <AppLink to={cell.href} className="text-violet-700 hover:underline">
          {text}
        </AppLink>
      ) : (
        text
      )}
    </td>
  );
}
