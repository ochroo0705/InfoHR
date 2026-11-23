import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type LogEmployeeOut = components["schemas"]["LogEmployeeOut"];
export type LogEmployeeRowOut = components["schemas"]["LogEmployeeRowOut"];
export type LogSystemOut = components["schemas"]["LogSystemOut"];
export type LogSystemRowOut = components["schemas"]["LogSystemRowOut"];
export type LogTabsOut = components["schemas"]["LogTabsOut"];
export type LogChangeOut = components["schemas"]["LogChangeOut"];
export type LogChipOut = components["schemas"]["LogChipOut"];
export type LogEmployeeOptionsOut = components["schemas"]["LogEmployeeOptionsOut"];
export type LogEmployeeQueryOut = components["schemas"]["LogEmployeeQueryOut"];
export type LogOptionOut = components["schemas"]["LogOptionOut"];
export type LogSystemOptionsOut = components["schemas"]["LogSystemOptionsOut"];
export type LogSystemQueryOut = components["schemas"]["LogSystemQueryOut"];

// The filters of the employee log, as the URL carries them (all text; the server cleans them).
export type EmployeeLogParams = {
  q: string;
  emp: string;
  employee: string;
  by: string;
  kind: string[];
  area: string;
  field: string;
  from: string;
  to: string;
  system: string;
  oldest: string;
};

// The filters of the system log, as the URL carries them (all text; the server cleans them).
export type SystemLogParams = {
  q: string;
  by: string;
  target: string;
  ip: string;
  category: string[];
  action: string;
  from: string;
  to: string;
  oldest: string;
};

// The employee log rows, batch by batch. A changed address is a new key: it starts again at offset 0 and the rows of the
// old address are not kept. `next_offset` is null when no row follows.
export function useEmployeeLog(params: EmployeeLogParams) {
  return useInfiniteQuery({
    queryKey: ["logs-employee", params],
    initialPageParam: 0,
    getNextPageParam: (last: LogEmployeeOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      const result = await api.GET("/api/v1/logs/employee", {
        // The schema types offset as a string, like the other query values.
        params: { query: { ...params, offset: String(pageParam) } },
      });
      return unwrapQuery<LogEmployeeOut>(result, "log request failed");
    },
  });
}

// The system log rows, batch by batch; the same rules as useEmployeeLog.
export function useSystemLog(params: SystemLogParams) {
  return useInfiniteQuery({
    queryKey: ["logs-system", params],
    initialPageParam: 0,
    getNextPageParam: (last: LogSystemOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      const result = await api.GET("/api/v1/logs/system", {
        params: { query: { ...params, offset: String(pageParam) } },
      });
      return unwrapQuery<LogSystemOut>(result, "log request failed");
    },
  });
}

// The Excel link of a log page. `address` is the cleaned query string the page got from the API, so the file has the
// same filters as the screen; an empty address links to the file with no filter.
export function excelHref(kind: "employee" | "system", address: string): string {
  const base = `/api/v1/logs/${kind}/export`;
  return address ? `${base}?${address}` : base;
}
