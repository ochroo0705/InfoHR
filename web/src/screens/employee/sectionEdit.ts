import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  fieldErrorsFor,
  invalidateEmployee,
  useSaveSection,
  type EmployeeWriteResultOut,
  type FieldErrors,
} from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import type { components } from "../../api/schema";
import { useUnsavedFlag } from "../../lib/unsaved";
import { captureBase, dropBase, effectiveLoaded } from "./loadedBase";
import { SAVE_FAILED_TEXT } from "./PageForm";

// The on-the-spot state of one personal field section (`_on_spot_fields.html`, UI_RULES §2f). Each section keeps its own
// edits, clash choices, errors and snapshot, so two sections never share a save. The edits hold only the names the user
// changed; a value set back to the stored one is dropped, as PageForm does. The base of an edit (loadedBase.ts) is the
// snapshot value from the moment the edit began; a save sends it for that name, so a refetch cannot make a stale edit
// look seen.

export type PersonalSectionOut = components["schemas"]["EmployeePersonalSectionOut"];
export type PersonalFieldOut = PersonalSectionOut["fields"][number];
export type Resolve = "mine" | "theirs";

// The value the server holds for a field, as the browser would post it: a checkbox is "on" when ticked, else "".
export function storedValueOf(field: PersonalFieldOut): string {
  if (field.kind === "checkbox") return field.checked ? "on" : "";
  return field.value;
}

// The edits that differ from the stored values. The save sends exactly these names.
export function changedNames(edits: Record<string, string>, fields: PersonalFieldOut[]): Record<string, string> {
  const stored = new Map(fields.map((field) => [field.name, storedValueOf(field)] as const));
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(edits)) {
    if (stored.get(name) !== value) out[name] = value;
  }
  return out;
}

// Drops the edits that equal the stored value (after a refetch). Returns the same object when nothing is dropped.
export function pruneEdits(edits: Record<string, string>, fields: PersonalFieldOut[]): Record<string, string> {
  const kept = changedNames(edits, fields);
  return Object.keys(kept).length === Object.keys(edits).length ? edits : kept;
}

// The record without the given names. Returns the same object when none of them is in it.
function omitNames<T>(record: Record<string, T>, names: string[]): Record<string, T> {
  if (!names.some((name) => name in record)) return record;
  return Object.fromEntries(Object.entries(record).filter(([name]) => !names.includes(name)));
}

export type SectionEdit = {
  edits: Record<string, string>;
  resolves: Record<string, Resolve>;
  errors: FieldErrors;
  formErrors: string[];
  // The snapshot the next save starts from: the server's, or the fresh one a refused or saved request brought back.
  loaded: string;
  pending: boolean;
  // True while there are edits or the last save failed: the strip shows and the form carries data-dirty.
  dirty: boolean;
  // Counts the refused saves, so the form can bring the first error into view.
  errorTick: number;
  setValue: (name: string, value: string) => void;
  setResolve: (name: string, choice: Resolve) => void;
  save: () => Promise<void>;
  cancel: () => void;
};

export function useSectionEdit(pk: number, section: PersonalSectionOut): SectionEdit {
  const queryClient = useQueryClient();
  const mutation = useSaveSection(pk, section.name);
  const [edits, setEdits] = useState<Record<string, string>>({});
  // The base of each edited name: its value in the snapshot from when the edit began (loadedBase.ts), by snapshot key.
  const [bases, setBases] = useState<Record<string, unknown>>({});
  const [resolves, setResolves] = useState<Record<string, Resolve>>({});
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  // The snapshot a refused or saved request brought back. Dropped when the section refetches, which brings its own.
  const [fresh, setFresh] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [errorTick, setErrorTick] = useState(0);
  const inFlight = useRef(false);
  // The edits as rendered now: a save's answer reads what the user typed while the request was in flight.
  const editsRef = useRef(edits);
  editsRef.current = edits;

  useEffect(() => {
    setFresh(null);
  }, [section.loaded]);

  // A refetch keeps the user's edits. An edit that now equals the stored value is dropped, with its base and its errors.
  useEffect(() => {
    const kept = pruneEdits(edits, section.fields);
    if (kept === edits) return;
    const dropped = Object.keys(edits).filter((name) => !(name in kept));
    setEdits(kept);
    setBases((prev) => dropped.reduce((base, name) => dropBase(base, name), prev));
    setErrors((prev) => omitNames(prev, dropped));
    setResolves((prev) => omitNames(prev, dropped));
    // Runs when the fields change; the edits it reads are the ones rendered with those fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section.fields]);

  const loaded = fresh ?? section.loaded;
  const failed = formErrors.length > 0 || Object.keys(errors).length > 0;
  const dirty = Object.keys(edits).length > 0 || failed;
  // A dirty section (or one whose last save failed) is an unsaved owner: "section:<name>" (unsaved.ts).
  useUnsavedFlag("section:" + section.name, dirty);

  const clearAll = () => {
    setEdits({});
    setBases({});
    setResolves({});
    setErrors({});
    setFormErrors([]);
    setFresh(null);
  };

  const setValue = (name: string, value: string) => {
    const field = section.fields.find((f) => f.name === name);
    const stored = field ? storedValueOf(field) : undefined;
    const same = value === stored;
    const wasEdited = name in edits;
    // The base comes from the snapshot the boxes display (the query data), never from a refused save's snapshot: the user
    // typed over what is on screen, not over what a colleague saved meanwhile.
    const snapshot = section.loaded;
    setEdits((prev) => {
      const copy = { ...prev };
      if (same) {
        delete copy[name];
      } else {
        copy[name] = value;
      }
      return copy;
    });
    // The base is taken when the edit begins, from the snapshot valid at that moment; it is dropped when the edit is.
    setBases((prev) => {
      if (same) return dropBase(prev, name);
      return wasEdited ? prev : captureBase(prev, name, snapshot);
    });
  };

  const setResolve = (name: string, choice: Resolve) => {
    setResolves((prev) => ({ ...prev, [name]: choice }));
  };

  const save = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    const values = changedNames(edits, section.fields);
    const sentNames = Object.keys(values);
    const resolve: Record<string, Resolve> = {};
    for (const [name, entry] of Object.entries(errors)) {
      if (entry.conflict) resolve[name] = resolves[name] ?? "mine";
    }
    const snapshot = effectiveLoaded(loaded, bases, sentNames);
    try {
      const result: EmployeeWriteResultOut = await mutation.mutateAsync({ values, resolve, loaded: snapshot });
      if (result.ok) {
        // Only what was sent goes, and only where the edit still holds the sent value. An edit typed while the request was
        // in flight stays, with its base.
        const current = editsRef.current;
        const done = sentNames.filter((name) => current[name] === values[name]);
        setEdits((prev) => omitNames(prev, done));
        // Every base goes: the snapshot the save returned is the current one, and a kept edit (typed in flight, even on a
        // name just sent) must not send the value its base held before this save.
        setBases({});
        setErrors({});
        setFormErrors([]);
        setResolves({});
        setFresh(result.loaded || null);
      } else {
        const conflicted = Object.keys(result.conflicts).filter((name) => result.conflicts[name]);
        setErrors(fieldErrorsFor(result));
        setFormErrors(result.form_errors);
        setResolves((prev) => Object.fromEntries(conflicted.map((name) => [name, prev[name] ?? "mine"])));
        // A conflicted name's base goes: the user now picks mine or theirs. Other names keep theirs.
        setBases((prev) => conflicted.reduce((base, name) => dropBase(base, name), prev));
        if (result.loaded) setFresh(result.loaded);
        setErrorTick((tick) => tick + 1);
      }
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      const messages = failure.formErrors ?? [];
      setFormErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
      const fields = failure.fieldErrors ?? {};
      setErrors(Object.fromEntries(Object.entries(fields).map(([name, list]) => [name, { errors: [...list] }])));
      setErrorTick((tick) => tick + 1);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  // «Болих» reloads the section's data (as Django's cancel reloads the fields), then drops the local state.
  const cancel = () => {
    void invalidateEmployee(queryClient, pk, ["personal"]);
    clearAll();
  };

  return {
    edits,
    resolves,
    errors,
    formErrors,
    loaded,
    pending,
    dirty,
    errorTick,
    setValue,
    setResolve,
    save,
    cancel,
  };
}
