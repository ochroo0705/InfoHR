import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  fieldErrorsFor,
  invalidateEmployee,
  usePageForm,
  useSavePage,
  type FieldErrors,
  type EmployeeWriteResultOut,
} from "../../api/employeeWrites";
import type { ApiFailure } from "../../api/mutate";
import { showSection } from "./scrollSpy";
import { useUnsavedFlag } from "../../lib/unsaved";
import { captureBase, dropBase, effectiveLoaded, type Base } from "./loadedBase";

// The page form of the employee page (Django's `form` and `si_form` in detail.html): one state for every box whose value
// goes out with the page save. The provider holds the user's edits only (names the user changed); the stored values
// come from the page-form query. A section that is not on the page form does not go through here.

// Django's text for a save that failed with no message of its own (a 4xx without form_errors).
export const SAVE_FAILED_TEXT = "Мэдээллийг хадгалж чадсангүй.";

export type Resolve = "mine" | "theirs";
type Choice = { value: string; label: string };
type Snapshot = { loaded: string; siLoaded: string };

// What a box reads and does. A name the page form does not have is `editable: false` (nothing to bind).
export type PageField =
  | { editable: false; name: string }
  | {
      editable: true;
      name: string;
      kind: string;
      label: string;
      // The edit when the user changed the box, else the stored value.
      value: string;
      choice: string;
      checked: boolean;
      choices: Choice[];
      combo: boolean;
      placeholder: string;
      // Django's required flag for this box, as the page form sends it (the header boxes show it as `required`).
      required: boolean;
      error?: string[];
      // The stored value after a clash: shown as the "theirs" choice.
      conflict?: string;
      // True when the box holds an edit that differs from the stored value (the violet edge).
      changed: boolean;
      resolve: Resolve;
      set: (value: string) => void;
      setResolve: (value: Resolve) => void;
    };

export type PageFormState = {
  enabled: boolean;
  dirty: boolean;
  saving: boolean;
  // True while the last save left errors on screen (the bar stays visible).
  failed: boolean;
  formErrors: string[];
  photo: File | null;
  photoClear: boolean;
  setPhoto: (file: File | null) => void;
  setPhotoClear: (clear: boolean) => void;
  save: () => Promise<void>;
  cancel: () => void;
  field: (name: string) => PageField;
  // The error messages the last save gave a name, for a box that is not a page-form field (the photo control).
  errorsOf: (name: string) => string[];
};

const PageFormContext = createContext<PageFormState | null>(null);

// The page form's state for the save bar and for the page's own boxes. Must be used inside PageFormProvider.
export function usePageFormState(): PageFormState {
  const state = useContext(PageFormContext);
  if (!state) throw new Error("usePageFormState needs PageFormProvider");
  return state;
}

// One box of the page form, by its HTML name (`first-name`, `si-salary`, ...).
export function usePageField(name: string): PageField {
  return usePageFormState().field(name);
}

// Drops the edits that equal the stored value. Returns the same object when nothing is dropped.
function pruneEqual(edits: Record<string, string>, stored: Map<string, { value: string }>): Record<string, string> {
  let changed = false;
  const next: Record<string, string> = {};
  for (const [name, value] of Object.entries(edits)) {
    if (stored.get(name)?.value === value) {
      changed = true;
    } else {
      next[name] = value;
    }
  }
  return changed ? next : edits;
}

export function PageFormProvider({
  pk,
  enabled,
  section,
  children,
}: {
  pk: number;
  enabled: boolean;
  // The section in view (work, salary or personal): the save sends it as `tab`, so a failed save opens that tab again.
  section: string;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const page = usePageForm(pk, enabled);
  const mutation = useSavePage(pk);

  const stored = useMemo(
    () => new Map((page.data?.fields ?? []).map((f) => [f.name, f] as const)),
    [page.data],
  );

  const [edits, setEdits] = useState<Record<string, string>>({});
  const [resolves, setResolves] = useState<Record<string, Resolve>>({});
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [photo, setPhotoFile] = useState<File | null>(null);
  const [photoClear, setPhotoClearFlag] = useState(false);
  // The fresh snapshots of a refused or an ok save (the server's newest). Dropped when the page form refetches.
  const [fresh, setFresh] = useState<Partial<Snapshot>>({});
  const [saving, setSaving] = useState(false);
  const [errorTick, setErrorTick] = useState(0);
  const errorTab = useRef("");
  const inFlight = useRef(false);
  // The base of each edited name (see loadedBase.ts): the snapshot value the boxes DISPLAYED when the edit began (the page
  // form's `loaded` for plain names, its `si_loaded` for si- names), never a refused save's fresh snapshot. A refetch does
  // not move a base, so a save cannot take a colleague's newer value as the one the user saw.
  const [loadedBase, setLoadedBase] = useState<Base>({});
  const [siBase, setSiBase] = useState<Base>({});

  // A refetched page form carries new stored values and a new snapshot: the fresh ones are dropped. An edit that now
  // equals the stored value is no longer a change, and its base goes with it. Other edits stay (a section save elsewhere
  // refetches this query too), with their bases.
  useEffect(() => {
    setFresh({});
  }, [stored]);
  useEffect(() => {
    const same = Object.keys(edits).filter((name) => stored.get(name)?.value === edits[name]);
    if (same.length === 0) return;
    setEdits((prev) => pruneEqual(prev, stored));
    dropBases(same);
  }, [stored, edits]);

  // Drops the bases of the given names (their edits were removed, saved or refused).
  const dropBases = (names: string[]) => {
    const plain = names.filter((name) => !name.startsWith("si-"));
    const si = names.filter((name) => name.startsWith("si-"));
    if (plain.length > 0) setLoadedBase((prev) => plain.reduce((base, name) => dropBase(base, name), prev));
    if (si.length > 0) setSiBase((prev) => si.reduce((base, name) => dropBase(base, name, "si-"), prev));
  };

  // The snapshots the boxes display: the page form's query data.
  const displayedLoaded = () => page.data?.loaded ?? "";
  const displayedSiLoaded = () => page.data?.si_loaded ?? "";
  // The snapshot a save is checked against now: the fresh one of a refused save (the server's newest), else the displayed.
  const currentLoaded = () => fresh.loaded || displayedLoaded();
  const currentSiLoaded = () => fresh.siLoaded || displayedSiLoaded();

  const changed = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [name, value] of Object.entries(edits)) {
      if (stored.get(name)?.value !== value) out[name] = value;
    }
    return out;
  }, [edits, stored]);

  const dirty = Object.keys(changed).length > 0 || photo !== null || photoClear;
  const failed = formErrors.length > 0 || Object.keys(errors).length > 0;

  // The page form is one of the unsaved owners (unsaved.ts): the page's beforeunload and navigation guards read it.
  useUnsavedFlag("page", dirty);

  // After a refused save, the first box with an error comes into view; without one, the section the server names.
  useEffect(() => {
    if (errorTick === 0) return;
    const invalid = document.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (invalid) {
      if (typeof invalid.scrollIntoView === "function") invalid.scrollIntoView({ block: "center" });
    } else if (errorTab.current) {
      showSection(errorTab.current, true);
    }
  }, [errorTick]);

  const clearAll = () => {
    setEdits({});
    setResolves({});
    setErrors({});
    setFormErrors([]);
    setPhotoFile(null);
    setPhotoClearFlag(false);
    setFresh({});
    setLoadedBase({});
    setSiBase({});
  };

  const save = async () => {
    if (!enabled || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    const sent = changed;
    const sentPhoto = photo;
    const sentPhotoClear = photoClear;
    const edited = Object.keys(sent);
    const values: Record<string, string> = { ...sent };
    // Each edited name sends its base, so a newer stored value from a refetch is not taken as the one the user saw.
    const loaded = effectiveLoaded(
      currentLoaded(),
      loadedBase,
      edited.filter((name) => !name.startsWith("si-")),
    );
    const siLoaded = effectiveLoaded(
      currentSiLoaded(),
      siBase,
      edited.filter((name) => name.startsWith("si-")),
      "si-",
    );
    // The server refuses a save without the snapshots of the forms the user may change.
    if (loaded) values.loaded = loaded;
    if (siLoaded) values["si-loaded"] = siLoaded;
    for (const [name, entry] of Object.entries(errors)) {
      if (entry.conflict) values[`resolve-${name}`] = resolves[name] ?? "mine";
    }
    try {
      const result: EmployeeWriteResultOut = await mutation.mutateAsync({
        values,
        photo: sentPhoto,
        photoClear: sentPhotoClear,
        tab: section,
      });
      if (result.ok) {
        // Only what was sent is dropped, and only where the edit still holds the sent value: typing made while the
        // request was in flight stays. Every base is dropped too, and the ok result's snapshot (the server's fresh one)
        // is what the next save checks against until the refetch shows it: a kept edit must not keep a pre-save base
        // or the page's pre-save snapshot.
        setEdits((prev) => {
          const copy = { ...prev };
          for (const name of edited) {
            if (copy[name] === sent[name]) delete copy[name];
          }
          return copy;
        });
        setLoadedBase({});
        setSiBase({});
        setResolves({});
        setErrors({});
        setFormErrors([]);
        setFresh({ loaded: result.loaded, siLoaded: result.si_loaded });
        setPhotoFile((current) => (current === sentPhoto ? null : current));
        if (sentPhotoClear) setPhotoClearFlag(false);
      } else {
        setErrors(fieldErrorsFor(result));
        setFormErrors(result.form_errors);
        const conflicted = Object.keys(result.conflicts);
        // A conflicted name takes the fresh snapshot (applied below), so its base is dropped; the others keep theirs.
        dropBases(conflicted);
        setResolves((prev) => Object.fromEntries(conflicted.map((name) => [name, prev[name] ?? "mine"])));
        setFresh({ loaded: result.loaded, siLoaded: result.si_loaded });
        errorTab.current = result.tab;
        setErrorTick((tick) => tick + 1);
      }
    } catch (error) {
      const failure = error as Partial<ApiFailure>;
      const messages = failure.formErrors ?? [];
      setFormErrors(messages.length > 0 ? messages : [SAVE_FAILED_TEXT]);
      const fields = failure.fieldErrors ?? {};
      setErrors(Object.fromEntries(Object.entries(fields).map(([name, list]) => [name, { errors: [...list] }])));
      errorTab.current = "";
      setErrorTick((tick) => tick + 1);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  const cancel = () => {
    clearAll();
    void invalidateEmployee(queryClient, pk, ["page-form"]);
  };

  const setEdit = (name: string, next: string, storedValue: string) => {
    if (next === storedValue) {
      setEdits((prev) => {
        const copy = { ...prev };
        delete copy[name];
        return copy;
      });
      dropBases([name]);
      return;
    }
    // The base is the DISPLAYED snapshot when the edit begins; captureBase keeps a base already recorded.
    if (name.startsWith("si-")) {
      const snapshot = displayedSiLoaded();
      setSiBase((prev) => captureBase(prev, name, snapshot, "si-"));
    } else {
      const snapshot = displayedLoaded();
      setLoadedBase((prev) => captureBase(prev, name, snapshot));
    }
    setEdits((prev) => ({ ...prev, [name]: next }));
  };

  const field = (name: string): PageField => {
    const server = stored.get(name);
    if (!server) return { editable: false, name };
    const edit = edits[name];
    const entry = errors[name];
    return {
      editable: true,
      name,
      kind: server.kind,
      label: server.label,
      value: edit ?? server.value,
      choice: server.choice,
      checked: edit !== undefined ? edit === "on" : server.checked,
      choices: server.choices,
      combo: server.combo,
      placeholder: server.placeholder,
      required: server.required,
      error: entry && entry.errors.length > 0 ? entry.errors : undefined,
      conflict: entry?.conflict,
      changed: edit !== undefined && edit !== server.value,
      resolve: resolves[name] ?? "mine",
      set: (next) => setEdit(name, next, server.value),
      setResolve: (choice) => setResolves((prev) => ({ ...prev, [name]: choice })),
    };
  };

  const value: PageFormState = {
    enabled,
    dirty,
    saving,
    failed,
    formErrors,
    photo,
    photoClear,
    setPhoto: setPhotoFile,
    setPhotoClear: setPhotoClearFlag,
    save,
    cancel,
    field,
    errorsOf: (name) => errors[name]?.errors ?? [],
  };

  return <PageFormContext.Provider value={value}>{children}</PageFormContext.Provider>;
}

// The page's <form id="emp-form"> (detail.html:6). Django's form is EMPTY: the boxes join it with their `form="emp-form"`
// attribute, so Enter in a box and the save bar's «Хадгалах» (type="submit") submit it. The sections' own forms can sit
// anywhere on the page. This element has no children.
export function PageFormElement() {
  const form = usePageFormState();
  return (
    <form
      id="emp-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void form.save();
      }}
    />
  );
}
