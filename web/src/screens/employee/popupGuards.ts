import type { QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { invalidateEmployee, type EmployeePart } from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The scaffold every form pop-up shares (CorrectionModal's rules, reused by the event pop-up and the order pop-up):
// - a late answer is ignored once the pop-up is closed or unmounted (`isCurrent`, `isMounted`);
// - after a refused save the cursor goes to the first box with an error (`bumpErrorTick` starts the focus).

// A load that failed for an unknown reason.
export const LOAD_FAILED_TEXT = "Мэдээлэл ачаалж чадсангүй.";
// The page changed under the pop-up (a 404: the event or order was applied or cancelled elsewhere). The same text is a
// 400 "save without the snapshot" in app/api/employee_writes.py (`_STALE_FORM`); here it means the page changed under
// the pop-up, and the caller refreshes the page data.
export const STALE_TEXT = "Хуудсыг дахин ачаалж, дахин оролдоно уу.";

// The messages of a failed load: the stale text for a 404, the server's form errors for a 403, else the load message.
export function loadMessagesOf(failure: Partial<ApiFailure> | null): string[] {
  if (failure?.status === 404) return [STALE_TEXT];
  if (failure?.status === 403 && (failure.formErrors?.length ?? 0) > 0) return failure.formErrors ?? [];
  return [LOAD_FAILED_TEXT];
}

export type PopupGuards = {
  // The <form> whose first box with an error gets the focus.
  formRef: { current: HTMLFormElement | null };
  // True while mounted and still open. A late answer checks this before it shows errors, moves the focus or closes.
  isCurrent: () => boolean;
  // True while mounted. Guards state updates that run after the pop-up may have unmounted (a pending save's finally).
  isMounted: () => boolean;
  // Call after a refused save: the first box with an error gets the focus.
  bumpErrorTick: () => void;
};

export function usePopupGuards(open: boolean): PopupGuards {
  const formRef = useRef<HTMLFormElement>(null);
  const [errorTick, setErrorTick] = useState(0);
  const mounted = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // After a refused save the cursor goes to the first box with an error; with none, to the first box of the form.
  useEffect(() => {
    if (errorTick === 0) return;
    const invalid = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    const box = invalid ?? formRef.current?.querySelector<HTMLElement>("input:not([type=hidden]), textarea");
    box?.focus();
  }, [errorTick]);

  const isCurrent = useCallback(() => mounted.current && openRef.current, []);
  const isMounted = useCallback(() => mounted.current, []);
  const bumpErrorTick = useCallback(() => setErrorTick((tick) => tick + 1), []);
  return { formRef, isCurrent, isMounted, bumpErrorTick };
}

// A refused save, split the way the form pop-ups show it: the field errors whose name is one of `names` go under that
// box (`boxErrors`); the others, and the form messages, go to the red box on top (`formMessages`). When the refusal
// names no box and gives no message, the red box gets the general save message.
export function splitRefusal(
  names: readonly string[],
  fieldErrors: Record<string, string[]>,
  messages: string[],
): { boxErrors: Record<string, string[]>; formMessages: string[] } {
  const known = new Set(names);
  const boxErrors: Record<string, string[]> = {};
  const elsewhere: string[] = [];
  for (const [name, list] of Object.entries(fieldErrors)) {
    if (known.has(name)) boxErrors[name] = list;
    else elsewhere.push(...list);
  }
  const all = [...messages, ...elsewhere];
  const formMessages = all.length > 0 ? all : Object.keys(boxErrors).length > 0 ? [] : [SAVE_FAILED_TEXT];
  return { boxErrors, formMessages };
}

// A 404 on the pop-up's load or save: the page changed under it, so the employee's parts are refreshed (once per change
// of `loadIsStale`).
export function useStaleRefresh(loadIsStale: boolean, pk: number, queryClient: QueryClient, parts: readonly EmployeePart[]) {
  useEffect(() => {
    if (loadIsStale) void invalidateEmployee(queryClient, pk, parts);
    // The parts are a fixed list per pop-up; only the stale flag, the employee and the client start a refresh.
  }, [loadIsStale, pk, queryClient]);
}
