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

// The value of a parent control on the page, read like select.js does: the first control with that name. "" when none.
function readParentValue(parent: string): string {
  const control = document.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${parent}"]`);
  return control?.value ?? "";
}

// The pop-up of the open request. It waits for the list's label (the modal title) from the lists index; if the index
// fails, the slug stands in for the label.
function OpenQuickAdd({ request, onClose }: { request: OpenRequest; onClose: () => void }) {
  const index = useListsIndex("");
  const label = index.data?.items.find((item) => item.slug === request.slug)?.label ?? (index.isError ? request.slug : undefined);
  if (label === undefined) return null;
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

export interface QuickAddApi {
  canAdd: boolean;
  // The Select props for a field's `add` info. `null` or `undefined` (not addable) gives no props.
  selectProps: (add: QuickAddAdd | null | undefined, onPicked: QuickAddPicked) => QuickAddSelectProps;
}

// Outside a provider (a test or a page without the shell) nothing can be added: canAdd is false and no props are given.
export function useQuickAdd(): QuickAddApi {
  const ctx = useContext(QuickAddContext);
  const open = ctx?.open;
  const canAdd = ctx?.canAdd ?? false;

  const selectProps = useCallback(
    (add: QuickAddAdd | null | undefined, onPicked: QuickAddPicked): QuickAddSelectProps => {
      if (!add || !open) return {};
      const addUrl = `/api/v1/lists/${add.slug}/quick`;
      if (!add.modal) return { addUrl, canAdd };
      return {
        addUrl,
        canAdd,
        addModal: true,
        onAddModal: (text: string) =>
          open({
            slug: add.slug,
            initialName: text,
            parentValue: add.parent === null ? undefined : readParentValue(add.parent),
            onPicked,
          }),
      };
    },
    [open, canAdd],
  );

  return useMemo(() => ({ canAdd, selectProps }), [canAdd, selectProps]);
}
