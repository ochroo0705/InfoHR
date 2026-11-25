import { useEffect, useRef } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router";
import { useMeta } from "../../shell/useMeta";
import {
  dropOldKeys,
  isResetLink,
  loadSaved,
  restoreTarget,
  rememberable,
  saveQuery,
  storageKey,
} from "./reportMemory";

// Port of the DOM wiring of app/static/js/report_memory.js, as a hook for ReportPage. The address of a report is
// remembered per user and per report. A plain address reached by a fresh navigation (a PUSH, or the first load of the
// document) goes back to the saved setup, once. Back/forward and reload keep their own address. The «Эхнээс» link
// (data-reset-all) forgets the saved setup before it navigates.

// Set on window once an answered arrival has been evaluated in this document (as the script's window.__hrReportMemory
// guard). Only the first arrival can be the page's first load: a later back/forward to the initial entry must not
// restore. A window property, not module state, so each document starts without it.
const ARRIVAL_FLAG = "__hrReportMemoryArrival";

function arrivalSeen(): boolean {
  return (window as unknown as Record<string, unknown>)[ARRIVAL_FLAG] === true;
}

function markArrivalSeen(): void {
  (window as unknown as Record<string, unknown>)[ARRIVAL_FLAG] = true;
}

// True when the document itself was loaded by a navigation (not a reload, not back/forward).
function loadedByNavigation(): boolean {
  try {
    const entry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    return entry?.type === "navigate";
  } catch {
    return false;
  }
}

// A fresh navigation: a PUSH, or the document's first arrival (the initial entry, loaded by navigation).
function isFreshArrival(action: string, locationKey: string): boolean {
  if (action === "PUSH") return true;
  return action === "POP" && !arrivalSeen() && locationKey === "default" && loadedByNavigation();
}

// `answered` is true once the page's answer has arrived with no redirect. `redirected` is true when the answer is a
// redirect. The server's default-view redirect has the priority: memory waits for the answer, so a bare address that
// is redirected is never also restored.
// Returns `restorePending`: true while a restore is due for this arrival and has not been performed yet. The page
// holds back the bare address's own answer while it is true, so the unfiltered rows are never drawn.
export function useReportMemory(reportKey: string | undefined, answered = true, redirected = false): boolean {
  const { data: meta } = useMeta();
  const userId = String(meta?.user?.id ?? "");
  const location = useLocation();
  const navigate = useNavigate();
  const action = useNavigationType();
  const { pathname, search, key: locationKey } = location;
  const storage = reportKey ? storageKey(userId, pathname) : null;
  const handledKey = useRef<string | null>(null);

  const restorePending =
    storage !== null &&
    !redirected &&
    search === "" &&
    handledKey.current !== locationKey &&
    isFreshArrival(action, locationKey) &&
    restoreTarget("navigate", pathname, search, loadSaved(storage)) !== null;

  // Keys written before the user id was part of the key: removed once a user is known (as the script does).
  useEffect(() => {
    if (userId !== "") dropOldKeys();
  }, [userId]);

  // Remember the address on each change. A bare address writes nothing (the restore below reads the saved setup).
  // A non-empty address with nothing to remember removes the key.
  useEffect(() => {
    if (!storage || search === "") return;
    saveQuery(storage, rememberable(search));
  }, [storage, search]);

  // «Эхнээс» forgets the setup in the capture phase, before the link's own navigation runs.
  useEffect(() => {
    if (!storage) return;
    const onClick = (event: Event) => {
      if (isResetLink(event.target as Element | null)) saveQuery(storage, "");
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [storage]);

  // A fresh navigation to a bare address goes back to the saved setup, once per arrival.
  useEffect(() => {
    if (!storage || !answered) return;
    if (handledKey.current === locationKey) return;
    handledKey.current = locationKey;
    const fresh = isFreshArrival(action, locationKey);
    markArrivalSeen();
    if (!fresh) return;
    const target = restoreTarget("navigate", pathname, search, loadSaved(storage));
    if (target !== null) navigate(target, { replace: true });
  }, [storage, answered, locationKey, action, pathname, search, navigate]);

  return restorePending;
}
