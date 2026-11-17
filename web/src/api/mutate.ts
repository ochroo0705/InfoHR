import type { QueryClient } from "@tanstack/react-query";
import type { ErrorBody } from "./client";
import { metaQueryOptions } from "./meta";

// What openapi-fetch resolves with: the parsed data on success, the parsed error body otherwise.
export type Settled<T> = { data?: T; error?: unknown; response: Response };

// A failed request. `status` is the HTTP status; `formErrors` is the body's form_errors ([] when the body is not the JSON error shape).
export type ApiFailure = Error & {
  status: number;
  formErrors: string[];
  fieldErrors: Record<string, string[]>;
  code?: string;
};

export function apiFailure(response: Response, error: unknown, message: string): ApiFailure {
  const body = (error !== null && typeof error === "object" ? error : {}) as Partial<ErrorBody>;
  return Object.assign(new Error(message), {
    status: response.status,
    formErrors: Array.isArray(body.form_errors) ? body.form_errors : [],
    fieldErrors: body.field_errors ?? {},
    code: body.code,
  });
}

// A GET answer's data, or a thrown ApiFailure.
export function unwrapQuery<T>(result: Settled<T>, message: string): T {
  if (!result.response.ok || result.data === undefined) {
    throw apiFailure(result.response, result.error, message);
  }
  return result.data;
}

// Django's own CSRF failure page is HTML, not the JSON error shape.
function isJsonAnswer(response: Response): boolean {
  return (response.headers.get("content-type") ?? "").includes("application/json");
}

// The API's CSRF failure: a JSON 403 with code "csrf_failed" (api/main.py http_error_handler).
function isApiCsrfFailure(response: Response, error: unknown): boolean {
  const body = (error !== null && typeof error === "object" ? error : {}) as Partial<ErrorBody>;
  return response.status === 403 && body.code === "csrf_failed";
}

// Sends an unsafe request. A CSRF 403 (the API's JSON code "csrf_failed", or Django's HTML page) means the CSRF token
// went stale: refetch ["meta"] (which stores a fresh token), then retry the request once. A second failure, or any
// other error, rejects.
export async function postWithCsrfRetry<T>(
  queryClient: QueryClient,
  send: () => Promise<Settled<T>>,
): Promise<T> {
  let result = await send();
  const csrfFailure =
    isApiCsrfFailure(result.response, result.error) ||
    (result.response.status === 403 && !isJsonAnswer(result.response));
  if (csrfFailure) {
    try {
      await queryClient.fetchQuery({ ...metaQueryOptions, staleTime: 0 });
    } catch (error) {
      // Every rejection has the same shape: a failed meta refetch carries its status and no form errors.
      const status = (error as { status?: number }).status ?? 0;
      throw Object.assign(new Error("meta request failed"), { status, formErrors: [], fieldErrors: {} });
    }
    result = await send();
  }
  if (!result.response.ok) {
    throw apiFailure(result.response, result.error, "request failed");
  }
  return result.data as T;
}
