// Port of app/static/js/report_memory.js: the pure helpers. A report remembers how the user left it (filters, sort,
// columns, layout): opening it again by its plain address returns to that state. Per user and per browser, per report,
// in localStorage. The day, the calendar month and the search are not remembered (UI_RULES §4b).
// The DOM wiring lives in useReportMemory.ts. Every storage call is guarded: a blocked or full storage just means
// nothing is remembered.

const PREFIX = "hr.reportQuery.";
const REPORT_PATH = /^\/reports\/([^/]+)\/$/;
const NOT_REMEMBERED = ["as_of", "lmonth", "lweek", "q"];

// The localStorage key of one report for one user; null when there is no user or the address is not a report.
export function storageKey(userId: string, pathname: string): string | null {
  const m = REPORT_PATH.exec(pathname);
  if (!m || typeof userId !== "string" || userId === "") return null;
  return PREFIX + "u" + userId + "." + m[1];
}

// True for a parameter that is not remembered, also when its name is percent-encoded (the server decodes it). A name
// that cannot be decoded is treated as not remembered.
function isDated(name: string): boolean {
  try {
    return NOT_REMEMBERED.indexOf(decodeURIComponent(name)) !== -1;
  } catch {
    return true;
  }
}

// The query to remember: the dated parameters dropped, the rest kept as they were written (not re-encoded).
export function rememberable(search: string): string {
  if (!search) return "";
  const kept = search
    .replace(/^\?/, "")
    .split("&")
    .filter((part) => part !== "" && !isDated(part.split("=")[0]));
  return kept.length ? "?" + kept.join("&") : "";
}

// The address to send a plain visit to, or null. Only a fresh navigation to a bare address goes back to the saved
// setup; a reload or back/forward keeps the address the browser already has.
export function restoreTarget(
  navType: string | undefined,
  pathname: string,
  search: string,
  saved: string | null,
): string | null {
  if (navType !== "navigate" || search !== "") return null;
  // A bare "?" is not a setup: it would send the page back to the same address forever.
  if (typeof saved !== "string" || saved.length < 2 || saved.charAt(0) !== "?") return null;
  return pathname + saved;
}

// True for a link (or anything inside one) marked data-reset-all, the «Эхнээс» button.
export function isResetLink(element: Pick<Element, "closest"> | null | undefined): boolean {
  return !!(element && element.closest && element.closest("[data-reset-all]"));
}

// ---- Storage (every call guarded) ----

export function loadSaved(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// An empty query removes the key.
export function saveQuery(key: string, query: string): void {
  try {
    if (query) localStorage.setItem(key, query);
    else localStorage.removeItem(key);
  } catch {
    /* blocked or full: nothing is remembered */
  }
}

// Keys written before the user id was part of the key can never be read again: remove them.
export function dropOldKeys(): void {
  try {
    const stale: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const name = localStorage.key(i);
      if (name && name.indexOf(PREFIX) === 0 && name.indexOf(PREFIX + "u") !== 0) stale.push(name);
    }
    stale.forEach((name) => localStorage.removeItem(name));
  } catch {
    /* blocked */
  }
}
