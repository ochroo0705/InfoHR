// Pure view logic of the event pop-up (no React). The API draws the form; these rules decide which typed values are
// sent, which box change reloads what, and how a refreshed form is merged with what the user typed.
import type { EventFormOut } from "../../api/events";
import { initialValue } from "../../widgets/FormFields";

// Names that are never posted with the event: the kind select reloads the form itself, and the CSRF token travels in
// its own header.
const NEVER_SENT: ReadonlySet<string> = new Set(["kind", "csrfmiddlewaretoken"]);

// Names whose change does not reload anything: prev_effective is the hidden last real date.
const NO_REFRESH: ReadonlySet<string> = new Set(["kind", "prev_effective", "csrfmiddlewaretoken"]);

// The effective date box. Only this box is a date (a real date change refills the form).
function isDateField(name: string): boolean {
  return name === "effective";
}

// The held values that belong to the given fields (event boxes plus order-block boxes), by HTML name. kind and the CSRF
// token are never sent, even when listed.
export function valuesToSend(fields: { name: string }[], held: Record<string, string>): Record<string, string> {
  const names = new Set(fields.map((field) => field.name));
  return Object.fromEntries(Object.entries(held).filter(([name]) => names.has(name) && !NEVER_SENT.has(name)));
}

// What a change of one box refreshes: the whole form for the effective date ("form"), the summary line for any other
// box ("summary"), nothing for kind (its own handler reloads), prev_effective and the CSRF token.
export function refreshKindFor(name: string): "form" | "summary" | null {
  if (isDateField(name)) return "form";
  if (NO_REFRESH.has(name)) return null;
  return "summary";
}

// The form after a refresh, by HTML name. The server has already kept what the user typed and refilled only the boxes
// they did not edit, so its values win. A box in keepNames (typed while the request was in flight) keeps the held
// value when there is one. A box that is no longer in the form is dropped (a kind change can remove boxes).
export function mergeFormAfterRefresh(
  held: Record<string, string>,
  next: EventFormOut,
  keepNames?: ReadonlySet<string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of [...next.fields, ...next.order_fields]) {
    const keep = keepNames?.has(field.name) === true && field.name in held;
    out[field.name] = keep ? held[field.name] : initialValue(field);
  }
  return out;
}

// The hidden prev_effective to send on the next reload: the last real date the server reported.
export function prevEffectiveBase(next: EventFormOut): string {
  return next.prev_effective;
}
