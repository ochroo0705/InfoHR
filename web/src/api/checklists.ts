import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { checklistMineKey, refreshAfterChecklistWrite, refreshIfRefused } from "./checklistRefresh";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type ChecklistMineOut = components["schemas"]["ChecklistMineOut"];
export type ChecklistMineItemOut = components["schemas"]["ChecklistMineItemOut"];
export type ChecklistStartIn = components["schemas"]["ChecklistStartIn"];

export { checklistMineKey };

// «Миний даалгавар»: the signed-in user's own open tasks, earliest due first. Works without an employee record.
export function useChecklistMine() {
  return useQuery({
    queryKey: checklistMineKey,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/checklists/mine");
      return unwrapQuery<ChecklistMineOut>(result, "checklist request failed");
    },
  });
}

// «Хийгдсэн» on one checklist task (pk is the task id). A refused write (404, 409) refreshes the data, then rejects.
export function useTickTask() {
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

// «Буцаах» on one checklist task (pk is the task id). A refused write (404, 409) refreshes the data, then rejects.
export function useUntickTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pk: number) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/checklists/tasks/{pk}/untick", { params: { path: { pk } } }),
      ),
    onSuccess: () => refreshAfterChecklistWrite(queryClient),
    onError: (error) => refreshIfRefused(queryClient, error),
  });
}

// «Цуцлах» on one open checklist (pk is the checklist id). A refused write (404, 409) refreshes the data, then rejects.
export function useCancelChecklist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pk: number) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/checklists/{pk}/cancel", { params: { path: { pk } } }),
      ),
    onSuccess: () => refreshAfterChecklistWrite(queryClient),
    onError: (error) => refreshIfRefused(queryClient, error),
  });
}

// «Ажлаас гарах жагсаалт эхлүүлэх» for employee `employeeId`. The variables are the picked last day (anchor_day,
// a YYYY-MM-DD string). A refused write (404, 409) refreshes the data; a 400 (bad date) does not.
export function useStartOffboarding(employeeId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (anchorDay: string) => {
      const body: ChecklistStartIn = { anchor_day: anchorDay };
      return postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/checklists/employees/{employee_id}/start", {
          params: { path: { employee_id: employeeId } },
          body,
        }),
      );
    },
    onSuccess: () => refreshAfterChecklistWrite(queryClient),
    onError: (error) => refreshIfRefused(queryClient, error),
  });
}
