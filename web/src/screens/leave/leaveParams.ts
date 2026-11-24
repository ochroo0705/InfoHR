import type { LeaveListParams } from "../../api/leave";

// The leave list's URL state. The pairs are written in one fixed order (q, employee, status, type, from, to) so the
// address is stable; Django does not fix this order and the server does not depend on it. The status "recorded" is the
// default and is left out.
export const DEFAULT_STATUS = "recorded";

// The address as the leave list reads it. A missing or empty status is the default. Values are kept as typed: the server
// cleans them (a bad date or an unknown status is ignored or matches nothing, as in Django).
export function parseLeaveParams(search: URLSearchParams): LeaveListParams {
  return {
    q: search.get("q") ?? "",
    employee: search.get("employee") ?? "",
    status: search.get("status") || DEFAULT_STATUS,
    type: search.get("type") ?? "",
    from: search.get("from") ?? "",
    to: search.get("to") ?? "",
  };
}

// The query string for the leave list's address: empty values and the default status are left out.
export function toSearch(params: LeaveListParams): URLSearchParams {
  const pairs: [string, string | undefined][] = [
    ["q", params.q],
    ["employee", params.employee],
    ["status", params.status === DEFAULT_STATUS ? "" : params.status],
    ["type", params.type],
    ["from", params.from],
    ["to", params.to],
  ];
  const search = new URLSearchParams();
  for (const [key, value] of pairs) {
    if (value) search.append(key, value);
  }
  return search;
}
