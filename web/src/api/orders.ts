import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { invalidateEventWrites, type HrPopupOut, type HrPopupResultOut } from "./events";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type OrderHistoryOut = components["schemas"]["OrderHistoryOut"];

// Which pop-up of an order: the edit (number, date, summary, issued by), the scan upload (one file box) or the cancel
// (the reason).
export type OrderPopupKind = "edit" | "upload" | "cancel";

// The edit, upload or cancel pop-up of one order. Kept only while open (gcTime 0), like useCorrectionForm.
export function useOrderPopup(pk: number, orderId: number, kind: OrderPopupKind, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "order-popup", orderId, kind],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    // A reconnect refetch would replace the form under what the user has typed.
    refetchOnReconnect: false,
    queryFn: async () => {
      if (kind === "edit") {
        const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/edit", {
          params: { path: { pk, order_id: orderId } },
        });
        return unwrapQuery<HrPopupOut>(result, "order request failed");
      }
      if (kind === "cancel") {
        const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/cancel", {
          params: { path: { pk, order_id: orderId } },
        });
        return unwrapQuery<HrPopupOut>(result, "order request failed");
      }
      const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/upload", {
        params: { path: { pk, order_id: orderId } },
      });
      return unwrapQuery<HrPopupOut>(result, "order request failed");
    },
  });
}

// Cancels a registered order with the posted reason (field name `reason`). A refusal answers 200 with ok false and
// writes nothing; nothing is invalidated then.
export function useSubmitOrderCancel(pk: number, orderId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: { values: Record<string, string> }) =>
      postWithCsrfRetry<HrPopupResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/orders/{order_id}/cancel", {
          params: { path: { pk, order_id: orderId } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateOrderWrites(queryClient, pk);
      }
    },
  });
}

// Saves the edit of an order. Field names are unprefixed (number, date, summary, issued_by). A refusal answers 200 with
// ok false and writes nothing; nothing is invalidated then.
export function useSubmitOrderEdit(pk: number, orderId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: { values: Record<string, string> }) =>
      postWithCsrfRetry<HrPopupResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/orders/{order_id}/edit", {
          params: { path: { pk, order_id: orderId } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateOrderWrites(queryClient, pk);
      }
    },
  });
}

// Attaches the signed scan of an order. The typed body cannot carry a file, so the serializer builds the multipart
// body with the file as part `file`. With no file (null) the multipart body has no `file` part, so the server answers
// its own «required» message. A refused file (wrong type, too big, missing) answers 200 with ok false.
export function useSubmitOrderUpload(pk: number, orderId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file }: { file: File | null }) =>
      postWithCsrfRetry<HrPopupResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/orders/{order_id}/upload", {
          params: { path: { pk, order_id: orderId } },
          body: {},
          bodySerializer: () => {
            const form = new FormData();
            if (file) form.append("file", file);
            return form;
          },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateOrderWrites(queryClient, pk);
      }
    },
  });
}

// The order's history (newest first). Read-only: a write never refreshes it, and nothing here invalidates.
export function useOrderHistory(pk: number, orderId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "order-history", orderId],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/history", {
        params: { path: { pk, order_id: orderId } },
      });
      return unwrapQuery<OrderHistoryOut>(result, "order request failed");
    },
  });
}

// An order edit or upload changes what an event changes (work, salary, activity, and the Today and attention lists), so
// it invalidates the same keys as an event write. Nothing is invalidated on a refusal (ok false).
function invalidateOrderWrites(queryClient: QueryClient, pk: number) {
  return invalidateEventWrites(queryClient, pk);
}
