// The palette's search. Port of search() and the input handler of app/static/js/palette.js: a typed query is debounced
// (DEBOUNCE_MS), each query gets its own AbortController so the latest query wins and a stale answer never repaints, the
// list is dimmed (busy) only when an answer is slower than BUSY_MS, and «show all» asks the same query again with more=1.
// An empty box sends the remembered references (recent) and the page path (from). The hook starts when the panel mounts
// and stops (aborts, clears its timers) when it unmounts: unmounting is the panel closing.
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchPalette, type PaletteOut } from "../../api/palette";
import { recentParam } from "./recents";

// palette.js DEBOUNCE_MS and BUSY_MS.
export const DEBOUNCE_MS = 200;
export const BUSY_MS = 150;

export type PaletteSearchOptions = {
  q: string;
  // The page path the palette was opened on (window.location.pathname), sent with an empty box only.
  from: string;
  storage: Storage | null;
  // The panel's data-user: the recents are kept per user (recents.ts).
  userId: string | number;
};

export type PaletteSearch = {
  answer: PaletteOut | null;
  // True when the answer on screen was asked with «show all» (more=1).
  more: boolean;
  busy: boolean;
  failed: boolean;
  // True from a change of the query (or of «show all») until its answer or error arrives. The answer on screen is then
  // not for the box's text yet.
  pending: boolean;
  // True only while the debounce timer is waiting (the request has not been sent yet).
  debouncing: boolean;
  // Runs the query now instead of after the debounce. Does nothing unless debouncing (palette.js: Enter flushes only a
  // waiting debounce, never a request already in flight).
  flush(): void;
  showAll(): void;
};

// The key of one request: the query, whether it asks for more people, and the «show all» bump. JSON keeps the parts
// apart, so no two different requests share a key (a plain join would let "a1" + 1 collide with "a" + 11).
export function requestKeyOf(q: string, more: boolean, tick: number): string {
  return JSON.stringify([q, more, tick]);
}

export function usePaletteSearch({ q, from, storage, userId }: PaletteSearchOptions): PaletteSearch {
  const [answer, setAnswer] = useState<PaletteOut | null>(null);
  const [answerMore, setAnswerMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // The request key of the last answer or error that arrived (see requestKeyOf).
  const [settledKey, setSettledKey] = useState<string | null>(null);
  // The request key of the last request that was sent (the debounce has ended for it).
  const [sentKey, setSentKey] = useState<string | null>(null);
  // The query «show all» was asked for. It counts only while the box still holds that query: typing again drops it.
  const [moreFor, setMoreFor] = useState<string | null>(null);
  // Bumped by showAll so the search runs again even when «show all» was already on.
  const [tick, setTick] = useState(0);
  const more = moreFor !== null && moreFor === q;
  const requestKey = requestKeyOf(q, more, tick);

  const controllerRef = useRef<AbortController | null>(null);
  const busyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The first search (the panel opens with an empty box) and «show all» run at once; typing is debounced.
  const immediateRef = useRef(true);

  const clearBusyTimer = useCallback(() => {
    if (busyTimerRef.current !== null) clearTimeout(busyTimerRef.current);
    busyTimerRef.current = null;
  }, []);

  // A typed change starts a new query: the «show all» of the old query is over.
  useEffect(() => {
    setMoreFor(null);
  }, [q]);

  useEffect(() => {
    const key = requestKeyOf(q, more, tick);
    const launch = (): void => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      setSentKey(key);
      clearBusyTimer();
      busyTimerRef.current = setTimeout(() => {
        busyTimerRef.current = null;
        if (!controller.signal.aborted) setBusy(true);
      }, BUSY_MS);

      // The empty box sends what was opened last and where the panel was opened; a typed query sends neither.
      const request =
        q.trim() !== ""
          ? { q, more }
          : { q, recent: recentParam(storage, userId), from };

      fetchPalette(request, controller.signal).then(
        (data) => {
          if (controller.signal.aborted) return;
          clearBusyTimer();
          setBusy(false);
          setFailed(false);
          setAnswerMore(more);
          setAnswer(data);
          setSettledKey(key);
        },
        () => {
          if (controller.signal.aborted) return;
          clearBusyTimer();
          setBusy(false);
          setFailed(true);
          setAnswer(null);
          setSettledKey(key);
        },
      );
    };

    // A change of the query (or of «show all») drops the request still in flight, so its answer never repaints. The busy
    // state stays as it is until the new query's own answer (or error) clears it.
    if (immediateRef.current) {
      immediateRef.current = false;
      launch();
      return () => controllerRef.current?.abort();
    }
    const timer = setTimeout(launch, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controllerRef.current?.abort();
    };
  }, [q, more, tick, from, storage, userId, clearBusyTimer]);

  // Close (unmount): drop the request in flight and the busy timer. Nothing repaints afterwards.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
      clearBusyTimer();
    };
  }, [clearBusyTimer]);

  const showAll = useCallback(() => {
    immediateRef.current = true;
    setMoreFor(q);
    setTick((t) => t + 1);
  }, [q]);

  // Enter during the debounce: the bump makes the effect run the query at once (its cleanup drops the timer).
  const pending = settledKey !== requestKey;
  // Debouncing: pending, and the request for this key has not been sent yet. In flight: sent, not answered.
  const debouncing = pending && sentKey !== requestKey;
  const flush = useCallback(() => {
    if (!debouncing) return;
    immediateRef.current = true;
    setTick((t) => t + 1);
  }, [debouncing]);

  return { answer, more: answerMore, busy, failed, pending, debouncing, flush, showAll };
}
