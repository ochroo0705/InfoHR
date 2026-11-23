import type { EmployeeLogParams, SystemLogParams } from "../../api/logs";

// The log pages' URL state. The order of the pairs is the order of Django's employee_address / system_address
// (app/logs/page_rules.py), so the address reads the same as before the port.

// The address as the employee log reads it. Missing values are empty. Values are kept as typed: the server cleans them.
export function employeeParamsFromSearch(search: URLSearchParams): EmployeeLogParams {
  return {
    q: search.get("q") ?? "",
    emp: search.get("emp") ?? "",
    employee: search.get("employee") ?? "",
    by: search.get("by") ?? "",
    kind: search.getAll("kind"),
    area: search.get("area") ?? "",
    field: search.get("field") ?? "",
    from: search.get("from") ?? "",
    to: search.get("to") ?? "",
    system: search.get("system") ?? "",
    oldest: search.get("oldest") ?? "",
  };
}

// The address as the system log reads it. Missing values are empty. Values are kept as typed: the server cleans them.
export function systemParamsFromSearch(search: URLSearchParams): SystemLogParams {
  return {
    q: search.get("q") ?? "",
    by: search.get("by") ?? "",
    target: search.get("target") ?? "",
    ip: search.get("ip") ?? "",
    category: search.getAll("category"),
    action: search.get("action") ?? "",
    from: search.get("from") ?? "",
    to: search.get("to") ?? "",
    oldest: search.get("oldest") ?? "",
  };
}

// The query string for the employee log's address: empty values are left out, repeated kinds are kept in order.
export function searchFromEmployeeParams(p: EmployeeLogParams): URLSearchParams {
  const pairs: [string, string][] = [
    ["q", p.q],
    ["emp", p.emp],
    ["employee", p.employee],
    ["by", p.by],
    ...p.kind.map((kind): [string, string] => ["kind", kind]),
    ["area", p.area],
    ["field", p.field],
    ["from", p.from],
    ["to", p.to],
    ["system", p.system],
    ["oldest", p.oldest],
  ];
  return toSearch(pairs);
}

// The query string for the system log's address: empty values are left out, repeated categories are kept in order.
export function searchFromSystemParams(p: SystemLogParams): URLSearchParams {
  const pairs: [string, string][] = [
    ["q", p.q],
    ...p.category.map((category): [string, string] => ["category", category]),
    ["action", p.action],
    ["by", p.by],
    ["target", p.target],
    ["ip", p.ip],
    ["from", p.from],
    ["to", p.to],
    ["oldest", p.oldest],
  ];
  return toSearch(pairs);
}

// Keeps the pairs that have a value, in the order given.
function toSearch(pairs: [string, string][]): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of pairs) {
    if (value) search.append(key, value);
  }
  return search;
}
