import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components, operations } from "./schema";

export type TodayOut = components["schemas"]["TodayOut"];
export type AttentionBoxOut = components["schemas"]["AttentionBoxOut"];
export type AttentionMoreOut = components["schemas"]["AttentionMoreOut"];
export type GroupOut = components["schemas"]["GroupOut"];
export type ItemOut = components["schemas"]["ItemOut"];
export type ToggleIn = components["schemas"]["ToggleIn"];
export type ToggleOut = components["schemas"]["ToggleOut"];
export type AwayOut = components["schemas"]["AwayOut"];
export type UpcomingListOut = components["schemas"]["UpcomingListOut"];
export type HireOut = components["schemas"]["HireOut"];
export type TodayViewOut = components["schemas"]["TodayViewOut"];
export type UpcomingKind = "birthday" | "anniversary";
export type AttentionMoreParams = NonNullable<
  operations["api_attention_attention_more"]["parameters"]["query"]
>;

// The same retry rule as useMe (a 401, 403 or 404 fails at once).
export function useToday() {
  return useQuery({
    queryKey: ["today"],
    retry: retryMe,
    queryFn: async () => {
      const result = await api.GET("/api/v1/today");
      return unwrapQuery<TodayOut>(result, "today request failed");
    },
  });
}

// The people away on one day of the Today strip. Nothing is asked for until a day is picked.
export function useAway(day: string | null) {
  return useQuery({
    queryKey: ["today", "away", day],
    enabled: !!day,
    queryFn: async () => {
      const result = await api.GET("/api/v1/today/away", { params: { query: { day: day ?? "" } } });
      return unwrapQuery<AwayOut>(result, "today request failed");
    },
  });
}

// Birthdays or work anniversaries in the next 30 days. Lazy: only fetched once `enabled` is turned on by a click.
export function useUpcoming(kind: UpcomingKind, enabled: boolean) {
  return useQuery({
    queryKey: ["today", "upcoming", kind],
    enabled,
    queryFn: async () => {
      const result = await api.GET("/api/v1/today/upcoming", { params: { query: { kind } } });
      return unwrapQuery<UpcomingListOut>(result, "today request failed");
    },
  });
}

// The names of people who joined in the last 30 days. Lazy, as useUpcoming.
export function useHires(enabled: boolean) {
  return useQuery({
    queryKey: ["today", "hires"],
    enabled,
    queryFn: async () => {
      const result = await api.GET("/api/v1/today/hires");
      return unwrapQuery<HireOut[]>(result, "today request failed");
    },
  });
}

// The report setups that say what is coming up. Lazy, as useUpcoming.
export function useViews(enabled: boolean) {
  return useQuery({
    queryKey: ["today", "views"],
    enabled,
    queryFn: async () => {
      const result = await api.GET("/api/v1/today/views");
      return unwrapQuery<TodayViewOut[]>(result, "today request failed");
    },
  });
}

// One Анхаарах group past its first items, or a page of a gap group. Nothing is fetched while params is null.
export function useAttentionMore(params: AttentionMoreParams | null) {
  return useQuery({
    queryKey: ["attention", "more", params],
    enabled: params !== null,
    queryFn: async () => {
      const result = await api.GET("/api/v1/attention/more", { params: { query: params ?? {} } });
      return unwrapQuery<AttentionMoreOut>(result, "attention request failed");
    },
  });
}

// «Мэдлээ» / «Дахин харуулах». On success the new box goes straight into the ["today"] cache (so the tile and the
// box re-render together), then the attention and today queries are invalidated.
export function useAttentionToggle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ToggleIn) =>
      postWithCsrfRetry<ToggleOut>(queryClient, () =>
        api.POST("/api/v1/attention/toggle", { body }),
      ),
    onSuccess: async ({ box }) => {
      const today = queryClient.getQueryData<TodayOut>(["today"]);
      if (today) {
        queryClient.setQueryData<TodayOut>(["today"], { ...today, box });
      }
      await queryClient.invalidateQueries({ queryKey: ["attention"] });
      // exact: open lazy lists under ["today", ...] (away, upcoming, hires, views) are not refetched by a toggle.
      await queryClient.invalidateQueries({ queryKey: ["today"], exact: true });
    },
  });
}
