import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { refreshAfterChecklistWrite, refreshIfRefused } from "./checklistRefresh";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type MeOut = components["schemas"]["MeOut"];
export type NoticeIn = components["schemas"]["NoticeIn"];

// A 401, 403 or 404 does not change on a retry, so it fails at once (a missing My page shows NotFound without a delay).
const NO_RETRY_STATUSES: number[] = [401, 403, 404];

export function retryMe(count: number, error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status ?? 0;
  return !NO_RETRY_STATUSES.includes(status) && count < 3;
}

// The My page of the signed-in user.
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    retry: retryMe,
    queryFn: async () => {
      const result = await api.GET("/api/v1/me");
      return unwrapQuery<MeOut>(result, "me request failed");
    },
  });
}

// «Мэдлээ» on one result notice.
export function useDismissNotice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NoticeIn) =>
      postWithCsrfRetry<void>(queryClient, () => api.POST("/api/v1/me/notice", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
}

// «Буцаах»: take back one's own waiting request.
export function useWithdraw() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pk: number) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/me/requests/{pk}/withdraw", { params: { path: { pk } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
}

// «Хийгдсэн» on a checklist task. A tick changes the Today page, the employee work data and «Миний даалгавар» too
// (the same refresh as the checklist writes); a refused tick (404, 409) refreshes them and then rejects.
export function useTick() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pk: number) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/checklists/tasks/{pk}/tick", { params: { path: { pk } } }),
      ),
    onSuccess: () => refreshAfterChecklistWrite(queryClient),
    onError: (error) => refreshIfRefused(queryClient, error),
  });
}
