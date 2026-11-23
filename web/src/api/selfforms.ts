import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type SelfFormListOut = components["schemas"]["SelfFormListOut"];
export type SelfFormListRowOut = components["schemas"]["SelfFormListRowOut"];
export type SelfFormCreateFormOut = components["schemas"]["SelfFormCreateFormOut"];
export type SelfFormCreateIn = components["schemas"]["SelfFormCreateIn"];
export type SelfFormCreateOut = components["schemas"]["SelfFormCreateOut"];
export type SelfFormShowOut = components["schemas"]["SelfFormShowOut"];
export type SelfFormActionOut = components["schemas"]["SelfFormActionOut"];

// The list of self-form links with the waiting count (the list page's query).
export const selfFormListKey = ["selfforms"];

// One form's page (Task 10 reads it through this key).
export function selfFormShowKey(pk: number): unknown[] {
  return ["selfform", pk];
}

// The nav query is ["nav", pathname] (shell/TopBar.tsx); it carries the waiting-self-forms badge. There is no key
// constant for it, so the create helper refreshes the whole ["nav"] prefix.
const NAV_KEY = ["nav"];

// The rows, the waiting count and the create form's description. 403 for a user without the manage right.
// (The show query and the extend/revoke helpers are at the end of this file.)
export function useSelfFormList() {
  return useQuery({
    queryKey: selfFormListKey,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/selfforms");
      return unwrapQuery<SelfFormListOut>(result, "self-form request failed");
    },
  });
}

// Creates a link. A refusal answers 200 with ok false and writes nothing, so nothing is invalidated then.
export async function createSelfForm(queryClient: QueryClient, body: SelfFormCreateIn): Promise<SelfFormCreateOut> {
  const result = await postWithCsrfRetry<SelfFormCreateOut>(queryClient, () =>
    api.POST("/api/v1/selfforms", { body }),
  );
  if (result.ok) {
    await queryClient.invalidateQueries({ queryKey: selfFormListKey });
    await queryClient.invalidateQueries({ queryKey: NAV_KEY });
  }
  return result;
}

// One form's page: the link, its state and the HR decision. The link is a secret, so the page keeps nothing once it is
// left (gcTime 0) and does not refetch when the window regains focus. 403 without the manage right, 404 outside scope.
export function useSelfFormShow(pk: number) {
  return useQuery({
    queryKey: selfFormShowKey(pk),
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/selfforms/{pk}", { params: { path: { pk } } });
      return unwrapQuery<SelfFormShowOut>(result, "self-form request failed");
    },
  });
}

// After an extend or a revoke: a result's show replaces the page's data. A written result (ok true) also refreshes the
// list and the nav badge; a refusal writes nothing, so it only sets the show (the same state) and invalidates nothing.
// The show is set only while the page's query is still in the cache (the page is mounted): a result that lands after the
// user left must not create a new cache entry for the link, which would live for the default 5 minutes.
async function applyAction(queryClient: QueryClient, pk: number, result: SelfFormActionOut): Promise<void> {
  if (result.show && queryClient.getQueryState(selfFormShowKey(pk)) !== undefined) {
    queryClient.setQueryData(selfFormShowKey(pk), result.show);
  }
  if (result.ok) {
    await queryClient.invalidateQueries({ queryKey: selfFormListKey });
    await queryClient.invalidateQueries({ queryKey: NAV_KEY });
  }
}

// Adds hours to an open or expired link. An empty box is sent as null (the company default).
export async function extendSelfForm(
  queryClient: QueryClient,
  pk: number,
  hours: string | null,
): Promise<SelfFormActionOut> {
  const result = await postWithCsrfRetry<SelfFormActionOut>(queryClient, () =>
    api.POST("/api/v1/selfforms/{pk}/extend", { params: { path: { pk } }, body: { hours } }),
  );
  await applyAction(queryClient, pk, result);
  return result;
}

// Cancels an open link so the employee cannot fill it any more.
export async function revokeSelfForm(queryClient: QueryClient, pk: number): Promise<SelfFormActionOut> {
  const result = await postWithCsrfRetry<SelfFormActionOut>(queryClient, () =>
    api.POST("/api/v1/selfforms/{pk}/revoke", { params: { path: { pk } } }),
  );
  await applyAction(queryClient, pk, result);
  return result;
}
