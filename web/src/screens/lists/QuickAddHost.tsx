import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useListsIndex } from "../../api/lists";
import type { components } from "../../api/schema";
import { useMeta } from "../../shell/useMeta";
import type { SelectProps } from "../../widgets/Select";
import { QuickAddModal } from "./QuickAddModal";

// The quick-add host: one «+ нэмэх» pop-up for every form dropdown on the signed-in frame (docs/UI_RULES.md §2a).
// A field description carries `add: {slug, modal, parent}` when its list can take a new entry (null otherwise). The
// leaf that draws the dropdown calls `useQuickAdd().selectProps(field.add, onPicked)` and spreads the result on Select:
// a plain add is posted by Select itself to `/api/v1/lists/<slug>/quick`; a `modal` add opens QuickAddModal here.
// QuickAddProvider is mounted once in the shell, so at most one pop-up can be open.

export type QuickAddAdd = components["schemas"]["FieldAddOut"];

// The props a leaf spreads on Select to get the add line (only what the quick add needs).
export type QuickAddSelectProps = Pick<SelectProps, "addUrl" | "canAdd" | "addModal" | "onAddModal">;

// Called with the picked entry's value and label (the value as the Select reads it, a string).
export type QuickAddPicked = (value: string, label: string) => void;

interface OpenRequest {
  slug: string;
  initialName: string;
  // The value of the list's parent field as the page shows it; undefined when the list has no parent.
  parentValue: string | undefined;
  onPicked: QuickAddPicked;
}

interface QuickAddContextValue {
  canAdd: boolean;
  open: (request: OpenRequest) => void;
}

const QuickAddContext = createContext<QuickAddContextValue | null>(null);

// The Add line of a quick-add select: the user holds lists.manage_lists. The server never sends the right in the
// field; the frontend reads it from /meta (Select's canAdd rule).
export function useCanAddLists(): boolean {
  const meta = useMeta();
  return meta.data?.user?.perms.includes("lists.manage_lists") ?? false;
}

// Anything the parent control can be searched in (the document, a form or a dialog).
interface ParentRoot {
  querySelector(selectors: string): Element | null;
}

// Where the parent control is looked for, read when the add is clicked: the form of the focused control (the combo
// input has the focus then), else its dialog, else the whole document. Two pages can hold the same name (a dialog over
// a page), so the nearest scope wins.
function parentRoot(): ParentRoot {
  const active = document.activeElement;
  return active?.closest("form") ?? active?.closest("[role=dialog]") ?? document;
}

// The value of a parent control, read like select.js does: the first control with that name in `root`. "" when none.
function readParentValue(parent: string, root: ParentRoot): string {
  const control = root.querySelector(`[name="${parent}"]`) as HTMLInputElement | HTMLSelectElement | null;
  return control?.value ?? "";
}

// The pop-up of the open request. It opens at once; the title is the list's label from the lists index when the index has
// the row, else the slug (while the index loads, has no such row, or failed).
function OpenQuickAdd({ request, onClose }: { request: OpenRequest; onClose: () => void }) {
  const index = useListsIndex("");
  const label = index.data?.items.find((item) => item.slug === request.slug)?.label ?? request.slug;
  return (
    <QuickAddModal
      slug={request.slug}
      label={label}
      initialName={request.initialName}
      parentValue={request.parentValue}
      onDone={(entry) => {
        request.onPicked(String(entry.value), entry.label);
        onClose();
      }}
      onClose={onClose}
    />
  );
}

export function QuickAddProvider({ children }: { children: ReactNode }) {
  const canAdd = useCanAddLists();
  const [request, setRequest] = useState<OpenRequest | null>(null);
  // An opener is ignored while a pop-up is open: the overlay blocks clicks, and replacing it would lose typed text.
  const open = useCallback((next: OpenRequest) => setRequest((prev) => prev ?? next), []);
  const close = useCallback(() => setRequest(null), []);
  const value = useMemo(() => ({ canAdd, open }), [canAdd, open]);

  return (
    <QuickAddContext.Provider value={value}>
      {children}
      {request ? <OpenQuickAdd request={request} onClose={close} /> : null}
    </QuickAddContext.Provider>
  );
}

export interface QuickAddSelectOptions {
  // The name the parent control carries in the DOM, when it differs from `add.parent` (a page that prefixes its names,
  // e.g. the hire page's `addr-city` for the server's `city`). Ignored when the list has no parent.
  parentName?: string;
}

export interface QuickAddApi {
  canAdd: boolean;
  // The Select props for a field's `add` info. `null` or `undefined` (not addable) gives no props.
  selectProps: (
    add: QuickAddAdd | null | undefined,
    onPicked: QuickAddPicked,
    options?: QuickAddSelectOptions,
  ) => QuickAddSelectProps;
}

export interface AddableOption {
  value: string;
  label: string;
}

// The entries a select got through the quick-add pop-up, on top of the choices the server sent. A modal add is not in
// those choices (they were sent before the entry existed), so the leaf that draws the select keeps them here. The list is
// dropped whenever the server's choices change by content (another parent, a refetch with other entries, a deleted
// entry), so an entry that is no longer valid does not stay as a ghost option. A new array with the same content keeps it.
// A plain add (Select's own list) does not come through here.
export function useAddedOptions(choices: readonly AddableOption[]): {
  options: AddableOption[];
  add: (value: string, label: string) => void;
} {
  const signature = useMemo(() => choices.map((choice) => choice.value).join("\u0001"), [choices]);
  const [added, setAdded] = useState<{ signature: string; items: AddableOption[] }>({ signature, items: [] });
  // The choices changed: the entries added against the old list are dropped. Setting state during render for the same
  // component (React's "adjusting state when a prop changes") re-renders at once; the guard makes that pass a no-op.
  let current = added;
  if (added.signature !== signature) {
    current = { signature, items: [] };
    setAdded(current);
  }

  const add = useCallback(
    (value: string, label: string) => {
      setAdded((prev) => {
        const base = prev.signature === signature ? prev.items : [];
        if (base.some((item) => item.value === value)) {
          return prev.signature === signature ? prev : { signature, items: base };
        }
        return { signature, items: [...base, { value, label }] };
      });
    },
    [signature],
  );

  const options = useMemo(
    () => [...choices, ...current.items.filter((item) => !choices.some((choice) => choice.value === item.value))],
    [choices, current.items],
  );

  return { options, add };
}

// Outside a provider (a test or a page without the shell) nothing can be added: canAdd is false and no props are given.
export function useQuickAdd(): QuickAddApi {
  const ctx = useContext(QuickAddContext);
  const open = ctx?.open;
  const canAdd = ctx?.canAdd ?? false;

  const selectProps = useCallback(
    (add: QuickAddAdd | null | undefined, onPicked: QuickAddPicked, options?: QuickAddSelectOptions): QuickAddSelectProps => {
      if (!add || !open) return {};
      const addUrl = `/api/v1/lists/${add.slug}/quick`;
      if (!add.modal) return { addUrl, canAdd };
      return {
        addUrl,
        canAdd,
        addModal: true,
        onAddModal: (text: string) => {
          // The parent is read now, when the add is clicked: the pop-up must see the page's value at that moment.
          const parentName = options?.parentName ?? add.parent;
          open({
            slug: add.slug,
            initialName: text,
            parentValue: add.parent === null ? undefined : readParentValue(parentName ?? "", parentRoot()),
            onPicked,
          });
        },
      };
    },
    [open, canAdd],
  );

  return useMemo(() => ({ canAdd, selectProps }), [canAdd, selectProps]);
}
