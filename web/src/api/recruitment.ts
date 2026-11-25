import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { present } from "./leave";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type RecruitVacancyListOut = components["schemas"]["RecruitVacancyListOut"];
export type RecruitVacancyRowOut = components["schemas"]["RecruitVacancyRowOut"];
export type RecruitVacancyOut = components["schemas"]["RecruitVacancyOut"];
export type RecruitCandidateRowOut = components["schemas"]["RecruitCandidateRowOut"];
export type RecruitCandidateOut = components["schemas"]["RecruitCandidateOut"];
export type RecruitStageItemOut = components["schemas"]["RecruitStageItemOut"];
export type RecruitSlotLineOut = components["schemas"]["RecruitSlotLineOut"];
export type RecruitVacancyOptionsOut = components["schemas"]["RecruitVacancyOptionsOut"];
export type RecruitVacancyFormOut = components["schemas"]["RecruitVacancyFormOut"];
export type RecruitPurgeOut = components["schemas"]["RecruitPurgeOut"];
export type RecruitPurgeRowOut = components["schemas"]["RecruitPurgeRowOut"];
export type RecruitPurgeResultOut = components["schemas"]["RecruitPurgeResultOut"];
export type RecruitVacancyIn = components["schemas"]["RecruitVacancyIn"];
export type RecruitVacancyUpdateIn = components["schemas"]["RecruitVacancyUpdateIn"];
export type RecruitVacancyCreatedOut = components["schemas"]["RecruitVacancyCreatedOut"];
export type RecruitCandidateIn = components["schemas"]["RecruitCandidateIn"];
export type RecruitMoveIn = components["schemas"]["RecruitMoveIn"];
export type RecruitRejectIn = components["schemas"]["RecruitRejectIn"];
export type RecruitCommentIn = components["schemas"]["RecruitCommentIn"];
export type RecruitConvertOut = components["schemas"]["RecruitConvertOut"];
export type RecruitWriteResultOut = components["schemas"]["RecruitWriteResultOut"];

// The filters of the vacancy list, as the URL carries them (all text). An empty or missing value is left out of the query.
export type RecruitVacancyListParams = {
  status?: string;
  q?: string;
};

// The budget line's inputs (all text). Only `position` decides whether the line is asked for at all.
export type RecruitSlotLineParams = {
  position?: string;
  branch?: string;
  desired_start?: string;
  headcount?: string;
  vacancy?: string;
};

function candidateKey(id: number) {
  return ["recruitment", "candidate", id];
}

// The whole recruitment prefix is one unit: the counts, the stage bars and the lists all depend on each other.
const RECRUITMENT_KEY = ["recruitment"];

// After a write that saved (ok true): the recruitment prefix; a vacancy or candidate write also the attention box and
// the nav badge. A refusal (ok false) changed nothing, so nothing is refreshed.
async function refreshAfterWrite(
  queryClient: QueryClient,
  result: { ok: boolean },
  listsAttention: boolean,
): Promise<void> {
  if (!result.ok) return;
  await queryClient.invalidateQueries({ queryKey: RECRUITMENT_KEY });
  if (listsAttention) {
    await queryClient.invalidateQueries({ queryKey: ["attention"] });
    await queryClient.invalidateQueries({ queryKey: ["nav"] });
  }
}

// The vacancy list, batch by batch. A changed filter is a new key: it starts again at offset 0 and keeps no old rows.
// `next_offset` is null when no row follows.
export function useVacancies(params: RecruitVacancyListParams) {
  return useInfiniteQuery({
    queryKey: ["recruitment", "vacancies", params],
    initialPageParam: 0,
    getNextPageParam: (last: RecruitVacancyListOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      // The schema types offset as a string, like the other query values.
      const query = { ...present({ ...params }), offset: String(pageParam) };
      const result = await api.GET("/api/v1/recruitment/vacancies", { params: { query } });
      return unwrapQuery<RecruitVacancyListOut>(result, "recruitment request failed");
    },
  });
}

// The choices of the vacancy form. `vacancy` is sent only for an existing vacancy (the edit form). Kept only while open
// (gcTime 0) and fetched again on every open.
export function useVacancyOptions(vacancyId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["recruitment", "options", vacancyId],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const query = vacancyId === null ? {} : { vacancy: String(vacancyId) };
      const result = await api.GET("/api/v1/recruitment/vacancies/options", { params: { query } });
      return unwrapQuery<RecruitVacancyOptionsOut>(result, "recruitment request failed");
    },
  });
}

// The saved values of vacancy `id` for the edit pop-up (ids, dates, status). Enabled only for a vacancy id. Kept only
// while open (gcTime 0) and read fresh on every open. A vacancy the user may not see answers 404, a non-manager 403.
export function useVacancyForm(id: number | null) {
  return useQuery({
    queryKey: ["recruitment", "vacancy-form", id],
    enabled: id !== null,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/recruitment/vacancies/{pk}/form", {
        params: { path: { pk: id as number } },
      });
      return unwrapQuery<RecruitVacancyFormOut>(result, "recruitment request failed");
    },
  });
}

// The budget line for the position the form has chosen. Idle while no position is given; the caller debounces the
// inputs. Kept only while open (gcTime 0). `null` from the server means there is no line to show.
export function useSlotLine(params: RecruitSlotLineParams) {
  return useQuery({
    queryKey: ["recruitment", "slot-line", params],
    enabled: Boolean(params.position),
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/recruitment/vacancies/slot-line", { params: { query: present({ ...params }) } });
      return unwrapQuery<RecruitSlotLineOut | null>(result, "recruitment request failed");
    },
  });
}

// The vacancy page: its stage bar, and its candidates of `stage` batch by batch (`next_offset` is null when no batch follows).
export function useVacancy(id: number, stage: string) {
  return useInfiniteQuery({
    queryKey: ["recruitment", "vacancy", id, stage],
    initialPageParam: 0,
    getNextPageParam: (last: RecruitVacancyOut) => last.next_offset ?? undefined,
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async ({ pageParam }) => {
      const query = { ...present({ stage }), offset: String(pageParam) };
      const result = await api.GET("/api/v1/recruitment/vacancies/{pk}", {
        params: { path: { pk: id }, query },
      });
      return unwrapQuery<RecruitVacancyOut>(result, "recruitment request failed");
    },
  });
}

// The candidate page. Personal data: kept only while open (gcTime 0) and read fresh on every open. A candidate the user
// may not see answers 404; the query then errors with that status and the screen shows the not-found state.
export function useCandidate(id: number) {
  return useQuery({
    queryKey: candidateKey(id),
    retry: retryMe,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/recruitment/candidates/{pk}", { params: { path: { pk: id } } });
      return unwrapQuery<RecruitCandidateOut>(result, "recruitment request failed");
    },
  });
}

// The purge page: the rejected candidates that are old enough to delete, and whether the user may run the purge.
export function usePurgePage() {
  return useQuery({
    queryKey: ["recruitment", "purge"],
    retry: retryMe,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/recruitment/purge");
      return unwrapQuery<RecruitPurgeOut>(result, "recruitment request failed");
    },
  });
}

// The plain download link of a candidate's CV file. The server answers no-store; the browser follows the link itself.
export function candidateFileUrl(id: number): string {
  return `/api/v1/recruitment/files/${id}`;
}

// Creates a vacancy (id null) or saves the edit of vacancy `id`. A refusal answers ok false with the messages.
export function useSaveVacancy(id: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecruitVacancyIn | RecruitVacancyUpdateIn) =>
      postWithCsrfRetry<RecruitVacancyCreatedOut | RecruitWriteResultOut>(queryClient, () =>
        id === null
          ? api.POST("/api/v1/recruitment/vacancies", { body: body as RecruitVacancyIn })
          : api.POST("/api/v1/recruitment/vacancies/{pk}", {
              params: { path: { pk: id } },
              body: body as RecruitVacancyUpdateIn,
            }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Adds a candidate to vacancy `vacancyId`. A closed or filled vacancy is refused (ok false), nothing is written.
export function useAddCandidate(vacancyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecruitCandidateIn) =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/vacancies/{pk}/candidates", {
          params: { path: { pk: vacancyId } },
          body,
        }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Moves candidate `id` to another stage. The target and the note are the page's own choices.
export function useMoveCandidate(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecruitMoveIn) =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/move", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Rejects candidate `id`, with the reason (and whether it was withdrawn).
export function useRejectCandidate(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecruitRejectIn) =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/reject", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Reopens rejected candidate `id`.
export function useReopenCandidate(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/reopen", { params: { path: { pk: id } } }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Adds a comment to candidate `id`.
export function useCommentCandidate(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecruitCommentIn) =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/comment", { params: { path: { pk: id } }, body }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Attaches a CV to candidate `id`. The file goes as the `file` part of a multipart body (no Content-Type set here: the
// browser adds the boundary). With no file the form has no file part and the server refuses it with its message.
export function useUploadCandidateFile(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File | null) =>
      postWithCsrfRetry<RecruitWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/files", {
          params: { path: { pk: id } },
          body: {},
          bodySerializer: () => {
            const form = new FormData();
            if (file) {
              form.append("file", file);
            }
            return form;
          },
        }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Converts candidate `id` to an employee: ok true gives the path of the hire form; a refusal gives its text in `error`.
export function useConvertCandidate(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<RecruitConvertOut>(queryClient, () =>
        api.POST("/api/v1/recruitment/candidates/{pk}/convert", { params: { path: { pk: id } } }),
      ),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, true),
  });
}

// Deletes the old rejected candidates the purge page lists. The answer carries how many rows went.
export function usePurge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postWithCsrfRetry<RecruitPurgeResultOut>(queryClient, () => api.POST("/api/v1/recruitment/purge")),
    onSuccess: (result) => refreshAfterWrite(queryClient, result, false),
  });
}
