import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { refreshAfterLeaveWrite } from "./leave";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type LeaveRequestListOut = components["schemas"]["LeaveRequestListOut"];
export type LeaveRequestRowOut = components["schemas"]["LeaveRequestRowOut"];
export type LeaveRequestStatusOut = components["schemas"]["LeaveRequestStatusOut"];
export type LeaveRequestOptionsOut = components["schemas"]["LeaveRequestOptionsOut"];
export type LeaveRequestDetailOut = components["schemas"]["LeaveRequestDetailOut"];
export type LeaveRequestHistoryOut = components["schemas"]["LeaveRequestHistoryOut"];
export type LeaveRequestOtherOut = components["schemas"]["LeaveRequestOtherOut"];
export type LeaveRequestFormIn = components["schemas"]["LeaveRequestFormIn"];
export type LeaveRequestApproveIn = components["schemas"]["LeaveRequestApproveIn"];
export type LeaveRequestRejectIn = components["schemas"]["LeaveRequestRejectIn"];
export type LeaveWriteResultOut = components["schemas"]["LeaveWriteResultOut"];
export type LeaveCheckOut = components["schemas"]["LeaveCheckOut"];

// The filters of the requests list, as the URL carries them (all text). An empty or missing value is left out of the query.
export type LeaveRequestListParams = {
  tab?: string;
  status?: string;
};

// Keeps only the values that were given (undefined or ""), so an empty filter is not sent at all.
function present(values: Record<string, string | undefined>): Record<string, string> {
  const query: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query[name] = value;
  }
  return query;
}

function detailKey(id: number) {
  return ["leave", "requests", "detail", id];
}

// The requests list, batch by batch. A changed filter is a new key: it starts again at offset 0 and keeps no old rows.
// `next_offset` is null when no row follows.
export function useLeaveRequests(params: LeaveRequestListParams) {
  return useInfiniteQuery({
    queryKey: ["leave", "requests", "list", params],
    initialPageParam: 0,
    getNextPageParam: (last: LeaveRequestListOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      // The schema types offset as a string, like the other query values.
      const query = { ...present({ ...params }), offset: String(pageParam) };
      const result = await api.GET("/api/v1/leave/requests", { params: { query } });
      return unwrapQuery<LeaveRequestListOut>(result, "leave request failed");
    },
  });
}

// The detail pop-up of request `id`. Kept only while open (gcTime 0) and read fresh on every open: the `step` the screen
// sends back with the approve or reject comes from this read, so a cached copy could be a step that has moved on.
export function useLeaveRequestDetail(id: number) {
  return useQuery({
    queryKey: detailKey(id),
    retry: retryMe,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/requests/{pk}", { params: { path: { pk: id } } });
      return unwrapQuery<LeaveRequestDetailOut>(result, "leave request failed");
    },
  });
}

// The types the staff request form offers. Kept only while open (gcTime 0), fetched again on every open.
export function useLeaveRequestOptions() {
  return useQuery({
    queryKey: ["leave", "requests", "options"],
    retry: retryMe,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/leave/requests/options");
      return unwrapQuery<LeaveRequestOptionsOut>(result, "leave request failed");
    },
  });
}

// After a request write that saved (ok true): the leave refresh (every leave query, employee work and activity, the
// employee log, «Миний даалгавар», the Today page), then the requests list, the attention box and the nav badge.
async function refreshAfterRequestWrite(queryClient: QueryClient, result: LeaveWriteResultOut): Promise<void> {
  if (!result.ok) return;
  await refreshAfterLeaveWrite(queryClient, result);
  await queryClient.invalidateQueries({ queryKey: ["leave", "requests"] });
  await queryClient.invalidateQueries({ queryKey: ["attention"] });
  await queryClient.invalidateQueries({ queryKey: ["nav"] });
}

// Approve or reject: ok true refreshes everything above. A refusal (ok false, e.g. the step moved on) changed nothing
// that the lists show, but the open pop-up's request may have moved on, so only its detail is refreshed.
async function afterDecision(queryClient: QueryClient, id: number, result: LeaveWriteResultOut): Promise<void> {
  if (result.ok) {
    await refreshAfterRequestWrite(queryClient, result);
    return;
  }
  await queryClient.invalidateQueries({ queryKey: detailKey(id) });
}

// A decision answered 404: the request was decided or withdrawn meanwhile. Its detail is refetched, so the open pop-up
// redraws as decided (the screen shows the text and drops the buttons).
function afterDecisionNotFound(queryClient: QueryClient, id: number, error: unknown): void {
  if ((error as { status?: number } | null)?.status === 404) {
    void queryClient.invalidateQueries({ queryKey: detailKey(id) });
  }
}

// Approves the current step of request `id`. The last step writes the leave.
export function useApproveRequest(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveRequestApproveIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/requests/{pk}/approve", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => afterDecision(queryClient, id, result),
    onError: (error) => afterDecisionNotFound(queryClient, id, error),
  });
}

// Rejects request `id` at its current step. The reason is required; no leave is written.
export function useRejectRequest(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveRequestRejectIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/requests/{pk}/reject", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => afterDecision(queryClient, id, result),
    onError: (error) => afterDecisionNotFound(queryClient, id, error),
  });
}

// Submits a leave request for the user's own record. A refusal answers ok false with the form's messages; nothing is
// refreshed then.
export function useCreateLeaveRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveRequestFormIn) =>
      postWithCsrfRetry<LeaveWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/leave/requests", { body }),
      ),
    onSuccess: (result) => refreshAfterRequestWrite(queryClient, result),
  });
}

// The live preview of the request form. It writes nothing, so it invalidates nothing.
export function useCheckLeaveRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LeaveRequestFormIn) =>
      postWithCsrfRetry<LeaveCheckOut>(queryClient, () => api.POST("/api/v1/leave/requests/check", { body })),
  });
}
