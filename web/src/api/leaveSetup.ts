import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { present } from "./leave";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery, type Settled } from "./mutate";
import type { components } from "./schema";

export type LeaveHolidaysOut = components["schemas"]["LeaveHolidaysOut"];
export type LeaveHolidayOut = components["schemas"]["LeaveHolidayOut"];
export type LeaveHolidayAddIn = components["schemas"]["LeaveHolidayAddIn"];
export type LeaveHolidayDeleteIn = components["schemas"]["LeaveHolidayDeleteIn"];
export type LeaveHolidayPrefillIn = components["schemas"]["LeaveHolidayPrefillIn"];
export type LeaveSettingsOut = components["schemas"]["LeaveSettingsOut"];
export type LeaveApprovalOut = components["schemas"]["LeaveApprovalOut"];
export type LeaveApprovalIn = components["schemas"]["LeaveApprovalIn"];
export type LeaveAutoIn = components["schemas"]["LeaveAutoIn"];
export type LeaveStringChoiceOut = components["schemas"]["LeaveStringChoiceOut"];
export type LeaveTypeOut = components["schemas"]["LeaveTypeOut"];
export type LeaveTypeIn = components["schemas"]["LeaveTypeIn"];
export type LeaveWriteResultOut = components["schemas"]["LeaveWriteResultOut"];

// One holiday write. `year` is the page's year (null or junk is this year on the server); `date` and `name` are used by
// add (both) and delete (date only); prefill takes the year alone.
export type HolidayActionIn = {
  action: "add" | "delete" | "prefill";
  year?: number;
  date?: string;
  name?: string;
};

// After a setup write that saved (ok true): the write's own page query (holidays or settings), the leave list (its
// holiday and not-configured banners), the attention box and the nav badge. A refused write (ok false) changed nothing.
async function refreshAfterSetupWrite(
  queryClient: QueryClient,
  pageKey: string[],
  result: LeaveWriteResultOut,
): Promise<void> {
  if (!result.ok) return;
  await queryClient.invalidateQueries({ queryKey: pageKey });
  await queryClient.invalidateQueries({ queryKey: ["leave", "list"] });
  await queryClient.invalidateQueries({ queryKey: ["attention"] });
  await queryClient.invalidateQueries({ queryKey: ["nav"] });
}

const HOLIDAYS_KEY = ["leave", "holidays"];
const SETTINGS_KEY = ["leave", "settings"];

// The holidays of one year. The year is sent only when given; junk or an out-of-range year is this year on the server.
export function useLeaveHolidays(year?: string) {
  return useQuery({
    queryKey: ["leave", "holidays", year ?? ""],
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/holidays", { params: { query: present({ year }) } });
      return unwrapQuery<LeaveHolidaysOut>(result, "leave request failed");
    },
  });
}

// Sends one holiday write to its route. Each route takes only the fields it reads.
function sendHolidayAction(input: HolidayActionIn): Promise<Settled<LeaveWriteResultOut>> {
  const year = input.year ?? null;
  switch (input.action) {
    case "add":
      return api.POST("/api/v1/leave/holidays/add", {
        body: { year, date: input.date ?? "", name: input.name ?? "" },
      });
    case "delete":
      return api.POST("/api/v1/leave/holidays/delete", { body: { year, date: input.date ?? "" } });
    case "prefill":
      return api.POST("/api/v1/leave/holidays/prefill", { body: { year } });
  }
}

// Adds, deletes or prefills holidays. The answer's `error` carries the refusal text (add only); ok false changed nothing.
export function useHolidayAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: HolidayActionIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () => sendHolidayAction(input)),
    onSuccess: (result) => refreshAfterSetupWrite(queryClient, HOLIDAYS_KEY, result),
  });
}

// The page's settings: the leave types, the approval steps with their choices, the auto-grant switch.
export function useLeaveSettings() {
  return useQuery({
    queryKey: SETTINGS_KEY,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/settings");
      return unwrapQuery<LeaveSettingsOut>(result, "leave request failed");
    },
  });
}

// Saves the two approval steps. A refusal answers ok false with field_errors and form_errors; the caller shows them.
export function useSaveApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveApprovalIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/settings/approval", { body }),
      ),
    onSuccess: (result) => refreshAfterSetupWrite(queryClient, SETTINGS_KEY, result),
  });
}

// Switches the automatic annual grant on or off.
export function useSaveAutoGrant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveAutoIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () => api.POST("/api/v1/leave/settings/auto", { body })),
    onSuccess: (result) => refreshAfterSetupWrite(queryClient, SETTINGS_KEY, result),
  });
}

// One leave type as the pop-up loads it. Nothing is fetched while id is null (the add pop-up). Kept only while open
// (gcTime 0) and read fresh on every open, so the form never starts from an older copy of the type.
export function useLeaveType(id: number | null) {
  return useQuery({
    queryKey: ["leave", "settings", "type", id],
    enabled: id !== null,
    retry: retryMe,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      if (id === null) throw new Error("leave type id missing");
      const result = await api.GET("/api/v1/leave/settings/types/{pk}", { params: { path: { pk: id } } });
      return unwrapQuery<LeaveTypeOut>(result, "leave request failed");
    },
  });
}

// Creates a leave type (id null) or updates type `id`. A refusal answers ok false with field_errors; the caller shows them.
export function useSaveLeaveType(id: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveTypeIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        id === null
          ? api.POST("/api/v1/leave/settings/types", { body })
          : api.POST("/api/v1/leave/settings/types/{pk}", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterSetupWrite(queryClient, SETTINGS_KEY, result),
  });
}

// Deletes leave type `id`. A type in use is kept and the reason comes back in `error` (ok false).
export function useDeleteLeaveType(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/settings/types/{pk}/delete", { params: { path: { pk: id } } }),
      ),
    onSuccess: (result) => refreshAfterSetupWrite(queryClient, SETTINGS_KEY, result),
  });
}
