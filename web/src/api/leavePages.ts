import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { present } from "./leave";
import { retryMe } from "./me";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type LeaveBalanceListOut = components["schemas"]["LeaveBalanceListOut"];
export type LeaveBalanceRowOut = components["schemas"]["LeaveBalanceRowOut"];
export type LeaveBalancePeriodOut = components["schemas"]["LeaveBalancePeriodOut"];
export type LeaveCalendarOut = components["schemas"]["LeaveCalendarOut"];
export type LeaveCalendarDayOut = components["schemas"]["LeaveCalendarDayOut"];
export type LeaveCalendarLineOut = components["schemas"]["LeaveCalendarLineOut"];
export type LeaveCalendarCellOut = components["schemas"]["LeaveCalendarCellOut"];

// The filters of the team calendar, as the URL carries them (all text). An empty or missing value is left out of the query.
export type LeaveCalendarParams = {
  month?: string;
  department?: string;
};

// The balance rows, batch by batch. `next_offset` is null when no row follows.
export function useLeaveBalances() {
  return useInfiniteQuery({
    queryKey: ["leave", "balances"],
    initialPageParam: 0,
    getNextPageParam: (last: LeaveBalanceListOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      // The schema types offset as a string, like the other query values.
      const result = await api.GET("/api/v1/leave/balances", {
        params: { query: { offset: String(pageParam) } },
      });
      return unwrapQuery<LeaveBalanceListOut>(result, "leave request failed");
    },
  });
}

// One month of the team calendar. A changed month or department is a new key, so each view is fetched once.
export function useLeaveCalendar(params: LeaveCalendarParams) {
  return useQuery({
    queryKey: ["leave", "calendar", params],
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/calendar", { params: { query: present({ ...params }) } });
      return unwrapQuery<LeaveCalendarOut>(result, "leave request failed");
    },
  });
}
