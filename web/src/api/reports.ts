import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type ReportCatalogueOut = components["schemas"]["ReportCatalogueOut"];
export type ReportPageOut = components["schemas"]["ReportPageOut"];
export type ReportTableOut = components["schemas"]["ReportTableOut"];
export type ReportRowsOut = components["schemas"]["ReportRowsOut"];
export type ReportGroupOut = components["schemas"]["ReportGroupOut"];
export type ReportCellOut = components["schemas"]["ReportCellOut"];
export type ReportHeadCellOut = components["schemas"]["ReportHeadCellOut"];
export type ReportColumnsModelOut = components["schemas"]["ReportColumnsModelOut"];
export type ReportRulesModelOut = components["schemas"]["ReportRulesModelOut"];
export type ReportFormatModelOut = components["schemas"]["ReportFormatModelOut"];
export type ReportViewFormOut = components["schemas"]["ReportViewFormOut"];
export type ReportViewIn = components["schemas"]["ReportViewIn"];
export type ReportViewResultOut = components["schemas"]["ReportViewResultOut"];

// Where a saved-view form comes from: the «Хадгалах» pop-up of a report (the address goes with it, the server reads it),
// or the «Засах» pop-up of a view by its id.
export type ViewFormTarget = { key: string; query: string } | { pk: number };

export const reportKeys = {
  catalogue: ["reports", "catalogue"] as const,
  page: (key: string, query: string) => ["reports", key, query] as const,
  // `seed` is the page's dataUpdatedAt the first batch came from: a new page answer is a new query, seeded afresh.
  rows: (key: string, query: string, seed: number) => ["reports", key, "rows", query, seed] as const,
};

// The pop-up models take the address without an offset: the query is sent verbatim, a leading "?" dropped.
function addressQuery(query: string): string {
  return query.startsWith("?") ? query.slice(1) : query;
}

// The address query is the filters, sent exactly as the address carries them. A leading "?" is dropped, nothing else is
// touched: the percent-encoding, repeated keys and their order are the API's input. `offset` is the one value this
// module adds, last, so the batch position is the only thing that differs between requests for the same address.
function addressSearch(query: string, offset: number): string {
  const raw = query.startsWith("?") ? query.slice(1) : query;
  const tail = `offset=${offset}`;
  return raw ? `${raw}&${tail}` : tail;
}

// The catalogue of reports the user may open, as the API draws it.
export async function fetchCatalogue(): Promise<ReportCatalogueOut> {
  const result = await api.GET("/api/v1/reports/catalogue");
  return unwrapQuery<ReportCatalogueOut>(result, "report request failed");
}

// The head, filter bar and table of one report for the address. A 403 (the user may not open it) and a 404 (no such
// report) are thrown as ApiFailure with their `status`. A redirect answer (`redirect` set) is returned as data; the
// caller decides whether to follow it, this module never does.
export async function fetchReportPage(key: string, query: string): Promise<ReportPageOut> {
  const result = await api.GET("/api/v1/reports/{key}", {
    params: { path: { key } },
    querySerializer: () => addressSearch(query, 0),
  });
  return unwrapQuery<ReportPageOut>(result, "report request failed");
}

// One batch of rows of the address, from `offset`. A grouped table answers every row at once with next_offset null.
export async function fetchReportRows(key: string, query: string, offset: number): Promise<ReportRowsOut> {
  const result = await api.GET("/api/v1/reports/{key}/rows", {
    params: { path: { key } },
    querySerializer: () => addressSearch(query, offset),
  });
  return unwrapQuery<ReportRowsOut>(result, "report request failed");
}

export function useCatalogue() {
  return useQuery({
    queryKey: reportKeys.catalogue,
    retry: retryMe,
    queryFn: fetchCatalogue,
  });
}

// The page of one report for the address. Its data is stale at once and it is not refetched on focus: a refetch under
// the user's hands would move the rows.
export function useReportPage(key: string, query: string) {
  return useQuery({
    queryKey: reportKeys.page(key, query),
    retry: retryMe,
    staleTime: 0,
    refetchOnWindowFocus: false,
    queryFn: () => fetchReportPage(key, query),
  });
}

// The rows of the address, batch by batch. The first batch is the page's own `table` (seeded, so nothing is requested on
// mount); further batches come from /rows?offset=N. `next_offset` null stops the pill. The key is the address and the
// seed version (the page's dataUpdatedAt), so a changed address or a refetched page is a new query with its own seed.
// The seed is kept only while the report is open (gcTime 0), so a remount reseeds from a fresh page.
export function useReportRows(key: string, query: string, first: ReportTableOut, seed: number) {
  const initial: InfiniteData<ReportRowsOut, number> = {
    pages: [{ groups: first.groups, next_offset: first.next_offset }],
    pageParams: [0],
  };
  return useInfiniteQuery({
    queryKey: reportKeys.rows(key, query, seed),
    initialPageParam: 0,
    initialData: initial,
    // The seed is the page's own answer: it is never stale for this query, so a new seed (a new key) does not fetch
    // its first batch again when the observer starts.
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
    retry: retryMe,
    getNextPageParam: (last: ReportRowsOut) => last.next_offset ?? undefined,
    queryFn: ({ pageParam }) => fetchReportRows(key, query, pageParam),
  });
}

// The «Багана сонгох» pop-up's model for the address.
export async function fetchColumnsModel(key: string, query: string): Promise<ReportColumnsModelOut> {
  const result = await api.GET("/api/v1/reports/{key}/columns", {
    params: { path: { key } },
    querySerializer: () => addressQuery(query),
  });
  return unwrapQuery<ReportColumnsModelOut>(result, "report request failed");
}

// The «Шүүлтүүр» pop-up's model for the address.
export async function fetchRulesModel(key: string, query: string): Promise<ReportRulesModelOut> {
  const result = await api.GET("/api/v1/reports/{key}/rules", {
    params: { path: { key } },
    querySerializer: () => addressQuery(query),
  });
  return unwrapQuery<ReportRulesModelOut>(result, "report request failed");
}

// The «Хэлбэр» pop-up's model for the address.
export async function fetchFormatModel(key: string, query: string): Promise<ReportFormatModelOut> {
  const result = await api.GET("/api/v1/reports/{key}/format", {
    params: { path: { key } },
    querySerializer: () => addressQuery(query),
  });
  return unwrapQuery<ReportFormatModelOut>(result, "report request failed");
}

// The «Хадгалах» pop-up (a report and the address) or the «Засах» pop-up (a view id) as the API draws it.
export async function fetchViewForm(target: ViewFormTarget): Promise<ReportViewFormOut> {
  const result =
    "pk" in target
      ? await api.GET("/api/v1/reports/views/{pk}", { params: { path: { pk: target.pk } } })
      : await api.GET("/api/v1/reports/{key}/views/new", {
          params: { path: { key: target.key } },
          querySerializer: () => addressQuery(target.query),
        });
  return unwrapQuery<ReportViewFormOut>(result, "report request failed");
}

// The pop-up models are read fresh on every open: stale at once and never kept after the pop-up closes (gcTime 0).
// `enabled` is the pop-up being open, so a closed pop-up sends nothing.
export function useColumnsModel(key: string, query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reports", key, "columns", query],
    enabled,
    retry: retryMe,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: () => fetchColumnsModel(key, query),
  });
}

export function useRulesModel(key: string, query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reports", key, "rules", query],
    enabled,
    retry: retryMe,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: () => fetchRulesModel(key, query),
  });
}

export function useFormatModel(key: string, query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reports", key, "format", query],
    enabled,
    retry: retryMe,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: () => fetchFormatModel(key, query),
  });
}

// The saved-view form (name, visibility, default, query), read fresh on every open.
export function useViewForm(target: ViewFormTarget, enabled: boolean) {
  const targetKey = "pk" in target ? ["pk", target.pk] : ["key", target.key, target.query];
  return useQuery({
    queryKey: ["reports", "view-form", ...targetKey],
    enabled,
    retry: retryMe,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: () => fetchViewForm(target),
  });
}

// After a saved-view write that saved (ok true), the report's pages are stale: a view changes the address and the
// list of views. A refused write (ok false) changed nothing, so nothing is refreshed.
async function refreshAfterViewWrite(queryClient: QueryClient, key: string | null, result: ReportViewResultOut) {
  if (!result.ok) return;
  await queryClient.invalidateQueries({ queryKey: key === null ? ["reports"] : ["reports", key] });
}

// Stores the address under a new view name for report `key`. A refusal answers ok false with the messages.
export function useSaveView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, body }: { key: string; body: ReportViewIn }) =>
      postWithCsrfRetry<ReportViewResultOut>(queryClient, () =>
        api.POST("/api/v1/reports/{key}/views", { params: { path: { key } }, body }),
      ),
    onSuccess: (result, variables) => refreshAfterViewWrite(queryClient, variables.key, result),
  });
}

// Renames view `pk` and changes who sees it and whether it opens first. The key of the report is not known here, so
// every report query is refreshed on a saved write.
export function useUpdateView(pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportViewIn) =>
      postWithCsrfRetry<ReportViewResultOut>(queryClient, () =>
        api.POST("/api/v1/reports/views/{pk}", { params: { path: { pk } }, body }),
      ),
    onSuccess: (result) => refreshAfterViewWrite(queryClient, null, result),
  });
}
