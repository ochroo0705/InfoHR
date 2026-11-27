import { api } from "./client";
import { metaQueryOptions } from "./meta";
import { apiFailure, isApiCsrfFailure, isJsonAnswer, type ApiFailure, type Settled } from "./mutate";
import type { components } from "./schema";

// The editor of a report cell, as the API draws it (the input kind, the value, the stale token, the hidden row values).
export type ReportEditor = components["schemas"]["ReportEditorOut"];
// The answer of a save: ok with the new text, or a refusal with the editor to show.
export type ReportEditResult = components["schemas"]["ReportEditResultOut"];
// Where an editor comes from: the cell's own route, the page's `edit` target. The client picks the URL by `route`.
export type ReportEditTarget = components["schemas"]["ReportEditTarget"];
// One cell of a bulk edit. The bulk route has no request schema in OpenAPI (its body is read raw), so this is written here.
export type BulkCellIn = { person: number; field: string; text: string; old: string };
// The answer of a bulk edit: one outcome per posted cell, in the posted order, and the count saved (0 for a dry run).
export type BulkResult = components["schemas"]["ReportEditBulkOut"];

// The text of a request that never reached the server (the same words as the other report screens use).
const NET_TEXT = "Холбогдож чадсангүй. Дахин оролдоно уу.";
// A save that was refused (the same words as grid_nav.js SAVE_FAIL).
export const SAVE_FAIL = "Хадгалж чадсангүй. Дахин оролдоно уу.";
// An editor that did not open (the same words as grid_nav.js NO_FORM_MSG).
export const NO_FORM_MSG = "Засварлагч нээгдсэнгүй. Хуудсаа шинэчилнэ үү.";
// The text the editor shows when the login has run out (the same words as Django's editor).
export const SESSION_LOST_TEXT = "Нэвтрэх хугацаа дууссан. Хуудсаа шинэчилж дахин нэвтэрнэ үү.";

// The login ran out (401). The editor stays open and shows the message; no login page is opened in a cell.
export class SessionLost extends Error {
  status: number;

  constructor() {
    super(SESSION_LOST_TEXT);
    this.name = "SessionLost";
    this.status = 401;
  }
}

// The request never reached the server (a fetch TypeError). Every other refusal is an ApiFailure, not this class.
export class EditFailed extends Error {
  status: number;

  constructor() {
    super(NET_TEXT);
    this.name = "EditFailed";
    this.status = 0;
  }
}

// Runs one request. Only a fetch TypeError (no network) becomes EditFailed; anything else is rethrown unchanged.
async function send<T>(call: () => Promise<Settled<T>>): Promise<Settled<T>> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof TypeError) throw new EditFailed();
    throw error;
  }
}

// The same CSRF rule as postWithCsrfRetry (api/mutate.ts): the API's JSON "csrf_failed" 403, or Django's HTML 403 page.
function isCsrfRefusal(result: Settled<unknown>): boolean {
  return (
    isApiCsrfFailure(result.response, result.error) ||
    (result.response.status === 403 && !isJsonAnswer(result.response))
  );
}

// Refreshes the CSRF token through the meta query, which stores the new token. A failed refresh is the same kinds of
// failure as a failed request: no network is EditFailed, a 401 is SessionLost, any other refusal is an ApiFailure.
async function refreshToken(): Promise<void> {
  try {
    await metaQueryOptions.queryFn();
  } catch (error) {
    if (error instanceof TypeError) throw new EditFailed();
    const status = (error as { status?: unknown }).status;
    if (status === 401) throw new SessionLost();
    const numeric = typeof status === "number" ? status : 0;
    throw Object.assign(new Error(SAVE_FAIL), { status: numeric, formErrors: [], fieldErrors: {} });
  }
}

// Sends an unsafe request. A stale CSRF token is refreshed and the request sent once more; a second refusal is answered
// like any other.
async function post<T>(call: () => Promise<Settled<T>>): Promise<Settled<T>> {
  let result = await send(call);
  if (isCsrfRefusal(result)) {
    await refreshToken();
    result = await send(call);
  }
  return result;
}

// The data of an answer that is ok. A 401 is SessionLost. Every other refusal is one error type, an ApiFailure with its
// status and form errors; its message is the body's `error` (the bulk route), else the first form error, else `fallback`.
function answered<T>(result: Settled<T>, fallback: string): T {
  const { response, data, error } = result;
  if (response.ok && data !== undefined) return data;
  if (response.status === 401) throw new SessionLost();
  const failure: ApiFailure = apiFailure(response, error, fallback);
  const detail = ((error ?? {}) as { error?: unknown }).error;
  failure.message = typeof detail === "string" && detail ? detail : failure.formErrors[0] || fallback;
  throw failure;
}

// The GET of the editor the target names. The route's own query: a cell (person, field), a row (person, kind, key,
// field), a correction (person, key = the field, record; "" for the base salary, which has no record).
function editorRequest(target: ReportEditTarget): Promise<Settled<ReportEditor>> {
  switch (target.route) {
    case "cell":
      return api.GET("/api/v1/reports/cell/editor", {
        params: { query: { person: target.person, field: target.field } },
      });
    case "row":
      return api.GET("/api/v1/reports/row-cell/editor", {
        params: { query: { person: target.person, kind: target.kind, key: target.key, field: target.field } },
      });
    case "correct":
      return api.GET("/api/v1/reports/correct/editor", {
        params: {
          query: {
            person: target.person,
            key: target.field,
            record: target.salary && target.record === 0 ? "" : String(target.record),
          },
        },
      });
  }
}

// The editor the target opens, read fresh. Never kept by the client: each open is a new answer.
export async function fetchEditor(target: ReportEditTarget): Promise<ReportEditor> {
  return answered(await send(() => editorRequest(target)), NO_FORM_MSG);
}

// The input a save posts: the typed value, the stale token the editor opened with (cell), the hidden values of the row
// (row), the old text and reason (correction).
export type ReportEditInput = {
  value: string;
  loaded: string;
  old: string;
  reason: string;
  hidden: Record<string, string>;
};

// The POST the target's route takes. Each route gets only its own fields; a correction's record is null for the base salary.
function saveRequest(target: ReportEditTarget, input: ReportEditInput): Promise<Settled<ReportEditResult>> {
  switch (target.route) {
    case "cell":
      return api.POST("/api/v1/reports/cell", {
        body: { person: target.person, field: target.field, value: input.value, loaded: input.loaded },
      });
    case "row":
      return api.POST("/api/v1/reports/row-cell", {
        body: {
          person: target.person,
          kind: target.kind,
          key: target.key,
          field: target.field,
          values: { ...input.hidden, [target.field]: input.value },
        },
      });
    case "correct":
      return api.POST("/api/v1/reports/correct", {
        body: {
          person: target.person,
          key: target.field,
          record: target.salary && target.record === 0 ? null : target.record,
          value: input.value,
          old: input.old,
          reason: input.reason,
        },
      });
  }
}

// Saves the editor's input through the target's route. A refusal that the server answers (a clash, a blocked cell) is
// returned as data with ok false and the editor to show; only a 401, another refusal or a network failure throws.
export async function saveEdit(target: ReportEditTarget, input: ReportEditInput): Promise<ReportEditResult> {
  return answered(await post(() => saveRequest(target, input)), SAVE_FAIL);
}

// The body of the bulk route. The route reads the raw body and answers 400 {"error": ...} for a body of the wrong shape
// (where Ninja would answer 422), so the OpenAPI document has no request schema for it.
type BulkBody = { apply: boolean; cells: BulkCellIn[] };

// The bulk edit: a dry run when apply is false, the ok cells saved when true. The body is sent as JSON.
export async function bulkCells(cells: BulkCellIn[], apply: boolean): Promise<BulkResult> {
  const body: BulkBody = { apply, cells };
  // `as never`: the generated client has no requestBody for this route, so the typed body is passed past its check.
  return answered(await post(() => api.POST("/api/v1/reports/cells", { body: body as never })), SAVE_FAIL);
}
