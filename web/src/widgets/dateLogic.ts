// Pure date logic for the React DatePicker. Port of the pure parts of app/static/js/datepicker.js (the labels, the typed
// normalising and the 42-cell month grid). Months are 0-based, as in Date.

// Verbatim from app/static/js/datepicker.js (MONTHS and DAYS).
export const MONTHS_MN: string[] = [
  "1-р сар", "2-р сар", "3-р сар", "4-р сар", "5-р сар", "6-р сар",
  "7-р сар", "8-р сар", "9-р сар", "10-р сар", "11-р сар", "12-р сар",
];
export const WEEKDAYS_MN: string[] = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"];

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_MONTH = /^(\d{4})-(\d{2})$/;

function pad(n: number): string {
  return (n < 10 ? "0" : "") + n;
}

export function isoOf(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// A real calendar day, or null (2026-02-30 is not one).
function parseIso(s: string): Date | null {
  const m = ISO_DATE.exec(s);
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  return d.getMonth() === +m[2] - 1 ? d : null;
}

// "20261014", "2026.10.14" or "2026/10/14" -> "2026-10-14". A valid ISO date is kept. Anything else gives null.
export function normalise(typed: string): string | null {
  const s = typed.trim();
  if (parseIso(s)) return s;
  const digits = s.replace(/\D/g, "");
  if (!/^\d{8}$/.test(digits)) return null;
  const candidate = `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
  return parseIso(candidate) ? candidate : null;
}

// "202610", "2026.10" or "2026/10" -> "2026-10" (month pickers). Anything else, or a month outside 1 to 12, gives null.
export function normaliseMonth(typed: string): string | null {
  const s = typed.trim();
  const m = ISO_MONTH.exec(s);
  if (m && +m[2] >= 1 && +m[2] <= 12) return s;
  const digits = s.replace(/\D/g, "");
  if (!/^\d{6}$/.test(digits)) return null;
  const month = +digits.slice(4);
  if (month < 1 || month > 12) return null;
  return `${digits.slice(0, 4)}-${digits.slice(4)}`;
}

// The cells of one month view, Monday first. 42 cells (six weeks), except that a sixth row which is all next month is
// dropped (datepicker.js: `if (i === 35 && day.getMonth() !== view.getMonth()) break`).
export function monthGrid(year: number, month: number): { iso: string; inMonth: boolean }[] {
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - ((first.getDay() + 6) % 7));
  const cells: { iso: string; inMonth: boolean }[] = [];
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    if (i === 35 && day.getMonth() !== month) break;
    cells.push({ iso: isoOf(day), inMonth: day.getMonth() === month });
  }
  return cells;
}

// True when a day (or month, as YYYY-MM) is before min or after max. ISO strings compare in date order.
export function isDisabled(iso: string, min?: string, max?: string): boolean {
  return (min !== undefined && min !== "" && iso < min) || (max !== undefined && max !== "" && iso > max);
}
