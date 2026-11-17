// The text of a refused change: the form_errors of the failed request, joined on one line. "" when the error has none
// (htmx did not swap a non-2xx answer either, so the template showed nothing).
export function formErrorText(error: unknown): string {
  const errors = (error as { formErrors?: unknown } | null)?.formErrors;
  return Array.isArray(errors) ? errors.join(" ") : "";
}
