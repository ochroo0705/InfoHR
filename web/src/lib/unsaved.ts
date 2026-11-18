import { useEffect, useSyncExternalStore } from "react";
import { confirm } from "../widgets/confirm";

// The unsaved-changes registry: the React side of Django's sections.js guard (a page that holds unsaved edits asks before
// the browser closes it, and before the app leaves it). Anything that holds unsaved edits registers a key while it is
// dirty:
//   "page"            the employee page form (PageForm.tsx, useUnsavedFlag("page", dirty))
//   "section:<name>"  one on-the-spot field section (sectionEdit.ts, useUnsavedFlag("section:" + name, dirty))
//   "list:<kind>"     an inline list's unsaved edits: InlineRow (an open row) and RowModal (an open pop-up), per list kind
// A key is dirty while it is set to true. Removing a key (setUnsaved(key, false), or the owner unmounting) clears it.

const dirtyKeys = new Set<string>();
const listeners = new Set<() => void>();
let revision = 0;

export function setUnsaved(key: string, dirty: boolean): void {
  if (dirtyKeys.has(key) === dirty) return;
  if (dirty) dirtyKeys.add(key);
  else dirtyKeys.delete(key);
  revision += 1;
  for (const listener of [...listeners]) listener();
}

export function isUnsaved(key: string): boolean {
  return dirtyKeys.has(key);
}

export function anyUnsaved(): boolean {
  return dirtyKeys.size > 0;
}

export function subscribeUnsaved(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function currentRevision(): number {
  return revision;
}

// Changes every time the registry changes, so a component can re-read it (a group opens for a dirty section).
export function useUnsavedRevision(): number {
  return useSyncExternalStore(subscribeUnsaved, currentRevision);
}

// Registers one owner's dirty state under a key. The key is cleared when the owner unmounts.
export function useUnsavedFlag(key: string, dirty: boolean): void {
  useEffect(() => {
    setUnsaved(key, dirty);
  }, [key, dirty]);
  useEffect(() => () => setUnsaved(key, false), [key]);
}

// Django's beforeunload guard: while anything is unsaved, a close or reload of the tab asks the browser first. The listener
// lives as long as the mounting page; it does nothing while the registry is clean.
export function useUnsavedGuard(): void {
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!anyUnsaved()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);
}

export const LEAVE_MESSAGE = "Хадгалаагүй өөрчлөлт алдагдана. Үргэлжлүүлэх үү?";
export const LEAVE_OK = "Үргэлжлүүлэх";

// Resolves true when the app may leave the page: nothing is unsaved, or the user accepts losing the edits. The app runs on
// BrowserRouter (not a data router), so react-router's useBlocker is not available; the in-app check is made where the app
// starts a navigation (viewTransition.ts useTransitionNavigate).
export async function confirmLeave(): Promise<boolean> {
  if (!anyUnsaved()) return true;
  return confirm(LEAVE_MESSAGE, { ok: LEAVE_OK });
}
