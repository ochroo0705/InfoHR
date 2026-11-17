import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export type ErrorBody = {
  field_errors: Record<string, string[]>;
  form_errors: string[];
  code?: string;
};

let csrfToken = "";

export function setCsrf(token: string): void {
  csrfToken = token;
}

export function getCsrf(): string {
  return csrfToken;
}

// Navigation sits behind one object so tests can spy on it (jsdom cannot
// stub location.assign directly).
export const nav = {
  assign: (url: string) => location.assign(url),
};

let loginRedirectDone = false;

export function redirectToLogin(): void {
  if (loginRedirectDone) return;
  // Already on the login page: a 401 there is the expected answer, not a reason to reload.
  if (location.pathname === "/login") return;
  loginRedirectDone = true;
  nav.assign("/login?next=" + encodeURIComponent(location.pathname + location.search));
}

const UNSAFE_METHODS = ["POST", "PUT", "PATCH", "DELETE"];

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getCsrf();
    if (UNSAFE_METHODS.includes(request.method) && token) {
      request.headers.set("X-CSRFToken", token);
    }
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401) {
      redirectToLogin();
    } else if (response.status === 403) {
      const body = (await response
        .clone()
        .json()
        .catch(() => null)) as Partial<ErrorBody> | null;
      // Already on the change page: its own 403s must not reload it (that would loop).
      if (body?.code === "password_change_required" && location.pathname !== "/password/change") {
        nav.assign("/password/change");
      }
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);
