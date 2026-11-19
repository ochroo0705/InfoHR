import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { invalidateEventWrites } from "./events";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type OrderDetailOut = components["schemas"]["OrderDetailOut"];
export type OrderSignOut = components["schemas"]["OrderSignOut"];
export type OrderSignResultOut = components["schemas"]["OrderSignResultOut"];
export type OrderSignIn = components["schemas"]["OrderSignIn"];
export type OkOut = components["schemas"]["OkOut"];

// The whole order pop-up (the detail). Kept only while open (gcTime 0); it does not refetch on focus or reconnect.
export function useOrderDetail(pk: number, orderId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "order-detail", orderId],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/detail", {
        params: { path: { pk, order_id: orderId } },
      });
      return unwrapQuery<OrderDetailOut>(result, "order request failed");
    },
  });
}

// The signing pop-up's data (title, whether the user has a saved signature). Same caching rules as the detail.
export function useOrderSignState(pk: number, orderId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "order-sign", orderId],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/orders/{order_id}/sign", {
        params: { path: { pk, order_id: orderId } },
      });
      return unwrapQuery<OrderSignOut>(result, "order request failed");
    },
  });
}

// Signs the registered order (mode saved or drawn). A refusal answers 200 with ok false and the messages; nothing is
// invalidated then.
export function useSubmitOrderSign(pk: number, orderId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OrderSignIn) =>
      postWithCsrfRetry<OrderSignResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/orders/{order_id}/sign", {
          params: { path: { pk, order_id: orderId } },
          body,
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEventWrites(queryClient, pk);
      }
    },
  });
}

// Deletes the signed-in user's own saved signature. Only the user's signature query is invalidated; the open sign
// pop-up refetches its own state.
export function useDeleteSavedSignature() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<OkOut>(queryClient, () => api.POST("/api/v1/me/signature/delete")),
    onSuccess: (result) => {
      if (result.ok) {
        return queryClient.invalidateQueries({ queryKey: ["me", "signature"] });
      }
    },
  });
}
