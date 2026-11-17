// Port of app/static/js/money.js. Money boxes group digits by commas as the user types (2500000 -> 2,500,000).
// Only the display changes; the server ignores the commas.

// Verbatim rule from money.js format(): keeps digits and one decimal point, drops leading zeros, groups the whole part
// in threes and keeps at most two decimals.
export function format(raw: string): string {
  const clean = raw.replace(/[^\d.]/g, "");
  const dot = clean.indexOf(".");
  let whole = dot < 0 ? clean : clean.slice(0, dot);
  const frac = dot < 0 ? null : clean.slice(dot + 1).replace(/\./g, "").slice(0, 2);
  whole = whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac === null ? whole : (whole || "0") + "." + frac;
}

// Caret rule from money.js reformat(): counts the digits and dots before the caret in the raw text the user just
// typed (prevValue), then puts the caret after the same number of digits in the formatted text (next).
export function caretAfter(prevValue: string, caret: number, next: string): number {
  const digitsBefore = prevValue.slice(0, caret).replace(/[^\d.]/g, "").length;
  let pos = 0;
  let seen = 0;
  while (pos < next.length && seen < digitsBefore) {
    if (/[\d.]/.test(next.charAt(pos))) seen++;
    pos++;
  }
  return pos;
}
