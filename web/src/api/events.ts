import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import { invalidateEmployee } from "./employeeWrites";
import type { components } from "./schema";

export type EventFormOut = components["schemas"]["EventFormOut"];
export type EventWriteResultOut = components["schemas"]["EventWriteResultOut"];
export type HrPopupOut = components["schemas"]["HrPopupOut"];
export type HrPopupResultOut = components["schemas"]["HrPopupResultOut"];

// The typed values of an event form. `prev_effective` is the hidden date the page holds (the last real date).
export type EventFormVars = {
  values: Record<string, string>;
  prev_effective: string;
};

// The first open of a form: no values typed yet and an empty prev_effective. The server reads exactly this pair as
// the first open (events.py _open_state), so both fields are sent; the schema requires the key.
const FIRST_OPEN: EventFormVars = { values: {}, prev_effective: "" };

// Loads the event form for the values typed so far (kind, date and summary refreshes). Not a hook: the change handlers
// call it. Nothing is written; a 403 (no right to record the type) or 404 (unknown type) rejects.
export function loadEventForm(
  queryClient: QueryClient,
  pk: number,
  type: string,
  vars: EventFormVars,
): Promise<EventFormOut> {
  return postWithCsrfRetry<EventFormOut>(queryClient, () =>
    api.POST("/api/v1/employees/{pk}/events/{type}/form", {
      params: { path: { pk, type } },
      body: { values: vars.values, prev_effective: vars.prev_effective },
    }),
  );
}

// The event form on its first open. Kept only while open (gcTime 0): it carries values the user may change, so it
// does not refetch on focus or reconnect (the same rules as useCorrectionForm).
export function useEventForm(pk: number, type: string, enabled: boolean) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["employee", pk, "event-form", type],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    // A reconnect refetch would replace the form under what the user has typed.
    refetchOnReconnect: false,
    queryFn: () => loadEventForm(queryClient, pk, type, FIRST_OPEN),
  });
}

// Records an event. `values` carries the form's fields by HTML name. The hidden value travels as the key prev_effective
// inside values; the server keeps the last real date on a refused save. A refusal answers 200 with ok false and writes
// nothing; nothing is invalidated then.
export function useSubmitEvent(pk: number, type: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: { values: Record<string, string> }) =>
      postWithCsrfRetry<EventWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/events/{type}", { params: { path: { pk, type } }, body: { values } }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEventWrites(queryClient, pk);
      }
    },
  });
}

// The cancel pop-up of one event (title, hint and its fields). 404 once the event is applied or cancelled.
export function useEventCancelForm(pk: number, eventId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["employee", pk, "event-cancel-form", eventId],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/events/{event_id}/cancel", {
        params: { path: { pk, event_id: eventId } },
      });
      return unwrapQuery<HrPopupOut>(result, "employee request failed");
    },
  });
}

// Cancels one event. A refusal (no reason, a signed order without its cancel order number) answers 200 with ok false.
export function useSubmitEventCancel(pk: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: { values: Record<string, string> }) =>
      postWithCsrfRetry<HrPopupResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/events/{event_id}/cancel", {
          params: { path: { pk, event_id: eventId } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEventWrites(queryClient, pk);
      }
    },
  });
}

// An event write (record or cancel) changes the employee's work, salary and activity, and the Today and attention
// lists that show it. ["today"] is a prefix, so its open sub-lists refresh too. The orders register shows the same
// orders (a cancel or sign from it), so ["orders-register"] refreshes too. Exported for the order writes, which change
// the same parts (an order that has an event applies its change).
export function invalidateEventWrites(queryClient: QueryClient, pk: number) {
  return Promise.all([
    invalidateEmployee(queryClient, pk, ["work", "salary", "activity"]),
    queryClient.invalidateQueries({ queryKey: ["today"] }),
    queryClient.invalidateQueries({ queryKey: ["attention"] }),
    queryClient.invalidateQueries({ queryKey: ["orders-register"] }),
  ]);
}
