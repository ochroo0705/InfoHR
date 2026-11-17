import { useEffect, useState, type ReactNode } from "react";

// The part of a react-query result that CountLine reads. useUpcoming, useHires and useAway return it as is.
export type LazyResult<T> = { data: T | undefined; isSuccess: boolean; isError: boolean };

export type CountLineProps<T> = {
  label: string;
  count: number;
  id: string;
  // Called on every render with whether the panel is open. It must call its hook unconditionally, e.g.
  // `(open) => useUpcoming("birthday", open)`. Nothing is fetched while open is false.
  query: (open: boolean) => LazyResult<T>;
  // Renders the loaded data inside the panel.
  children: (data: T) => ReactNode;
};

// «{label} {count} ▸» full-width button with its own panel under it (htmx count line of the Today page).
// The arrow turns to ▾ and aria-expanded to "true" only once the lazy query has succeeded, as the htmx
// after-request handler does. A second click empties the panel and sets ▸ again, with no request.
// A failed query closes the panel again, so the next click retries it.
export function CountLine<T>({ label, count, id, query, children }: CountLineProps<T>) {
  const [open, setOpen] = useState(false);
  const result = query(open);
  const data = open && result.isSuccess ? result.data : undefined;
  const expanded = data !== undefined;

  useEffect(() => {
    if (open && result.isError) setOpen(false);
  }, [open, result.isError]);

  return (
    <div>
      <button
        type="button"
        aria-controls={id}
        aria-expanded={expanded ? "true" : "false"}
        onClick={() => setOpen(!expanded)}
        className="flex w-full items-center rounded py-1.5 text-left text-slate-700 hover:bg-slate-50"
      >
        {label} {count} <span data-arrow>{expanded ? "▾" : "▸"}</span>
      </button>
      <div id={id} aria-live="polite">
        {data !== undefined ? children(data) : null}
      </div>
    </div>
  );
}
