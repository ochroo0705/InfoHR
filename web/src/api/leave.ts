import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type LeaveListOut = components["schemas"]["LeaveListOut"];
export type LeaveRowOut = components["schemas"]["LeaveRowOut"];
export type LeaveOptionsOut = components["schemas"]["LeaveOptionsOut"];
export type LeaveEditOut = components["schemas"]["LeaveEditOut"];
export type LeaveCancelInfoOut = components["schemas"]["LeaveCancelInfoOut"];
export type LeaveLoaded = components["schemas"]["LeaveLoadedOut"];
export type LeaveWriteIn = components["schemas"]["LeaveWriteIn"];
export type LeaveUpdateIn = components["schemas"]["LeaveUpdateIn"];
export type LeaveCancelIn = components["schemas"]["LeaveCancelIn"];
export type LeaveCheckIn = components["schemas"]["LeaveCheckIn"];
export type LeaveWriteResultOut = components["schemas"]["LeaveWriteResultOut"];
export type LeaveCheckOut = components["schemas"]["LeaveCheckOut"];

// The filters of the leave list, as the URL carries them (all text). An empty or missing value is left out of the query.
export type LeaveListParams = {
  q?: string;
  employee?: string;
  status?: string;
  type?: string;
  from?: string;
  to?: string;
};

// The filters of the add pop-up's options. `from` is "assistant" when the pop-up was opened from the assistant.
export type LeaveOptionsParams = {
  employee?: string;
  type?: string;
  start?: string;
  end?: string;
  from?: string;
};

// Keeps only the values that were given (undefined or ""), so an empty filter is not sent at all.
export function present(values: Record<string, string | undefined>): Record<string, string> {
  const query: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query[name] = value;
  }
  return query;
}

// The leave rows, batch by batch. A changed filter is a new key: it starts again at offset 0 and keeps no old rows.
// `next_offset` is null when no row follows.
export function useLeaveList(filter: LeaveListParams) {
  return useInfiniteQuery({
    queryKey: ["leave", "list", filter],
    initialPageParam: 0,
    getNextPageParam: (last: LeaveListOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      // The schema types offset as a string, like the other query values.
      const query = { ...present({ ...filter }), offset: String(pageParam) };
      const result = await api.GET("/api/v1/leave", { params: { query } });
      return unwrapQuery<LeaveListOut>(result, "leave request failed");
    },
  });
}

// The choices of the add pop-up and its first values. Kept only while open (gcTime 0), and fetched again on every open:
// a cached copy could be older than the row another program changed (the stale check).
export function useLeaveOptions(params: LeaveOptionsParams) {
  return useQuery({
    queryKey: ["leave", "options", params],
    retry: retryMe,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/options", { params: { query: present({ ...params }) } });
      return unwrapQuery<LeaveOptionsOut>(result, "leave request failed");
    },
  });
}

// The edit pop-up's first values and the row as loaded (pk is the leave id).
export function useLeaveEdit(id: number) {
  return useQuery({
    queryKey: ["leave", "edit", id],
    retry: retryMe,
    // The row as loaded goes back with the save: it is read fresh on every open, never from the cache (gcTime 0).
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/{pk}", { params: { path: { pk: id } } });
      return unwrapQuery<LeaveEditOut>(result, "leave request failed");
    },
  });
}

// What the cancel pop-up asks (pk is the leave id).
export function useLeaveCancelInfo(id: number) {
  return useQuery({
    queryKey: ["leave", "cancel", id],
    retry: retryMe,
    // The loaded row goes back with the cancel: read fresh on every open, never from the cache (gcTime 0).
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/{pk}/cancel", { params: { path: { pk: id } } });
      return unwrapQuery<LeaveCancelInfoOut>(result, "leave request failed");
    },
  });
}

// After a leave write that saved (ok true), refreshes what it can change: every leave query, every employee's work
// data (the leave block; the key is ["employee", pk, "work"] and the write does not know the pk), «Миний даалгавар»'s
// user (["me"]) and the Today page. A refused write (ok false) changed nothing, so nothing is refreshed.
export async function refreshAfterLeaveWrite(queryClient: QueryClient, result: LeaveWriteResultOut): Promise<void> {
  if (!result.ok) return;
  await queryClient.invalidateQueries({ queryKey: ["leave"] });
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "employee" && query.queryKey[2] === "work",
  });
  // The employee's activity log (["employee", pk, "activity"]) and the employee log page (["logs-employee", …]) show the
  // write too; the write does not know the pk, so every employee's activity is refreshed by the predicate.
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "employee" && query.queryKey[2] === "activity",
  });
  await queryClient.invalidateQueries({ queryKey: ["logs-employee"] });
  await queryClient.invalidateQueries({ queryKey: ["me"] });
  await queryClient.invalidateQueries({ queryKey: ["today"] });
}

// Records a leave (the add pop-up). A refusal answers ok false with the form's messages; the caller shows them.
export function useCreateLeave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveWriteIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () => api.POST("/api/v1/leave", { body })),
    onSuccess: (result) => refreshAfterLeaveWrite(queryClient, result),
  });
}

// Changes recorded leave `id`. `loaded` (in the body) is the row as the edit pop-up loaded it; a row another program
// changed is refused with ok false.
export function useUpdateLeave(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveUpdateIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/{pk}", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterLeaveWrite(queryClient, result),
  });
}

// Cancels leave `id` (removes it, or marks it «Буруу бүртгэсэн» once it has started). Refused writes answer ok false.
export function useCancelLeave(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveCancelIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/{pk}/cancel", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterLeaveWrite(queryClient, result),
  });
}

// The live check of the form as posted. It writes nothing, so it invalidates nothing.
export function useCheckLeave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveCheckIn) =>
      postWithCsrfRetry<LeaveCheckOut>(queryClient, () => api.POST("/api/v1/leave/check", { body })),
  });
}
