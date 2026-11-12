// A report remembers how the user left it (filters, sort, columns, layout): opening it again by its plain address
// (the top bar, a link) returns to that state. Back/forward and reload already keep their own address. Per user and
// per browser, per report, in localStorage; «Эхнээс» (a link with data-reset-all) forgets it before it navigates.
// The logic is pure helpers: under Node the module exports them (report_memory.test.mjs); in the browser there is no
// module object, so nothing is exported and only the DOM wiring runs.
(function () {
  "use strict";

  const PREFIX = "hr.reportQuery.";
  const REPORT_PATH = /^\/reports\/([^/]+)\/$/;
  // The day and the calendar month are dated: a setup that keeps them would open an old page weeks later.
  const DATED_PARAMS = ["as_of", "lmonth", "lweek"];

  // ---- Pure helpers (no DOM) ----

  // The localStorage key of one report for one user; null when there is no user or the address is not a report.
  function storageKey(userId, pathname) {
    const m = REPORT_PATH.exec(pathname);
    if (!m || typeof userId !== "string" || userId === "") return null;
    return PREFIX + "u" + userId + "." + m[1];
  }

  // True for a dated parameter, also when its name is percent-encoded (the server decodes it). A name that cannot be
  // decoded is treated as not remembered.
  function isDated(name) {
    try { return DATED_PARAMS.indexOf(decodeURIComponent(name)) !== -1; } catch (e) { return true; }
  }

  // The query to remember: the dated parameters dropped, the rest kept as they were written (not re-encoded).
  function rememberable(search) {
    if (!search) return "";
    const kept = search.replace(/^\?/, "").split("&").filter((part) => {
      return part !== "" && !isDated(part.split("=")[0]);
    });
    return kept.length ? "?" + kept.join("&") : "";
  }

  // The address to send a plain visit to, or null. Only a fresh navigation to a bare address goes back to the saved
  // setup; a reload or back/forward keeps the address the browser already has.
  function restoreTarget(navType, pathname, search, saved) {
    if (navType !== "navigate" || search !== "") return null;
    // A bare "?" is not a setup: it would send the page back to the same address forever.
    if (typeof saved !== "string" || saved.length < 2 || saved.charAt(0) !== "?") return null;
    return pathname + saved;
  }

  // True for a link (or anything inside one) marked data-reset-all, the «Эхнээс» button.
  function isResetLink(element) {
    return !!(element && element.closest && element.closest("[data-reset-all]"));
  }

  const helpers = { storageKey, rememberable, restoreTarget, isResetLink };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  // ---- Browser part ----

  // The id comes from <body data-user-id>, set only for a logged-in user. Without it nothing is read or written.
  const userId = document.body ? document.body.getAttribute("data-user-id") : null;
  if (!userId) return;

  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, query) {
    try { if (query) { localStorage.setItem(k, query); } else { localStorage.removeItem(k); } } catch (e) { /* blocked */ }
  }

  // Keys written before the user id was part of the key can never be read again: remove them.
  try {
    const stale = [];
    for (let i = 0; i < localStorage.length; i++) {
      const name = localStorage.key(i);
      if (name && name.indexOf(PREFIX) === 0 && name.indexOf(PREFIX + "u") !== 0) stale.push(name);
    }
    stale.forEach((name) => localStorage.removeItem(name));
  } catch (e) { /* blocked */ }

  const k = storageKey(userId, location.pathname);
  if (k && !window.__hrReportMemory) {
    const nav = performance.getEntriesByType("navigation")[0];
    const target = restoreTarget(nav && nav.type, location.pathname, location.search, load(k));
    if (target !== null) { location.replace(target); return; }
    if (location.search) { save(k, rememberable(location.search)); }
  }
  if (window.__hrReportMemory) { return; }
  window.__hrReportMemory = true;

  function remember() {
    const current = storageKey(userId, location.pathname);
    if (current) { save(current, rememberable(location.search)); }
  }
  document.addEventListener("htmx:pushedIntoHistory", remember);
  document.addEventListener("htmx:historyRestore", remember);

  // Capture phase: the forgetting happens before the link's own navigation (which then loads the plain address).
  document.addEventListener("click", (event) => {
    if (!isResetLink(event.target)) return;
    const current = storageKey(userId, location.pathname);
    if (current) {
      try { localStorage.removeItem(current); } catch (e) { /* blocked */ }
    }
  }, true);
})();
