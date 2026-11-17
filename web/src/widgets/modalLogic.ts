// Pure decision helpers for the React pop-up (Modal.tsx). Port of the pop-up part of app/static/js/modal.js:
// pickTopShell, shouldAnimateRemoval and tryClose keep the legacy rules. The DOM part of modal.js (the ✕, the document
// listeners, the MutationObserver) becomes React state in Modal.tsx. Shells here are plain objects, so the tests need no DOM.

// The question before a pop-up with typed input is closed (modal.js ASK, UI_RULES §6).
export const DIRTY_CONFIRM_MESSAGE = "Оруулсан мэдээлэл хадгалагдахгүй. Хаах уу?";

// The error shape of the API (AGENTS.md): field_errors maps a field name to its messages, form_errors lists the rest.
export type ServerErrors = {
  field_errors?: Record<string, string[]>;
  form_errors?: string[];
  code?: string;
};

// Non-empty means the server sent back at least one message, so the pop-up holds data it must not lose.
export function hasServerErrors(errors: ServerErrors | null | undefined): boolean {
  if (!errors) return false;
  const fieldMessages = Object.values(errors.field_errors ?? {}).some((list) => list.length > 0);
  return fieldMessages || (errors.form_errors?.length ?? 0) > 0;
}

// ---- The stack of open pop-ups (the Escape order). Module-level: one page, one stack. ----

// An entry is one mounted pop-up. `leaving` is read live (a getter), so the stack never holds a stale value.
export type StackEntry = { readonly closable: boolean; readonly leaving: boolean };

const stack: StackEntry[] = [];

export function pushModal(entry: StackEntry): void {
  stack.push(entry);
}

export function popModal(entry: StackEntry): void {
  const index = stack.indexOf(entry);
  if (index >= 0) stack.splice(index, 1);
}

export function modalStack(): readonly StackEntry[] {
  return stack;
}

// The Escape picker: the topmost closable pop-up that is not already leaving (a leaving pop-up is on its way out).
export interface ShellState {
  readonly closable: boolean;
  readonly leaving: boolean;
}

export function pickTopShell<T extends ShellState>(shells: readonly T[]): T | null {
  for (let i = shells.length - 1; i >= 0; i -= 1) {
    if (shells[i].leaving) continue;
    if (shells[i].closable) return shells[i];
  }
  return null;
}

// Whether removing a shell plays the pop-up exit first. Only a pop-up shell does. A shell already leaving, a noAnim
// shell (rebuilt from an open pop-up) and a context without the exit are removed at once.
export interface RemovableShell {
  readonly isShell: boolean;
  readonly leaving: boolean;
  readonly noAnim: boolean;
}

export function shouldAnimateRemoval(el: RemovableShell, canLeave: boolean): boolean {
  if (!canLeave || !el.isShell) return false;
  // A second close on a leaving shell removes it at once (the exit is cut short, nothing is removed twice).
  if (el.leaving || el.noAnim) return false;
  return true;
}

// Closes a pop-up through the dirty check. `ask` is the in-app confirm in the browser; tests pass their own. A clean
// pop-up closes at once (no await runs). A dirty one closes only when `ask` says yes. A pop-up already leaving is not
// closed again, and no second prompt is shown for it.
export interface CloseTarget {
  readonly dirty: boolean;
  readonly leaving: boolean;
  close(): void;
}

export async function tryClose(
  shell: CloseTarget,
  ask: (message: string) => boolean | Promise<boolean>,
): Promise<void> {
  if (shell.leaving) return;
  if (shell.dirty && !(await ask(DIRTY_CONFIRM_MESSAGE))) return;
  if (shell.leaving) return;  // closed by another path while the question was open
  shell.close();
}
