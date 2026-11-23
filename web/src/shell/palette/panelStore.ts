// The open flag of the assistant panel. Port of the open-flag part of app/static/js/thread_store.js (createThreadStore):
// the same sessionStorage key ("assistant-thread-<userId>") and the same value shape ({"open": boolean, "items": [...]}),
// so step 6 can add the thread without a migration. The thread items are not handled here.
// Every storage call is guarded: a blocked or full storage just means the flag is not kept, and nothing here throws.
// A null storage keeps the flag in memory for the life of the store.

export type PanelStore = {
  isOpen(): boolean;
  setOpen(open: boolean): void;
};

export function panelStoreKey(userId: number): string {
  return "assistant-thread-" + userId;
}

// The stored object, or null when the value is missing, corrupt, or not a plain object (an array counts as not one).
function readObject(storage: Storage, key: string): Record<string, unknown> | null {
  try {
    const raw = storage.getItem(key);
    if (raw == null) return null;
    const data: unknown = JSON.parse(raw);
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function createPanelStore(storage: Storage | null, userId: number): PanelStore {
  const key = panelStoreKey(userId);
  let memoryOpen = false;

  return {
    isOpen(): boolean {
      if (!storage) return memoryOpen;
      const data = readObject(storage, key);
      return data !== null && data.open === true;
    },

    setOpen(open: boolean): void {
      if (!storage) {
        memoryOpen = !!open;
        return;
      }
      // Keep the stored items exactly as they are (not cleaned here; step 6 cleans them on read). Only the flag changes.
      // A missing or corrupt value starts an empty thread.
      const data = readObject(storage, key);
      const items = data && Array.isArray(data.items) ? data.items : [];
      try {
        storage.setItem(key, JSON.stringify({ open: !!open, items }));
      } catch {
        // storage blocked or full: the flag is not kept this time
      }
    },
  };
}
