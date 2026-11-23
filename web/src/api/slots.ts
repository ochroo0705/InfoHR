import { useInfiniteQuery, useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type SlotListOut = components["schemas"]["SlotListOut"];
export type SlotRowOut = components["schemas"]["SlotRowOut"];
export type SlotTotalsOut = components["schemas"]["SlotTotalsOut"];
export type SlotOptionsOut = components["schemas"]["SlotOptionsOut"];
export type SlotWriteIn = components["schemas"]["SlotWriteIn"];
export type SlotWriteResultOut = components["schemas"]["SlotWriteResultOut"];

// The key of one year's rows. Every slot write invalidates ["slots"], so the list and the options refetch together.
export function slotListKey(year: number | null): unknown[] {
  return ["slots", year];
}

// The year's rows, batch by batch (config batching.LIST_BATCH rows per batch). `next_offset` is null when no row
// follows. A new year is a new key, so it starts again at offset 0.
export function useSlotList(year: number | null) {
  return useInfiniteQuery({
    queryKey: slotListKey(year),
    initialPageParam: 0,
    getNextPageParam: (last: SlotListOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      // The schema types year and offset as strings, like the other query values. No year means the current year.
      const query = year === null ? { offset: String(pageParam) } : { year: String(year), offset: String(pageParam) };
      const result = await api.GET("/api/v1/slots", { params: { query } });
      return unwrapQuery<SlotListOut>(result, "slot request failed");
    },
  });
}

// The choices of the add and edit pop-up for one year, and the year a new row starts with.
export function useSlotOptions(year: number) {
  return useQuery({
    queryKey: ["slots", "options", year],
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/slots/options", { params: { query: { year: String(year) } } });
      return unwrapQuery<SlotOptionsOut>(result, "slot request failed");
    },
  });
}

// Adds a row (id null) or changes row `id`. A refusal answers 200 with ok false and writes nothing, so nothing is
// invalidated then.
export async function saveSlot(queryClient: QueryClient, id: number | null, body: SlotWriteIn): Promise<SlotWriteResultOut> {
  const result = await postWithCsrfRetry<SlotWriteResultOut>(queryClient, () =>
    id === null
      ? api.POST("/api/v1/slots", { body })
      : api.POST("/api/v1/slots/{pk}", { params: { path: { pk: id } }, body }),
  );
  if (result.ok) await queryClient.invalidateQueries({ queryKey: ["slots"] });
  return result;
}

// Deletes row `id`. A refused delete (the database login lacks the grant) answers ok false; nothing is invalidated then.
export async function deleteSlot(queryClient: QueryClient, id: number): Promise<SlotWriteResultOut> {
  const result = await postWithCsrfRetry<SlotWriteResultOut>(queryClient, () =>
    api.POST("/api/v1/slots/{pk}/delete", { params: { path: { pk: id } } }),
  );
  if (result.ok) await queryClient.invalidateQueries({ queryKey: ["slots"] });
  return result;
}
