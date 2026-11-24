import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { apiFailure, postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type ListsIndexOut = components["schemas"]["ListIndexOut"];
export type ListIndexItemOut = components["schemas"]["ListIndexItemOut"];
export type ListMeaningOut = components["schemas"]["ListMeaningOut"];
export type ListMeaningRowOut = components["schemas"]["ListMeaningRowOut"];
export type ListMeaningOptionOut = components["schemas"]["ListMeaningOptionOut"];
export type ListPageOut = components["schemas"]["ListPageOut"];
export type ListRowOut = components["schemas"]["ListRowOut"];
export type ListColumnOut = components["schemas"]["ListColumnOut"];
export type ListFormOut = components["schemas"]["ListFormOut"];
export type ListFieldOut = components["schemas"]["ListFieldOut"];
export type ListChoiceOut = components["schemas"]["ListChoiceOut"];
export type ListSaveOut = components["schemas"]["ListSaveOut"];
export type ListOkOut = components["schemas"]["ListOkOut"];
export type ListQuickOut = components["schemas"]["ListQuickOut"];
export type ListQuickErrorOut = components["schemas"]["ListQuickErrorOut"];

// What a quick-add answers: the picked or created entry (ListQuickOut, the shape Select reads as {value, label, existed}),
// or the refusal (ListQuickErrorOut, with `error` and `field_errors`). Tell them apart by `"error" in reply`.
export type QuickAddReply = ListQuickOut | ListQuickErrorOut;

// The form values of a write: every box by its field name; an empty box is "".
export type ListValues = Record<string, string>;

// Query keys. Every list key starts with "lists", so one prefix covers them all. A list's page and its forms share the
// slug in the key, so a write refreshes exactly the list it changed.
export const listKeys = {
  index: (q: string) => ["lists", "index", q] as const,
  meaning: () => ["lists", "meaning"] as const,
  page: (slug: string) => ["lists", "page", slug] as const,
  form: (slug: string, pk: number | undefined) => ["lists", "form", slug, pk === undefined ? "add" : pk] as const,
};

// The lists index for a search text. The text is sent as typed; the server trims it.
export function useListsIndex(q: string) {
  return useQuery({
    queryKey: listKeys.index(q),
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/lists", { params: { query: { q } } });
      return unwrapQuery<ListsIndexOut>(result, "list request failed");
    },
  });
}

// The «Утгын холбоо» page: each meaning with its options and the chosen entry.
export function useMeaning() {
  return useQuery({
    queryKey: listKeys.meaning(),
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/lists/meaning");
      return unwrapQuery<ListMeaningOut>(result, "list request failed");
    },
  });
}

// One list's columns and rows.
export function useListPage(slug: string) {
  return useQuery({
    queryKey: listKeys.page(slug),
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/lists/{slug}", { params: { path: { slug } } });
      return unwrapQuery<ListPageOut>(result, "list request failed");
    },
  });
}

// The pop-up form of a list: the add form with no pk, the edit form of entry `pk`. Only fetched while the pop-up is open
// (`enabled`); kept only while it is shown (gcTime 0), because it carries values the user may change.
export function useListForm(slug: string, pk: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: listKeys.form(slug, pk),
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/lists/{slug}/form", {
        params: { path: { slug }, query: pk === undefined ? {} : { pk: String(pk) } },
      });
      return unwrapQuery<ListFormOut>(result, "list request failed");
    },
  });
}

// Refreshes what an entry write of list `slug` can change: the index counts, the list's page, its open forms and the
// meanings (their options show entry names). Each key is a prefix, so every form of the list is refreshed.
export function invalidateListEntries(queryClient: QueryClient, slug: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["lists", "index"] }),
    queryClient.invalidateQueries({ queryKey: listKeys.page(slug) }),
    queryClient.invalidateQueries({ queryKey: ["lists", "form", slug] }),
    queryClient.invalidateQueries({ queryKey: listKeys.meaning() }),
  ]);
}

// Saves the «Утгын холбоо» choices. An empty value deletes that meaning; the server ignores junk and unknown pks.
export function useSaveMeaning() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: ListValues) =>
      postWithCsrfRetry<ListOkOut>(queryClient, () => api.POST("/api/v1/lists/meaning", { body: { values } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKeys.meaning() }),
  });
}

// Adds an entry (pk undefined) or changes entry `pk` of list `slug`. A refusal answers 200 with ok false and writes
// nothing, so nothing is invalidated then; the caller shows the errors and keeps the pop-up open.
export function useSaveEntry(slug: string, pk?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: ListValues) =>
      postWithCsrfRetry<ListSaveOut>(queryClient, () =>
        pk === undefined
          ? api.POST("/api/v1/lists/{slug}", { params: { path: { slug } }, body: { values } })
          : api.POST("/api/v1/lists/{slug}/{pk}", {
              params: { path: { slug, pk: String(pk) } },
              body: { values },
            }),
      ),
    onSuccess: (result) => {
      if (result.ok) return invalidateListEntries(queryClient, slug);
    },
  });
}

// Deletes entry `pk` of list `slug`. An entry still in use answers ok false with the message; nothing is invalidated then.
export function useDeleteEntry(slug: string, pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<ListSaveOut>(queryClient, () =>
        api.POST("/api/v1/lists/{slug}/{pk}/delete", { params: { path: { slug, pk: String(pk) } } }),
      ),
    onSuccess: (result) => {
      if (result.ok) return invalidateListEntries(queryClient, slug);
    },
  });
}

// Adds an entry from a form dropdown (Select's add line, or QuickAddModal). Answers the Select reply: the picked entry on
// 200, the refusal on 400. Other failures (403 for no right, 404 for an unknown list) throw an ApiFailure. This does not
// refresh the lists by itself (it has no query client); the caller that shows a list calls invalidateListEntries.
export async function quickAddEntry(slug: string, values: ListValues): Promise<QuickAddReply> {
  const result = await api.POST("/api/v1/lists/{slug}/quick", { params: { path: { slug } }, body: { values } });
  if (result.data !== undefined) return result.data;
  if (result.response.status === 400 && result.error !== undefined && "error" in (result.error as object))
    return result.error as ListQuickErrorOut;
  throw apiFailure(result.response, result.error, "request failed");
}
