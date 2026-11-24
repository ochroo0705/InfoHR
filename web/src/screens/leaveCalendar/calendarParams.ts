// The team calendar's URL state (?month=YYYY-MM&department=<id>). A month that is not YYYY-MM and a department that is
// not a number are dropped here: the request leaves them out, and the server falls back (the current month, no
// department), as Django does. Other values are kept as typed. An empty value is never written to the address.
export type CalendarSearch = { month: string; department: string };

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const DEPARTMENT = /^\d+$/;

export function parseCalendarParams(search: URLSearchParams): CalendarSearch {
  const month = search.get("month") ?? "";
  const department = search.get("department") ?? "";
  return {
    month: MONTH.test(month) ? month : "",
    department: DEPARTMENT.test(department) ? department : "",
  };
}

export function toSearch(params: CalendarSearch): URLSearchParams {
  const search = new URLSearchParams();
  if (params.month) search.append("month", params.month);
  if (params.department) search.append("department", params.department);
  return search;
}
