// The reload behaviours of the event pop-up (Task 11b). A committed change of «effective» reloads the form, a kind pick
// switches to the other type's form, and a committed change of another named box refreshes the summary line only.
// Three counters decide what an answer may still do:
// - reloadSeq: the latest date or kind reload; an older reload's answer is ignored;
// - summarySeq: the latest summary refresh asked;
// - saveSeq: the latest save sent.
// A reload answer applies its fields and errors unless a newer save was sent after it; its summary line and its base
// apply only if no newer summary was asked and no newer save was sent (for the base: the save alone). The hook decides
// nothing: it sends the held values and applies what the server answers.
import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type Dispatch, type RefObject, type SetStateAction } from "react";
import { invalidateEmployee } from "../../api/employeeWrites";
import { loadEventForm, type EventFormOut } from "../../api/events";
import type { ApiFailure } from "../../api/mutate";
import { normalise } from "../../widgets/dateLogic";
import type { FormField, FormValues } from "../../widgets/FormFields";
import { mergeFormAfterRefresh, prevEffectiveBase, refreshKindFor, valuesToSend } from "./eventModalLogic";
import { loadMessagesOf } from "./popupGuards";

export const EFFECTIVE = "effective";

// The form as the pop-up shows it after a reload, and the types it is on. `n` counts the sessions (each open, and each
// type the caller sets from outside): an answer from an earlier session is ignored.
export type Live = { n: number; loadType: string; activeType: string; reloaded: EventFormOut | null };

// What a reload answer may still change: keepErrors (a save was sent after it), keepSummary (a summary or a save was).
export type FormApplied = { keepErrors: boolean; keepSummary: boolean };

export type EventReloadsOptions = {
  pk: number;
  queryClient: QueryClient;
  live: Live;
  setLive: Dispatch<SetStateAction<Live>>;
  values: FormValues;
  allFields: FormField[];
  shown: EventFormOut | null;
  formRef: RefObject<HTMLFormElement | null>;
  isCurrent: () => boolean;
  setField: (name: string, value: string) => void;
  onKindChange?: (type: string) => void;
  onFormApplied?: (next: EventFormOut, applied: FormApplied) => void;
  onReloadFailed?: (messages: string[]) => void;
  onSummary?: (answer: { summary: string; when: string }) => void;
};

export function useEventReloads(options: EventReloadsOptions) {
  const { pk, queryClient, live, setLive, setField, isCurrent, formRef } = options;
  const liveRef = useRef(live);
  liveRef.current = live;
  const heldRef = useRef(options.values);
  heldRef.current = options.values;
  const allFieldsRef = useRef(options.allFields);
  allFieldsRef.current = options.allFields;
  const shownRef = useRef(options.shown);
  shownRef.current = options.shown;
  const onKindChangeRef = useRef(options.onKindChange);
  onKindChangeRef.current = options.onKindChange;
  // The last real date: the answer of the last form reload or refusal (null: the loaded form's own, see base()).
  const baseRef = useRef<string | null>(null);
  // The kind the user picked and the server has not answered yet (null: none pending). A date or summary request is sent
  // to this type, so a later change does not send the held kind's answer back to the old type.
  const wantedRef = useRef<string | null>(null);
  // The reloadSeq of the latest reload when that reload is a kind pick (-1: none). A same-type pick cancels only that.
  const kindMark = useRef(-1);
  // The last date sent by a reload, so a second change event for the same date sends nothing.
  const lastDate = useRef<string | null>(null);
  const reloadSeq = useRef(0);
  const summarySeq = useRef(0);
  const saveSeq = useRef(0);
  // When each box last changed (a clock tick), to tell the boxes typed while a reload was in flight.
  const clock = useRef(0);
  const typedAt = useRef<Record<string, number>>({});

  // A new session starts with no base, no pending kind, no last date and no typed-box clock.
  useEffect(() => {
    baseRef.current = null;
    wantedRef.current = null;
    kindMark.current = -1;
    lastDate.current = null;
    typedAt.current = {};
  }, [live.n]);

  // The hidden last real date: the last answer's, else the loaded form's.
  const base = (): string => baseRef.current ?? (shownRef.current ? prevEffectiveBase(shownRef.current) : "");
  // The values to send: the held boxes of this form, without kind and the CSRF token, with the overrides applied.
  const sendValues = (overrides: FormValues = {}): FormValues =>
    valuesToSend(allFieldsRef.current, { ...heldRef.current, ...overrides });
  const typedSince = (start: number) =>
    new Set(Object.keys(typedAt.current).filter((name) => typedAt.current[name] > start));

  // Applies a form answer: the boxes merge (what was typed during the request is kept), the base follows unless a save
  // was sent after the reload, and the form becomes the shown one on the given type.
  const applyForm = (
    next: EventFormOut,
    type: string,
    keep: ReadonlySet<string>,
    saveAdvanced: boolean,
    summaryAdvanced: boolean,
  ) => {
    const merged = mergeFormAfterRefresh(heldRef.current, next, keep);
    for (const [name, value] of Object.entries(merged)) setField(name, value);
    heldRef.current = { ...heldRef.current, ...merged };
    if (!saveAdvanced) baseRef.current = next.prev_effective;
    wantedRef.current = null;
    kindMark.current = -1;
    const switched = liveRef.current.activeType !== type;
    setLive((prev) => ({ ...prev, activeType: type, reloaded: next }));
    options.onFormApplied?.(next, { keepErrors: saveAdvanced, keepSummary: saveAdvanced || summaryAdvanced });
    if (switched) onKindChangeRef.current?.(type);
  };

  // A date or kind reload. Latest-request-wins: an answer older than a newer reload, or one after the session ended, is
  // ignored. A failure keeps every value and shows the message (the stale text for a 404). Returns the reload's number.
  const reload = (
    type: string,
    overrides: FormValues,
    apply: (next: EventFormOut, keep: ReadonlySet<string>, saveAdvanced: boolean, summaryAdvanced: boolean) => void,
  ): number => {
    const mine = ++reloadSeq.current;
    const session = liveRef.current.n;
    const start = clock.current;
    const saveMark = saveSeq.current;
    const summaryMark = summarySeq.current;
    const stillWanted = () => isCurrent() && liveRef.current.n === session && mine === reloadSeq.current;
    loadEventForm(queryClient, pk, type, { values: sendValues(overrides), prev_effective: base() })
      .then((next) => {
        if (stillWanted()) apply(next, typedSince(start), saveSeq.current !== saveMark, summarySeq.current !== summaryMark);
      })
      .catch((error: unknown) => {
        if (!stillWanted()) return;
        const failure = error as Partial<ApiFailure>;
        if (failure.status === 404) void invalidateEmployee(queryClient, pk, ["work", "activity"]);
        lastDate.current = null;
        wantedRef.current = null;
        kindMark.current = -1;
        options.onReloadFailed?.(loadMessagesOf(failure));
      });
    return mine;
  };

  // A committed change of «effective» reloads the form with the date typed. The normalised text is sent, as the date box
  // shows it after its blur.
  const reloadDate = (raw: string) => {
    const value = normalise(raw) ?? raw;
    if (value === lastDate.current) return;
    lastDate.current = value;
    const typeNow = wantedRef.current ?? liveRef.current.activeType;
    reload(typeNow, { [EFFECTIVE]: value }, (next, keep, saveAdv, sumAdv) =>
      applyForm(next, typeNow, keep, saveAdv, sumAdv),
    );
  };

  // The kind select: reloads the other type's form with the typed values, then switches to it (no open animation: the
  // answer says reload). Picking the shown type again cancels a pending kind reload, and nothing else.
  const pickKind = (next: string): void => {
    if (next === liveRef.current.activeType) {
      if (kindMark.current === reloadSeq.current) {
        reloadSeq.current += 1;
        wantedRef.current = null;
        kindMark.current = -1;
      }
      return;
    }
    wantedRef.current = next;
    kindMark.current = reload(next, {}, (answer, keep, saveAdv, sumAdv) =>
      applyForm(answer, next, keep, saveAdv, sumAdv),
    );
  };

  // Any other named box refreshes the summary line only: its answer never replaces a value or an error. A summary answer
  // older than a newer summary, a reload or a save is ignored.
  const refreshSummary = () => {
    const mine = ++summarySeq.current;
    const session = liveRef.current.n;
    const reloadMark = reloadSeq.current;
    const saveMark = saveSeq.current;
    loadEventForm(queryClient, pk, wantedRef.current ?? liveRef.current.activeType, {
      values: sendValues(),
      prev_effective: base(),
    })
      .then((next) => {
        if (!isCurrent() || liveRef.current.n !== session) return;
        if (mine !== summarySeq.current || reloadSeq.current !== reloadMark || saveSeq.current !== saveMark) return;
        options.onSummary?.({ summary: next.summary, when: next.when });
      })
      .catch(() => undefined);
  };

  // A committed change (a native change event inside the form, as Django's hx-trigger="change") reloads or refreshes. Only
  // named boxes of this form count: an unnamed control inside the form (a combo's typing box) asks nothing. The order
  // block sits outside the summary and the summary never reads its boxes, so an order box asks nothing either. One
  // document listener, checked against the form, so a remounted form needs no re-attach.
  const onCommit = (event: Event) => {
    const box = event.target as HTMLInputElement | null;
    if (!box || !formRef.current?.contains(box)) return;
    if (!allFieldsRef.current.some((field) => field.name === box.name)) return;
    if (box.name === EFFECTIVE) reloadDate(box.value);
    else if (refreshKindFor(box.name) === "summary" && !box.name.startsWith("order-")) refreshSummary();
  };
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;
  useEffect(() => {
    const listener = (event: Event) => commitRef.current(event);
    document.addEventListener("change", listener);
    return () => document.removeEventListener("change", listener);
  }, []);

  return {
    base,
    setBase: (value: string) => {
      baseRef.current = value;
    },
    sendValues,
    pickKind,
    noteTyped(name: string, value: string) {
      heldRef.current = { ...heldRef.current, [name]: value };
      clock.current += 1;
      typedAt.current[name] = clock.current;
    },
    // A save is sent: a reload or summary answer asked before it is older and must not overwrite the refusal's answer.
    noteSave() {
      saveSeq.current += 1;
    },
  };
}
