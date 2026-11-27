import { useCallback, useEffect, useRef, useState } from "react";
import {
  createState,
  endMode,
  isOn,
  resetIfNewPage,
  selectAll,
  selectionBody,
  setRow,
  setVisible,
  toggleMode,
} from "./selectionState";
import type { SelState } from "./selectionState";

// The row selection of one report page, as a hook (the DOM wiring of app/static/js/report_select.js).
//
// useReportSelection(resetKey) returns:
//   state            the SelState (ids, all, held); read it to paint the rows and the bar.
//   setVisibleIds    the registration of the rows on screen: the person ids in draw order. CONTRACT: the consumer calls
//                    it on every render of the rows (with the ids it draws that render). pickRow, pickVisible and the
//                    header box read the last registered list; a render that skips the call leaves the previous list
//                    in place. The call stores a ref and causes no re-render.
//   toggle()         «Сонгох»: mode on with nothing picked, or off (and cleared).
//   pickRow(id, on)  ticks or unticks one person.
//   pickVisible(on)  the header box: picks every row on screen, or clears.
//   pickAll()        «Бүх N мөрийг сонгох»: every matching row, no ids sent.
//   cancel()         ends the mode and clears the picks («Болих»).
//   body(query)      the body of a selection action: {query, ids, all}.
//
// resetKey is the report address without the batch. When it differs from the key the selection belongs to, the
// selection is replaced during render, before the render commits, so old picks are never painted under the new key.
// Escape ends the mode unless the key event was already defaultPrevented (a dropdown, a calendar) or a pop-up is open.

const POPUP_SELECTOR = ".fixed.inset-0.z-50:not([data-leaving])";

export type ReportSelection = {
  state: SelState;
  setVisibleIds: (ids: readonly string[]) => void;
  toggle: () => void;
  pickRow: (id: string | number, on: boolean) => void;
  pickVisible: (on: boolean) => void;
  pickAll: () => void;
  cancel: () => void;
  body: (query: string) => { query: string; ids: string[]; all: boolean };
};

// The selection together with the report key it belongs to.
type Held = { key: string; state: SelState };

export function useReportSelection(resetKey: string): ReportSelection {
  const [held, setHeld] = useState<Held>(() => ({ key: resetKey, state: createState() }));
  const visibleRef = useRef<readonly string[]>([]);

  // Reset during render: a render with a new key sees the reset selection at once, so nothing of the old one commits.
  let current = held;
  if (held.key !== resetKey) {
    current = { key: resetKey, state: resetIfNewPage(held.state, resetKey, held.key).state };
    setHeld(current);
  }
  const state = current.state;

  // Applies a pure change to the selection. Returns the previous object when nothing changed, so React skips a render.
  const update = useCallback((change: (s: SelState) => SelState) => {
    setHeld((prev) => {
      const next = change(prev.state);
      return next === prev.state ? prev : { key: prev.key, state: next };
    });
  }, []);

  // Escape ends the mode, unless the key was already used or a pop-up is open. The listener is removed on unmount.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector(POPUP_SELECTOR)) return;
      update((s) => (isOn(s) ? endMode(s) : s));
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [update]);

  const setVisibleIds = useCallback((ids: readonly string[]) => {
    visibleRef.current = ids;
  }, []);

  const toggle = useCallback(() => update(toggleMode), [update]);

  // The rows on screen are read at the moment of the click, so the state change itself is a pure function of them.
  const pickRow = useCallback(
    (id: string | number, on: boolean) => {
      const visible = visibleRef.current;
      update((s) => setRow(s, id, on, visible));
    },
    [update],
  );

  const pickVisible = useCallback(
    (on: boolean) => {
      const visible = visibleRef.current;
      update((s) => setVisible(s, on, visible));
    },
    [update],
  );

  const pickAll = useCallback(() => update(selectAll), [update]);

  const cancel = useCallback(() => update(endMode), [update]);

  const body = useCallback((query: string) => selectionBody(query, state), [state]);

  return { state, setVisibleIds, toggle, pickRow, pickVisible, pickAll, cancel, body };
}
