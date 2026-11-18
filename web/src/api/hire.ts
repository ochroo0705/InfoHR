import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components, operations } from "./schema";

export type HireFormOut = components["schemas"]["HireFormOut"];
export type HireTabOut = components["schemas"]["HireTabOut"];
export type HireSectionOut = components["schemas"]["HireSectionOut"];
export type HireReviewOut = components["schemas"]["HireReviewOut"];
export type HireDuplicateOut = components["schemas"]["HireDuplicateOut"];
export type HireResultOut = components["schemas"]["HireResultOut"];
export type HireRegisterCheckOut = components["schemas"]["HireRegisterCheckOut"];
export type HireRegisterMatchOut = components["schemas"]["HireRegisterMatchOut"];
export type HireOrderSuggestOut = components["schemas"]["HireOrderSuggestOut"];
export type HireDecisionOut = components["schemas"]["HireDecisionOut"];
export type HireChoiceOut = components["schemas"]["EmployeeFormChoiceOut"];
// The body of the hire POST, as the API declares it. The photo is added by the serializer (the typed body cannot carry
// a file).
type HireSubmitBody = NonNullable<
  operations["api_hire_hire_create"]["requestBody"]
>["content"]["multipart/form-data"];

export type HireSubmitArgs = {
  values: Record<string, string>;
  candidate: string;
  submission: string;
  photo: File | null;
};

// The hire form's description (layout, fields, gating). Its values are the page's own state after the first load, so
// the query is not kept in the cache (gcTime 0) and does not refetch on focus or reconnect: a refetch would replace the
// layout under what the user has typed. A 403 or 404 is not retried (retryMe).
export function useHireForm(candidate: string, submission: string) {
  return useQuery({
    queryKey: ["hire-form", candidate, submission],
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/new", {
        params: { query: { candidate, submission } },
      });
      return unwrapQuery<HireFormOut>(result, "hire request failed");
    },
  });
}

// The multipart body of the hire: the `values` JSON text, the hidden candidate and submission ids, and the photo when
// one is given (omitted when null).
function hireFormData(body: HireSubmitBody, photo: File | null): FormData {
  const form = new FormData();
  form.append("values", body.values);
  form.append("candidate", body.candidate ?? "");
  form.append("submission", body.submission ?? "");
  if (photo) {
    form.append("photo", photo);
  }
  return form;
}

// Hires the employee. A refused form answers 200 with ok false (the caller shows the messages); nothing is written then.
// Takes the query client for the CSRF retry, as the other mutation helpers do.
export function hireSubmit(queryClient: QueryClient, args: HireSubmitArgs): Promise<HireResultOut> {
  const body: HireSubmitBody = {
    values: JSON.stringify(args.values),
    candidate: args.candidate,
    submission: args.submission,
  };
  return postWithCsrfRetry<HireResultOut>(queryClient, () =>
    api.POST("/api/v1/employees", {
      body,
      bodySerializer: (formBody) => hireFormData(formBody, args.photo),
    }),
  );
}

// The hire as a mutation. A successful hire refreshes the lists that show it: the today hires line, attention and the
// signed-in user's own page. Nothing is invalidated on a refusal.
export function useHireSubmit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: HireSubmitArgs) => hireSubmit(queryClient, args),
    onSuccess: async (result) => {
      if (result.ok) {
        await queryClient.invalidateQueries({ queryKey: ["today"] });
        await queryClient.invalidateQueries({ queryKey: ["attention"] });
        await queryClient.invalidateQueries({ queryKey: ["me"] });
      }
    },
  });
}

// The live register check. An empty or blank value looks nobody up and makes no request.
export async function checkRegister(value: string): Promise<HireRegisterMatchOut | null> {
  if (value.trim() === "") return null;
  const result = await api.GET("/api/v1/employees/check-register", {
    params: { query: { register_no: value } },
  });
  const data = unwrapQuery<HireRegisterCheckOut>(result, "hire request failed");
  return data.match;
}

// The district options of a city (the district select follows the city). An unknown city gives an empty list.
export async function fetchDistricts(city: string): Promise<HireChoiceOut[]> {
  const result = await api.GET("/api/v1/employees/districts", { params: { query: { city } } });
  return unwrapQuery<HireChoiceOut[]>(result, "hire request failed");
}

// The «Санал болгох» answer: the next order number of the year of `date`, and the date to use when the form's is empty.
// An empty date sends no `date` parameter at all (order_suggest.js does the same: `?date=` only when the box has a value).
export async function suggestOrderNumber(date: string): Promise<HireOrderSuggestOut> {
  const result = await api.GET("/api/v1/employees/order-suggest", {
    params: { query: date ? { date } : {} },
  });
  return unwrapQuery<HireOrderSuggestOut>(result, "hire request failed");
}

// HR sends a submitted self-form back to the employee with a note. A refusal (ok false) is returned, not thrown.
export function sendBack(queryClient: QueryClient, pk: number, note: string): Promise<HireDecisionOut> {
  return postWithCsrfRetry<HireDecisionOut>(queryClient, () =>
    api.POST("/api/v1/selfforms/{pk}/send-back", { params: { path: { pk } }, body: { note } }),
  );
}

// HR rejects a submitted self-form for good, with the reason. A refusal (ok false) is returned, not thrown.
export function rejectSubmission(queryClient: QueryClient, pk: number, reason: string): Promise<HireDecisionOut> {
  return postWithCsrfRetry<HireDecisionOut>(queryClient, () =>
    api.POST("/api/v1/selfforms/{pk}/reject", { params: { path: { pk } }, body: { reason } }),
  );
}
