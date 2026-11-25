import { useInfiniteQuery, useQuery, type InfiniteData } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type ReportCatalogueOut = components["schemas"]["ReportCatalogueOut"];
export type ReportPageOut = components["schemas"]["ReportPageOut"];
export type ReportTableOut = components["schemas"]["ReportTableOut"];
export type ReportRowsOut = components["schemas"]["ReportRowsOut"];
export type ReportGroupOut = components["schemas"]["ReportGroupOut"];
export type ReportCellOut = components["schemas"]["ReportCellOut"];
export type ReportHeadCellOut = components["schemas"]["ReportHeadCellOut"];

export const reportKeys = {
  catalogue: ["reports", "catalogue"] as const,
  page: (key: string, query: string) => ["reports", key, query] as const,
  // `seed` is the page's dataUpdatedAt the first batch came from: a new page answer is a new query, seeded afresh.
  rows: (key: string, query: string, seed: number) => ["reports", key, "rows", query, seed] as const,
};

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
