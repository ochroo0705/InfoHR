import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type EmployeeHeadOut = components["schemas"]["EmployeeHeadOut"];
export type EmployeeWorkOut = components["schemas"]["EmployeeWorkOut"];
export type WorkFieldOut = components["schemas"]["WorkFieldOut"];
export type EmployeeSalaryOut = components["schemas"]["EmployeeSalaryOut"];
export type EmployeePersonalOut = components["schemas"]["EmployeePersonalOut"];
export type EmployeeActivityOut = components["schemas"]["EmployeeActivityOut"];
export type ReportingLineOut = components["schemas"]["ReportingLineOut"];
export type ReportingPersonOut = components["schemas"]["ReportingPersonOut"];

// The header, rail and rights of one employee (404 outside the user's scope). Its one-time login is returned once, so
// the query is not kept in the cache after the page leaves (gcTime 0). The page keeps the value in its own state.
export function useEmployee(pk: number) {
  return useQuery({
    queryKey: ["employee", pk],
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}", { params: { path: { pk } } });
      return unwrapQuery<EmployeeHeadOut>(result, "employee request failed");
    },
  });
}

// The Work tab. Its own query, so the page draws as soon as the header arrives.
export function useEmployeeWork(pk: number) {
  return useQuery({
    queryKey: ["employee", pk, "work"],
    retry: retryMe,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/work", { params: { path: { pk } } });
      return unwrapQuery<EmployeeWorkOut>(result, "employee request failed");
    },
  });
}

// The chain of managers above one employee, for `day` (YYYY-MM-DD; "" means today, so no day parameter is sent).
export function useReportingLine(pk: number, day: string) {
  return useQuery({
    queryKey: ["employee", pk, "reporting-line", day],
    // While another day loads, the previous chain stays on screen.
    placeholderData: keepPreviousData,
    retry: retryMe,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/reporting-line", {
        params: { path: { pk }, query: day ? { day } : {} },
      });
      return unwrapQuery<ReportingLineOut>(result, "employee request failed");
    },
  });
}

// The Salary tab. Nothing is asked for while `enabled` is false (the header's can.view_salary is false, or not loaded).
export function useEmployeeSalary(pk: number, enabled = true) {
  return useQuery({
    queryKey: ["employee", pk, "salary"],
    enabled,
    retry: retryMe,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/salary", { params: { path: { pk } } });
      return unwrapQuery<EmployeeSalaryOut>(result, "employee request failed");
    },
  });
}

// The Personal tab. Nothing is asked for while `enabled` is false (the header's can.view_personal is false, or not loaded).
export function useEmployeePersonal(pk: number, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "personal"],
    enabled,
    retry: retryMe,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/personal", { params: { path: { pk } } });
      return unwrapQuery<EmployeePersonalOut>(result, "employee request failed");
    },
  });
}

// The «Түүх» drawer, in batches of 50. The first batch is offset 0; each next batch starts at the previous next_offset.
// The last batch has next_offset null, which ends the list (getNextPageParam returns undefined). Nothing is asked for
// while `enabled` is false: the drawer asks only once it is opened.
export function useEmployeeActivity(pk: number, enabled = true) {
  return useInfiniteQuery({
    queryKey: ["employee", pk, "activity"],
    enabled,
    initialPageParam: 0,
    retry: retryMe,
    queryFn: async ({ pageParam }) => {
      const result = await api.GET("/api/v1/employees/{pk}/activity", {
        params: { path: { pk }, query: { offset: String(pageParam) } },
      });
      return unwrapQuery<EmployeeActivityOut>(result, "employee request failed");
    },
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
  });
}
