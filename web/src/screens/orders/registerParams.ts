import type { RegisterParams } from "../../api/orderRegister";

// The register's URL state. The order of the keys is the order of the Django query_string (q, sort, year, order_type,
// department, state), so the address reads the same as before the port.
const DEFAULT_SORT = "-date";
const KEYS: (keyof RegisterParams)[] = ["q", "sort", "year", "order_type", "department", "state"];

// The address as the register and the print page read it. Missing values are empty, except sort, which defaults to
// the newest first. Values are kept as typed: the server cleans them (a bad year shows as «Бүх он»).
export function paramsFromSearch(search: URLSearchParams): RegisterParams {
  return {
    q: search.get("q") ?? "",
    sort: search.get("sort") || DEFAULT_SORT,
    year: search.get("year") ?? "",
    order_type: search.get("order_type") ?? "",
    department: search.get("department") ?? "",
    state: search.get("state") ?? "",
  };
}

// The query string for the address: empty values and the default sort are left out.
export function searchFromParams(p: RegisterParams): URLSearchParams {
  const search = new URLSearchParams();
  for (const key of KEYS) {
    const value = p[key];
    if (!value) continue;
    if (key === "sort" && value === DEFAULT_SORT) continue;
    search.set(key, value);
  }
  return search;
}

// The print page's address for the current filters (Django's #print-link, opened in a new tab).
export function printHref(p: RegisterParams): string {
  const qs = searchFromParams(p).toString();
  return "/employees/orders/print/" + (qs ? "?" + qs : "");
}
