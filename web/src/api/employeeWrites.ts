import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { postWithCsrfRetry, unwrapQuery } from "./mutate";
import type { components, operations } from "./schema";

export type EmployeeFormPageOut = components["schemas"]["EmployeeFormPageOut"];
export type EmployeeFormOut = components["schemas"]["EmployeeFormOut"];
export type EmployeeFormFieldOut = components["schemas"]["EmployeeFormFieldOut"];
export type EmployeeWriteResultOut = components["schemas"]["EmployeeWriteResultOut"];
export type EmployeeWriteLoginOut = components["schemas"]["EmployeeWriteLoginOut"];

// The parts of one employee that a write can change. Each one is an own query key under ["employee", pk].
export type EmployeePart = "work" | "salary" | "personal" | "activity" | "page-form";

// The field errors of one result, by HTML name: the server's messages and the conflict text, when a field changed
// since it was loaded.
export type FieldErrors = Record<string, { errors: string[]; conflict?: string }>;

// The body of the page save: the multipart fields, as the API declares them.
type SaveBody = NonNullable<
  operations["api_employee_writes_employee_save"]["requestBody"]
>["content"]["multipart/form-data"];

// Marks the header ["employee", pk] and each listed part for refetch. The header is always refreshed, because every
// write can change what it shows. Each key is matched exactly, so a write refreshes what it names and nothing else
// under ["employee", pk].
export function invalidateEmployee(queryClient: QueryClient, pk: number, parts: readonly EmployeePart[] = []) {
  const keys: (string | number)[][] = [["employee", pk], ...parts.map((part) => ["employee", pk, part])];
  return Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey, exact: true })));
}

// Maps a result's field_errors and conflicts to one entry per field name. A field can have messages, a conflict, or both.
export function fieldErrorsFor(
  result: Pick<EmployeeWriteResultOut, "field_errors" | "conflicts">,
): FieldErrors {
  const out: FieldErrors = {};
  for (const [name, errors] of Object.entries(result.field_errors)) {
    out[name] = { errors: [...errors] };
  }
  for (const [name, conflict] of Object.entries(result.conflicts)) {
    out[name] = { errors: out[name]?.errors ?? [], conflict };
  }
  return out;
}

// The pop-up form of the page's own fields (header, work, bank and salary), with the stored values and the loaded
// token. Kept only while it is open (gcTime 0), because it carries values the user may change.
export function usePageForm(pk: number, enabled = true) {
  return useQuery({
    queryKey: ["employee", pk, "page-form"],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    // A reconnect refetch would replace the stale-check snapshot without the user seeing it.
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/page-form", { params: { path: { pk } } });
      return unwrapQuery<EmployeeFormPageOut>(result, "employee request failed");
    },
  });
}

// Saves the page. The fields go in `values` (with `loaded`, `si-loaded` and any `resolve-<name>`), as the JSON text
// of `values_json`. A business refusal answers 200 with ok false, which the caller shows; nothing is invalidated then.
export type SavePageVars = {
  values: Record<string, string>;
  photo?: File | null;
  photoClear?: boolean;
  tab?: string;
};

export function useSavePage(pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: SavePageVars) => {
      const body: SaveBody = {
        values_json: JSON.stringify(vars.values),
        photo_clear: vars.photoClear ?? false,
        tab: vars.tab ?? "",
      };
      return postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/save", {
          params: { path: { pk } },
          body,
          // The serializer gets the same typed body and adds the photo file, which the typed body cannot carry.
          bodySerializer: (formBody) => saveFormData(formBody, vars.photo ?? null),
        }),
      );
    },
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEmployee(queryClient, pk, ["work", "salary", "personal", "activity", "page-form"]);
      }
    },
  });
}

// The multipart body of the page save: the typed fields, and the photo file when one is sent.
function saveFormData(body: SaveBody, photo: File | null): FormData {
  const form = new FormData();
  form.append("values_json", body.values_json);
  form.append("photo_clear", body.photo_clear ? "true" : "false");
  form.append("tab", body.tab ?? "");
  if (photo) {
    form.append("photo", photo);
  }
  return form;
}

// Saves one section of the personal tab. `loaded` is the token of the values the user saw; `resolve` says, per field,
// whether to keep the user's value ("mine") or the stored one ("theirs") after a conflict.
export type SaveSectionVars = {
  values: Record<string, string>;
  resolve?: Record<string, string>;
  loaded: string;
};

export function useSaveSection(pk: number, section: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: SaveSectionVars) =>
      postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/personal/sections/{section}", {
          params: { path: { pk, section } },
          body: { values: vars.values, resolve: vars.resolve ?? {}, loaded: vars.loaded },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        // page-form stays in this list on purpose: the identity fields sit on the page form, and a section save
        // changes their `loaded` snapshot, so the page form must reload to save again.
        return invalidateEmployee(queryClient, pk, ["personal", "activity", "page-form"]);
      }
    },
  });
}

// The values that a row's pop-up depends on: an address takes its city, district and street as presets.
export type RowFormOverrides = { city?: string; district?: string; street?: string };

// The pop-up of one personal-list row: the add form (key null) or the edit form of row `key`.
export function useRowForm(
  pk: number,
  kind: string,
  key: number | null,
  overrides: RowFormOverrides = {},
  enabled = true,
) {
  const { city = null, district = null, street = null } = overrides;
  return useQuery({
    queryKey: ["employee", pk, "row-form", kind, key, city, district, street],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    // A reconnect refetch would replace the stale-check snapshot without the user seeing it.
    refetchOnReconnect: false,
    queryFn: async () => {
      const result = await api.GET("/api/v1/employees/{pk}/personal/{kind}/form", {
        params: { path: { pk, kind }, query: { key, city, district, street } },
      });
      return unwrapQuery<EmployeeFormOut>(result, "employee request failed");
    },
  });
}

// The values of a row write. The hidden loaded_* entries of the pop-up (the row's loaded values) go in `values`, as the
// form had them; the server refuses a row whose loaded values are missing.
export type RowVars = { values: Record<string, string> };

// Refetches the personal lists after a refused or failed row write: a row that another user changed or removed is then
// gone from the list, and the open row closes (PersonalList).
function invalidatePersonal(queryClient: QueryClient, pk: number) {
  return queryClient.invalidateQueries({ queryKey: ["employee", pk, "personal"], exact: true });
}

export function useAddRow(pk: number, kind: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: RowVars) =>
      postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/personal/{kind}", {
          params: { path: { pk, kind } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEmployee(queryClient, pk, ["personal", "activity"]);
      }
      return invalidatePersonal(queryClient, pk);
    },
    onError: () => invalidatePersonal(queryClient, pk),
  });
}

export function useEditRow(pk: number, kind: string, key: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: RowVars) =>
      postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/personal/{kind}/{key}", {
          params: { path: { pk, kind, key } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEmployee(queryClient, pk, ["personal", "activity"]);
      }
      return invalidatePersonal(queryClient, pk);
    },
    onError: () => invalidatePersonal(queryClient, pk),
  });
}

export function useDeleteRow(pk: number, kind: string, key: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: RowVars) =>
      postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/personal/{kind}/{key}/delete", {
          params: { path: { pk, kind, key } },
          body: { values },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEmployee(queryClient, pk, ["personal", "activity"]);
      }
      return invalidatePersonal(queryClient, pk);
    },
    onError: () => invalidatePersonal(queryClient, pk),
  });
}

// Adds a note to the activity log. The answer is 204, so there is nothing to read back.
export function useAddNote(pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/note", { params: { path: { pk } }, body: { text } }),
      ),
    onSuccess: () => invalidateEmployee(queryClient, pk, ["activity"]),
  });
}

// Ticks or unticks one setup item of the checklist (Бүрдүүлэлт).
export function useToggleSetup(pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      postWithCsrfRetry<void>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/setup/{key}", { params: { path: { pk, key } } }),
      ),
    onSuccess: () => invalidateEmployee(queryClient, pk, ["work"]),
  });
}

// Creates the employee's login. The answer holds the temporary password once, so the mutation is not kept in the
// cache (gcTime 0) and nothing is invalidated here: the caller shows the password first, then calls
// invalidateEmployee(queryClient, pk) when the pop-up closes.
export function useCreateLogin(pk: number) {
  const queryClient = useQueryClient();
  return useMutation({
    gcTime: 0,
    mutationFn: (username: string) =>
      postWithCsrfRetry<EmployeeWriteLoginOut>(queryClient, () =>
        api.POST("/api/v1/employees/{pk}/login", { params: { path: { pk } }, body: { username } }),
      ),
  });
}

// The paths of the correction pop-ups. "salary/set" is the first salary; the others correct one row by its id.
export type CorrectionPath = "salary/set" | `salary/${number}/correct` | `job/${number}/correct`;

// The row id of a correction path ("job/9/correct" -> 9). Only called for the two row paths.
function recordIdOf(path: CorrectionPath): number {
  return Number(path.split("/")[1]);
}

// The pop-up of one correction. Each path has its own typed route.
export function useCorrectionForm(pk: number, path: CorrectionPath, enabled = true) {
  return useQuery({
    queryKey: ["employee", pk, "correction-form", path],
    enabled,
    retry: retryMe,
    gcTime: 0,
    refetchOnWindowFocus: false,
    // A reconnect refetch would replace the stale-check snapshot without the user seeing it.
    refetchOnReconnect: false,
    queryFn: async () => {
      if (path === "salary/set") {
        const result = await api.GET("/api/v1/employees/{pk}/salary/set/form", { params: { path: { pk } } });
        return unwrapQuery<EmployeeFormOut>(result, "employee request failed");
      }
      if (path.startsWith("job/")) {
        const result = await api.GET("/api/v1/employees/{pk}/job/{record_id}/correct/form", {
          params: { path: { pk, record_id: recordIdOf(path) } },
        });
        return unwrapQuery<EmployeeFormOut>(result, "employee request failed");
      }
      const result = await api.GET("/api/v1/employees/{pk}/salary/{record_id}/correct/form", {
        params: { path: { pk, record_id: recordIdOf(path) } },
      });
      return unwrapQuery<EmployeeFormOut>(result, "employee request failed");
    },
  });
}

// Sends one correction (or the first salary) to the same path the form was loaded from.
export function useSubmitCorrection(pk: number, path: CorrectionPath) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ values }: RowVars) =>
      postWithCsrfRetry<EmployeeWriteResultOut>(queryClient, () => {
        if (path === "salary/set") {
          return api.POST("/api/v1/employees/{pk}/salary/set", { params: { path: { pk } }, body: { values } });
        }
        if (path.startsWith("job/")) {
          return api.POST("/api/v1/employees/{pk}/job/{record_id}/correct", {
            params: { path: { pk, record_id: recordIdOf(path) } },
            body: { values },
          });
        }
        return api.POST("/api/v1/employees/{pk}/salary/{record_id}/correct", {
          params: { path: { pk, record_id: recordIdOf(path) } },
          body: { values },
        });
      }),
    onSuccess: (result) => {
      if (result.ok) {
        return invalidateEmployee(queryClient, pk, ["work", "salary", "activity"]);
      }
    },
  });
}
