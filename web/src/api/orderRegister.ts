import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type OrderRegisterOut = components["schemas"]["OrderRegisterOut"];
export type OrderRegisterRowOut = components["schemas"]["OrderRegisterRowOut"];
export type OrderPrintOut = components["schemas"]["OrderPrintOut"];
export type OrderPrintStartOut = components["schemas"]["OrderPrintStartOut"];
export type OrderPrintStatusOut = components["schemas"]["OrderPrintStatusOut"];
export type OrderRegisterQueryOut = components["schemas"]["OrderRegisterQueryOut"];
export type OrderRegisterOptionsOut = components["schemas"]["OrderRegisterOptionsOut"];
export type OrderRegisterAllLabelsOut = components["schemas"]["OrderRegisterAllLabelsOut"];

// The filter, sort and search values of the register, as the URL carries them (all text; the server cleans them).
export type RegisterParams = {
  q: string;
  sort: string;
  year: string;
  order_type: string;
  department: string;
  state: string;
};

// The register rows, batch by batch. A later batch adds rows; a changed filter or sort is a new key, so it starts again
// at offset 0 and the rows of the old filter are not kept. `next_offset` is null when no row follows.
export function useOrderRegister(params: RegisterParams) {
  return useInfiniteQuery({
    queryKey: ["orders-register", params],
    initialPageParam: 0,
    getNextPageParam: (last: OrderRegisterOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      const result = await api.GET("/api/v1/orders/register", {
        // The schema types offset as a string, like the other query values.
        params: { query: { ...params, offset: String(pageParam) } },
      });
      return unwrapQuery<OrderRegisterOut>(result, "order request failed");
    },
  });
}

// The print page's data: every matching row, grouped by department. Each load writes one export log line, so the query
// is never refetched by itself (no focus or reconnect refetch, and it is not kept after the page goes).
export function useOrderPrint(params: RegisterParams) {
  return useQuery({
    queryKey: ["orders-print", params],
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/orders/print", { params: { query: params } });
      return unwrapQuery<OrderPrintOut>(result, "order request failed");
    },
  });
}

// Starts the PDF of the ticked orders as a background job (11 orders or more). The job's token, status path and file
// path come back; the result is held by the caller, never in the query cache. The ids travel as form values: one `ids`
// field per order, as the plain form does.
export function useStartPrintJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) =>
      postWithCsrfRetry<OrderPrintStartOut>(queryClient, () =>
        api.POST("/api/v1/orders/print/start", {
          body: { ids: ids.map(String) },
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          bodySerializer: (body) => formIds(body.ids ?? []),
        }),
      ),
  });
}

// The state of one background job ("running", "ready" or "failed"). Only the user who started it may read it; another
// user's or an unknown token answers 404 (the rejection carries status 404).
export async function fetchPrintStatus(token: string): Promise<OrderPrintStatusOut> {
  const result = await api.GET("/api/v1/orders/print/{token}/status", { params: { path: { token } } });
  return unwrapQuery<OrderPrintStatusOut>(result, "order request failed");
}

// One `ids` field per id, repeated, in form encoding. Returned as a string: a URLSearchParams body is not accepted by
// the Request of the test environment (jsdom's URLSearchParams is another realm), and the header is set explicitly.
function formIds(ids: string[]): string {
  const form = new URLSearchParams();
  for (const id of ids) form.append("ids", id);
  return form.toString();
}
